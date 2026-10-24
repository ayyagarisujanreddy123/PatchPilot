"""Bounded public HTTP GETs with DNS validation, numeric-IP pinning and TLS.

Resolver/connector/context constructor hooks are trusted test dependencies, never
URL/request options. Default connections bypass proxies and never use a cookie
jar, credentials, automatic redirects, or content decompression.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import math
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from patchpilot.webscan.models import HTTPResponse

MAX_BODY_BYTES = 512 * 1024
_MAX_HEADER_BYTES = 64 * 1024
_MAX_LINE_BYTES = 8192
_MAX_READ_OPERATIONS = 4096
_MAX_DNS_ANSWERS = 64
_REDIRECTS = {301, 302, 303, 307, 308}
_TRANSITION_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in (
        "::/96",
        "64:ff9b::/96",
        "64:ff9b:1::/48",
        "2001::/32",
        "2002::/16",
    )
)
_DNS_PROGRAM = """import json, socket, sys
host, port = json.loads(sys.stdin.read())
answers = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM, socket.IPPROTO_TCP)
print(json.dumps(list(dict.fromkeys(item[4][0] for item in answers))))
"""

Resolver = Callable[[str, int, float], Sequence[str]]
Connector = Callable[[str, int, float], socket.socket]


class PublicHTTPError(RuntimeError):
    """Credential-free failure safe to show to a website-assessment caller."""


def _public_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise PublicHTTPError("Website DNS returned an invalid address") from None
    if (
        "%" in value
        or not address.is_global
        or address.is_private
        or address.is_reserved
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or isinstance(address, ipaddress.IPv6Address)
        and (
            address.ipv4_mapped is not None
            or any(address in block for block in _TRANSITION_NETWORKS)
        )
    ):
        raise PublicHTTPError(
            "Only globally routable public website addresses are allowed"
        )
    return address.compressed


def validate_public_url(url: str) -> str:
    """Validate syntax without DNS; strip fragments and reject query secrets."""
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise ValueError("Enter a public HTTP(S) page URL of at most 2048 characters")
    if (
        any(ord(character) <= 32 or ord(character) == 127 for character in url)
        or "\\" in url
    ):
        raise ValueError("Website URLs cannot contain whitespace or control characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in unquote(url)):
        raise ValueError("Website URLs cannot contain encoded control characters")
    try:
        parts = urlsplit(url)
        port = parts.port
        host = parts.hostname
    except ValueError:
        raise ValueError("Enter a valid public HTTP(S) page URL") from None
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or not host:
        raise ValueError("Enter a complete public HTTP(S) page URL")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ValueError("Website URLs cannot contain credentials")
    if parts.query:
        raise ValueError("Use a public page URL without query parameters")
    if parts.netloc.endswith(":") or port is not None and port not in {80, 443}:
        raise ValueError("Public website assessment supports ports 80 and 443 only")
    if "%" in host:
        raise ValueError("Website hostnames cannot contain encoded or scoped addresses")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        try:
            host = _public_ip(host)
        except PublicHTTPError:
            raise ValueError("Enter a globally routable public website URL") from None
        authority = f"[{host}]" if literal.version == 6 else host
    else:
        if host.endswith(".."):
            raise ValueError("Enter a valid public website hostname")
        try:
            host = host.removesuffix(".").encode("idna").decode("ascii").lower()
        except UnicodeError:
            raise ValueError("Enter a valid public website hostname") from None
        labels = host.split(".")
        if (
            len(host) > 253
            or len(labels) < 2
            or labels[-1].isdigit()
            or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in labels
            )
            or host.endswith(
                (".localhost", ".local", ".internal", ".home.arpa", ".onion")
            )
        ):
            raise ValueError("Enter a valid public website hostname")
        authority = host
    default_port = 443 if scheme == "https" else 80
    if port is not None and port != default_port:
        authority += f":{port}"
    path = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
    canonical = urlunsplit((scheme, authority, path, "", ""))
    if len(canonical) > 2048:
        raise ValueError("Canonical website URL exceeds 2048 characters")
    return canonical


class _Deadline:
    def __init__(self, timeout_s: float):
        if not math.isfinite(timeout_s) or not 0 < timeout_s <= 60:
            raise ValueError(
                "Website request timeout must be finite and between 0 and 60 seconds"
            )
        self.end = time.monotonic() + timeout_s

    def remaining(self) -> float:
        remaining = self.end - time.monotonic()
        if remaining <= 0:
            raise PublicHTTPError("Website request exceeded its time limit")
        return remaining


def _resolve_public(host: str, port: int, timeout_s: float) -> Sequence[str]:
    # getaddrinfo has no portable cancellation API. A killed resolver subprocess
    # prevents abandoned DNS threads from accumulating after slow requests.
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-c", _DNS_PROGRAM],
            input=json.dumps([host, port]),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise PublicHTTPError("Website DNS lookup exceeded its time limit") from None
    except OSError:
        raise PublicHTTPError("Website DNS lookup could not be started") from None
    if result.returncode or len(result.stdout) > 65536:
        raise PublicHTTPError("Website hostname could not be resolved")
    try:
        answers = json.loads(result.stdout)
    except ValueError:
        raise PublicHTTPError("Website DNS returned an invalid response") from None
    if not isinstance(answers, list):
        raise PublicHTTPError("Website DNS returned an invalid response")
    return answers


def _connect_numeric(ip: str, port: int, timeout_s: float) -> socket.socket:
    address = ipaddress.ip_address(ip)
    connection = socket.socket(
        socket.AF_INET6 if address.version == 6 else socket.AF_INET,
        socket.SOCK_STREAM,
        socket.IPPROTO_TCP,
    )
    try:
        connection.settimeout(timeout_s)
        connection.connect((ip, port, 0, 0) if address.version == 6 else (ip, port))
        return connection
    except BaseException:
        connection.close()
        raise


class _BoundedFile:
    """Cap status/header/chunk lines and I/O operations around HTTPResponse."""

    def __init__(self, connection: socket.socket, deadline: _Deadline):
        self.raw = connection.makefile("rb")
        self.connection, self.deadline = connection, deadline
        self.line_bytes = self.operations = 0

    def _before(self) -> None:
        self.operations += 1
        if self.operations > _MAX_READ_OPERATIONS:
            raise PublicHTTPError("Website response exceeded its read-operation limit")
        self.connection.settimeout(self.deadline.remaining())

    def readline(self, size: int = -1) -> bytes:
        self._before()
        line = self.raw.readline(
            min(size, _MAX_LINE_BYTES + 1) if size >= 0 else _MAX_LINE_BYTES + 1
        )
        self.line_bytes += len(line)
        if len(line) > _MAX_LINE_BYTES or self.line_bytes > _MAX_HEADER_BYTES:
            raise PublicHTTPError("Website response headers exceeded the size limit")
        return line

    def read(self, size: int = -1) -> bytes:
        self._before()
        return self.raw.read(size)

    def read1(self, size: int = -1) -> bytes:
        self._before()
        return self.raw.read1(size)

    def close(self) -> None:
        self.raw.close()

    def flush(self) -> None:
        self.raw.flush()


class _ResponseSocket:
    def __init__(self, connection: socket.socket, deadline: _Deadline):
        self.connection, self.deadline = connection, deadline

    def makefile(self, mode: str) -> _BoundedFile:
        return _BoundedFile(self.connection, self.deadline)


class PublicHTTPClient:
    """Normal public GETs; every redirect and every DNS answer is revalidated."""

    def __init__(
        self,
        *,
        resolver: Resolver | None = None,
        connector: Connector | None = None,
        tls_context: ssl.SSLContext | None = None,
    ):
        self._resolver = resolver or _resolve_public
        self._connector = connector or _connect_numeric
        self._tls = tls_context or ssl.create_default_context()
        self._verify_tls_settings()

    def _verify_tls_settings(self) -> None:
        if self._tls.verify_mode != ssl.CERT_REQUIRED or not self._tls.check_hostname:
            raise ValueError(
                "TLS certificate and hostname verification must remain enabled"
            )

    def _addresses(self, host: str, port: int, deadline: _Deadline) -> tuple[str, ...]:
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        answers = (
            [host] if literal else self._resolver(host, port, deadline.remaining())
        )
        deadline.remaining()
        if not answers or len(answers) > _MAX_DNS_ANSWERS:
            raise PublicHTTPError("Website DNS returned no usable bounded address set")
        if any(not isinstance(address, str) for address in answers):
            raise PublicHTTPError("Website DNS returned an invalid address")
        # Validate the whole answer set before selecting a socket destination.
        return tuple(dict.fromkeys(_public_ip(address) for address in answers))

    def fetch(
        self, url: str, *, timeout_s: float = 15, max_redirects: int = 3
    ) -> tuple[HTTPResponse, ...]:
        deadline = _Deadline(timeout_s)
        if type(max_redirects) is not int or not 0 <= max_redirects <= 3:
            raise ValueError("Public website requests support at most three redirects")
        try:
            current = validate_public_url(url)
        except ValueError:
            raise PublicHTTPError(
                "Use a valid public HTTP(S) page URL without credentials or query parameters"
            ) from None
        chain: list[HTTPResponse] = []
        visited: set[str] = set()
        try:
            while True:
                if current in visited:
                    raise PublicHTTPError("Website redirects formed a loop")
                visited.add(current)
                response = self._fetch_one(current, deadline)
                chain.append(response)
                locations = [
                    value
                    for name, value in response.headers
                    if name.lower() == "location"
                ]
                if response.status not in _REDIRECTS or not locations:
                    return tuple(chain)
                if len(locations) != 1:
                    raise PublicHTTPError("Website returned ambiguous redirect headers")
                if len(chain) > max_redirects:
                    raise PublicHTTPError("Website exceeded the three-redirect limit")
                location = locations[0].strip(" \t")
                # urljoin/urlsplit discard embedded tabs; reject them before
                # normalization so redirect validation cannot erase controls.
                if any(
                    ord(character) <= 32 or ord(character) == 127
                    for character in location
                ):
                    raise PublicHTTPError(
                        "Website redirect contains invalid control characters"
                    )
                try:
                    current = validate_public_url(urljoin(current, location))
                except ValueError:
                    raise PublicHTTPError(
                        "Website redirect destination is not an allowed public page URL"
                    ) from None
        except PublicHTTPError:
            raise
        except ssl.SSLCertVerificationError:
            raise PublicHTTPError(
                "Website TLS certificate verification failed"
            ) from None
        except ssl.SSLError:
            raise PublicHTTPError("Website TLS connection failed") from None
        except (OSError, http.client.HTTPException, ValueError, OverflowError):
            raise PublicHTTPError(
                "Website response could not be collected within the safe request limits"
            ) from None

    def _fetch_one(self, url: str, deadline: _Deadline) -> HTTPResponse:
        started = time.monotonic()
        parts = urlsplit(url)
        host = parts.hostname
        assert host is not None
        port = parts.port or (443 if parts.scheme == "https" else 80)
        addresses = self._addresses(host, port, deadline)
        connection = None
        selected = ""
        for selected in addresses[:3]:
            try:
                connection = self._connector(
                    selected, port, min(5, deadline.remaining())
                )
                break
            except OSError:
                deadline.remaining()
        if connection is None:
            raise PublicHTTPError(
                "Website could not be reached at its validated public addresses"
            )
        active = [connection]
        timer: threading.Timer | None = None
        response = None

        def interrupt() -> None:
            try:
                active[0].shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        try:
            timer = threading.Timer(deadline.remaining(), interrupt)
            timer.daemon = True
            timer.start()
            tls_protocol = expiry = None
            if parts.scheme == "https":
                self._verify_tls_settings()
                connection = self._tls.wrap_socket(
                    connection, server_hostname=host, do_handshake_on_connect=False
                )
                active[0] = connection
                connection.settimeout(deadline.remaining())
                connection.do_handshake()
                tls_protocol = connection.version()
                not_after = connection.getpeercert().get("notAfter")
                if not_after:
                    expiry = datetime.fromtimestamp(
                        ssl.cert_time_to_seconds(not_after), UTC
                    ).isoformat()
            connection.settimeout(deadline.remaining())
            request = (
                f"GET {parts.path or '/'} HTTP/1.1\r\nHost: {parts.netloc}\r\n"
                "User-Agent: PatchPilot/0.1 PublicWebsiteAssessment\r\n"
                "Accept: text/html,application/xhtml+xml;q=0.9,text/plain;q=0.8,*/*;q=0.1\r\n"
                "Accept-Encoding: identity\r\nConnection: close\r\n\r\n"
            ).encode("ascii")
            connection.sendall(request)
            response = http.client.HTTPResponse(
                _ResponseSocket(connection, deadline), method="GET"
            )
            response.begin()
            if not 100 <= response.status <= 599:
                raise PublicHTTPError("Website returned an invalid HTTP status")
            headers = tuple(response.getheaders())
            lengths = [
                value.strip()
                for name, value in headers
                if name.lower() == "content-length"
            ]
            transfer = [
                value.strip().lower()
                for name, value in headers
                if name.lower() == "transfer-encoding"
            ]
            if (
                len(set(lengths)) > 1
                or transfer
                and lengths
                or any(value not in {"identity", "chunked"} for value in transfer)
                or any("\r" in value or "\n" in value for _, value in headers)
            ):
                raise PublicHTTPError(
                    "Website returned ambiguous or unsupported HTTP framing"
                )
            expected_length = response.length
            chunks: list[bytes] = []
            total = 0
            while total < MAX_BODY_BYTES:
                deadline.remaining()
                chunk = response.read1(min(65536, MAX_BODY_BYTES - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            truncated = total == MAX_BODY_BYTES and (
                expected_length is None or expected_length > MAX_BODY_BYTES
            )
            if (
                expected_length is not None
                and not truncated
                and total < expected_length
            ):
                raise PublicHTTPError(
                    "Website response ended before its declared length"
                )
            deadline.remaining()
            return HTTPResponse(
                url,
                response.status,
                headers,
                b"".join(chunks),
                truncated,
                round((time.monotonic() - started) * 1000),
                selected,
                tls_protocol,
                expiry,
            )
        finally:
            if timer is not None:
                timer.cancel()
            if response is not None:
                response.close()
            active[0].close()

"""Public GET security boundaries with explicit DNS/socket test injection."""

import gzip
import socket
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from patchpilot.webscan import network
from patchpilot.webscan.network import (
    PublicHTTPClient,
    PublicHTTPError,
    validate_public_url,
)

PUBLIC_IP = "93.184.216.34"


@pytest.mark.parametrize(
    "value",
    [
        "file:///etc/passwd",
        "ftp://example.com/",
        "http://localhost/",
        "http://intranet/",
        "http://127.0.0.1/",
        "http://0.0.0.0/",
        "http://10.0.0.1/",
        "http://169.254.169.254/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:8.8.8.8]/",
        "http://[64:ff9b::7f00:1]/",
        "http://[64:ff9b:1::a00:1]/",
        "http://[2002:7f00:1::]/",
        "http://224.0.0.1/",
        "http://2130706433/",
        "http://127.1/",
        "http://0177.0.0.1/",
        "http://user:password@example.com/",
        "http://@example.com/",
        "http://example.com:22/",
        "http://example.com:65536/",
        "http://example.com:/",
        "http://example.com\\@127.0.0.1/",
        "https://example.com/\n",
        "https://exam\tple.com/",
        "https://example.com/%0d%0aX-Test:1",
        "https://example.com/?token=do-not-leak-me",
        "https://example.com/" + "a" * 2048,
    ],
)
def test_url_validation_rejects_unsafe_or_credential_bearing_inputs(value):
    with pytest.raises(ValueError) as caught:
        validate_public_url(value)
    assert "do-not-leak-me" not in str(caught.value)
    assert "password" not in str(caught.value)


@pytest.mark.parametrize(
    "value,expected",
    [
        (
            "HTTPS://Example.COM:443/path.php#token=private",
            "https://example.com/path.php",
        ),
        ("http://example.com:80", "http://example.com/"),
        ("https://bücher.de/über.php", "https://xn--bcher-kva.de/%C3%BCber.php"),
        ("https://example.com./", "https://example.com/"),
        ("https://[2606:4700:4700::1111]/", "https://[2606:4700:4700::1111]/"),
    ],
)
def test_url_validation_is_pure_and_canonical(value, expected, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Pure validation must not perform DNS")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    assert validate_public_url(value) == expected


@pytest.fixture
def http_site():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            requests.append((self.path, tuple(self.headers.items())))
            try:
                if self.path == "/slow-headers":
                    self.wfile.write(b"HTTP/1.1 200 OK\r\nX-Slow: ")
                    self.wfile.flush()
                    for _ in range(30):
                        self.wfile.write(b"a")
                        self.wfile.flush()
                        time.sleep(0.04)
                    return
                if self.path == "/big-header":
                    self.wfile.write(
                        b"HTTP/1.1 200 OK\r\nX-Big: " + b"a" * 20000 + b"\r\n\r\n"
                    )
                    return
                if self.path == "/redirect":
                    self.reply(
                        302, b"redirect", [("Location", "http://example.net/final.php")]
                    )
                elif self.path == "/same-host-redirect":
                    self.reply(302, b"redirect", [("Location", "/final.php")])
                elif self.path == "/private-redirect":
                    self.reply(
                        302, b"redirect", [("Location", "http://127.0.0.1/admin")]
                    )
                elif self.path == "/query-redirect":
                    self.reply(
                        302,
                        b"redirect",
                        [("Location", "/final.php?token=do-not-leak-me")],
                    )
                elif self.path == "/control-redirect":
                    self.reply(
                        302,
                        b"redirect",
                        [("Location", "http://example.net/fi\tnal.php")],
                    )
                elif self.path == "/loop":
                    self.reply(302, b"redirect", [("Location", "/loop")])
                elif self.path.startswith("/chain/"):
                    number = int(self.path.rsplit("/", 1)[-1])
                    self.reply(302, b"redirect", [("Location", f"/chain/{number + 1}")])
                elif self.path == "/big":
                    self.reply(200, b"x" * (512 * 1024 + 4096))
                elif self.path == "/gzip":
                    self.reply(
                        200,
                        gzip.compress(b"private-to-transport-body", mtime=0),
                        [("Content-Encoding", "gzip")],
                    )
                elif self.path == "/slow-body":
                    self.send_response(200)
                    self.send_header("Content-Length", "30")
                    self.end_headers()
                    for _ in range(30):
                        self.wfile.write(b"x")
                        self.wfile.flush()
                        time.sleep(0.04)
                else:
                    self.reply(
                        200,
                        b"fresh public response",
                        [("Set-Cookie", "one=private"), ("Set-Cookie", "two=private")],
                    )
            except (OSError, ConnectionError):
                pass

        def reply(self, status, body, headers=()):
            self.send_response(status)
            for key, value in headers:
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, requests
    server.shutdown()
    server.server_close()


def client_for(server, *, resolver=None, tls_context=None, connections=None):
    def connect(ip, port, timeout_s):
        if connections is not None:
            connections.append((ip, port))
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        connection.settimeout(timeout_s)
        connection.connect(("127.0.0.1", server.server_port))
        return connection

    return PublicHTTPClient(
        resolver=resolver or (lambda host, port, timeout: [PUBLIC_IP]),
        connector=connect,
        tls_context=tls_context,
    )


def test_real_socket_get_pins_public_ip_and_never_sends_auth_cookie_or_compression(
    http_site, monkeypatch
):
    server, requests = http_site
    connections = []
    monkeypatch.setenv("HTTP_PROXY", "http://user:secret@127.0.0.1:1")
    client = client_for(server, connections=connections)
    responses = client.fetch("http://example.com/index.php#ignored", timeout_s=2)
    assert len(responses) == 1
    response = responses[0]
    assert response.status == 200 and response.body == b"fresh public response"
    assert response.url == "http://example.com/index.php"
    assert response.resolved_ip == PUBLIC_IP
    assert response.body_truncated is False
    assert (
        len([value for name, value in response.headers if name.lower() == "set-cookie"])
        == 2
    )
    assert connections == [(PUBLIC_IP, 80)]
    headers = {name.lower(): value for name, value in requests[0][1]}
    assert headers["host"] == "example.com"
    assert headers["accept-encoding"] == "identity"
    assert (
        not {"authorization", "cookie", "proxy-authorization", "referer"}
        & headers.keys()
    )


@pytest.mark.parametrize(
    "unsafe",
    [
        "127.0.0.1",
        "10.1.2.3",
        "169.254.169.254",
        "::1",
        "fc00::1",
        "fe80::1",
        "::ffff:127.0.0.1",
        "64:ff9b::a00:1",
        "64:ff9b:1::a00:1",
        "224.0.0.1",
    ],
)
def test_mixed_dns_answers_fail_before_any_connection(unsafe):
    connections = []
    client = PublicHTTPClient(
        resolver=lambda host, port, timeout: [PUBLIC_IP, unsafe],
        connector=lambda *args: connections.append(args),
    )
    with pytest.raises(PublicHTTPError):
        client.fetch("http://example.com/")
    assert not connections


def test_every_redirect_is_re_resolved_and_rebinding_fails_closed(http_site):
    server, requests = http_site
    names, connections = [], []

    def resolve(host, port, timeout):
        names.append(host)
        return [PUBLIC_IP] if len(names) == 1 else ["127.0.0.1"]

    with pytest.raises(PublicHTTPError):
        client_for(server, resolver=resolve, connections=connections).fetch(
            "http://example.com/same-host-redirect"
        )
    assert names == ["example.com", "example.com"]
    assert len(requests) == len(connections) == 1


def test_redirect_chain_preserves_raw_responses_and_changes_host(http_site):
    server, requests = http_site
    names = []

    def resolve(host, port, timeout):
        names.append(host)
        return [PUBLIC_IP]

    responses = client_for(server, resolver=resolve).fetch(
        "http://example.com/redirect"
    )
    assert [response.status for response in responses] == [302, 200]
    assert [response.url for response in responses] == [
        "http://example.com/redirect",
        "http://example.net/final.php",
    ]
    assert names == ["example.com", "example.net"]
    assert dict(requests[1][1])["Host"] == "example.net"


@pytest.mark.parametrize(
    "route", ["/private-redirect", "/query-redirect", "/control-redirect", "/loop"]
)
def test_unsafe_redirects_do_not_issue_a_second_get(http_site, route):
    server, requests = http_site
    with pytest.raises(PublicHTTPError) as caught:
        client_for(server).fetch("http://example.com" + route)
    assert len(requests) == 1
    assert "do-not-leak-me" not in str(caught.value)


def test_redirect_limit_is_three_and_finite(http_site):
    server, requests = http_site
    with pytest.raises(PublicHTTPError):
        client_for(server).fetch("http://example.com/chain/0", max_redirects=3)
    assert len(requests) == 4


def test_body_cap_returns_only_512_kib_and_marks_truncation(http_site):
    response = client_for(http_site[0]).fetch("http://example.com/big")[0]
    assert response.body == b"x" * (512 * 1024)
    assert response.body_truncated is True


def test_compressed_content_is_not_decompressed(http_site):
    response = client_for(http_site[0]).fetch("http://example.com/gzip")[0]
    assert response.body == gzip.compress(b"private-to-transport-body", mtime=0)
    assert ("Content-Encoding", "gzip") in response.headers


@pytest.mark.parametrize("route", ["/slow-headers", "/slow-body"])
def test_total_deadline_interrupts_slow_streaming_not_just_idle_reads(http_site, route):
    started = time.monotonic()
    with pytest.raises(PublicHTTPError):
        client_for(http_site[0]).fetch("http://example.com" + route, timeout_s=0.15)
    assert time.monotonic() - started < 0.8


def test_oversized_headers_fail_with_a_safe_error(http_site):
    with pytest.raises(PublicHTTPError) as caught:
        client_for(http_site[0]).fetch("http://example.com/big-header")
    assert len(str(caught.value)) < 200


def test_default_dns_resolution_is_killed_at_the_total_deadline(monkeypatch):
    monkeypatch.setattr(network, "_DNS_PROGRAM", "import time; time.sleep(60)")
    started = time.monotonic()
    with pytest.raises(PublicHTTPError):
        PublicHTTPClient().fetch("http://example.com/", timeout_s=0.15)
    assert time.monotonic() - started < 1


def test_numeric_connector_does_not_perform_a_second_dns_lookup(monkeypatch):
    connected = []

    class FakeSocket:
        def settimeout(self, value):
            assert value > 0

        def connect(self, value):
            connected.append(value)

        def close(self):
            pass

    monkeypatch.setattr(socket, "socket", lambda *args: FakeSocket())
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args: pytest.fail("Numeric connect must not re-resolve DNS"),
    )
    network._connect_numeric(PUBLIC_IP, 443, 1)
    assert connected == [(PUBLIC_IP, 443)]


@pytest.fixture
def tls_site(http_site, tmp_path):
    server, requests = http_site
    key, cert = tmp_path / "key.pem", tmp_path / "cert.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            "/CN=example.com",
            "-addext",
            "subjectAltName=DNS:example.com",
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    names = []
    context.set_servername_callback(lambda sock, name, ssl_context: names.append(name))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    trust = ssl.create_default_context(cafile=str(cert))
    return server, requests, trust, names


def test_tls_verifies_certificate_hostname_and_preserves_domain_sni(tls_site):
    server, requests, trust, names = tls_site
    response = client_for(server, tls_context=trust).fetch("https://example.com/")[0]
    assert response.status == 200 and response.tls_protocol.startswith("TLS")
    assert response.certificate_expires_at is not None
    assert names == ["example.com"]
    assert dict(requests[0][1])["Host"] == "example.com"


def test_tls_untrusted_certificate_fails_closed(tls_site):
    with pytest.raises(PublicHTTPError, match="TLS"):
        client_for(tls_site[0]).fetch("https://example.com/")


def test_tls_hostname_mismatch_fails_closed(tls_site):
    server, _, trust, names = tls_site
    with pytest.raises(PublicHTTPError, match="TLS"):
        client_for(server, tls_context=trust).fetch("https://wrong.example.com/")
    assert names == ["wrong.example.com"]


def test_insecure_tls_context_cannot_be_used_as_a_bypass():
    context = ssl._create_unverified_context()
    with pytest.raises(ValueError):
        PublicHTTPClient(tls_context=context)

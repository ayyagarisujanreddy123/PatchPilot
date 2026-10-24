#!/usr/bin/env python3
"""Publish only the curated owned demo and serve its declared commit locally.

Run with the project's Python environment. Requires configured gh and Docker.
This script never changes Docker context, forces refs, merges PRs, or prints tokens.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
CURATED = (
    ".patchpilot.json",
    "README.md",
    "config/php.ini",
    "public/index.php",
    "public/contact.php",
    "public/upload.php",
)
HEX40 = re.compile(r"[a-f0-9]{40}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
IMAGE_ID = re.compile(r"sha256:[a-f0-9]{64}\Z")


class SetupError(RuntimeError):
    pass


def run(arguments, *, cwd=None, timeout=60, check=True):
    try:
        result = subprocess.run(
            arguments,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        raise SetupError(
            f"{arguments[0]} is unavailable or exceeded its deadline"
        ) from None
    if check and result.returncode:
        # CLI errors may include authentication material or arbitrary remote text.
        raise SetupError(
            f"{arguments[0]} operation failed; inspect its local configuration"
        )
    return result


def gh_json(arguments):
    result = run(["gh", *arguments])
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise SetupError("GitHub returned an invalid response") from None


def inspect(kind, reference):
    result = run(
        [
            "docker",
            *(["image", "inspect"] if kind == "image" else ["inspect"]),
            reference,
        ],
        check=False,
    )
    if result.returncode:
        return None
    try:
        data = json.loads(result.stdout)
        if (
            not isinstance(data, list)
            or len(data) != 1
            or not isinstance(data[0], dict)
        ):
            raise ValueError
        return data[0]
    except ValueError:
        raise SetupError("Docker resource identity could not be verified") from None


def owned(info, labels):
    found = info.get("Config", {}).get("Labels", {}) if info else {}
    return isinstance(found, dict) and all(
        found.get(key) == value for key, value in labels.items()
    )


def setup_repository(repository, workspace, owner):
    source = workspace / "source"
    marker = workspace / "owner.json"
    expected = {"schemaVersion": 1, "owner": owner, "repository": repository}
    existed = workspace.exists()
    if existed:
        try:
            if workspace.is_symlink() or json.loads(marker.read_text()) != expected:
                raise ValueError
        except (OSError, ValueError):
            raise SetupError(
                "Existing demo workspace lacks matching ownership evidence"
            ) from None
    else:
        workspace.mkdir(parents=True)
        marker.write_text(json.dumps(expected, indent=2) + "\n")
    if source.is_symlink():
        raise SetupError("Demo source must be an owned regular directory")
    if not source.exists():
        source.mkdir()
        template = ROOT / "examples" / "php-community-site"
        for name in CURATED:
            original, target = template / name, source / name
            if not original.is_file() or original.is_symlink():
                raise SetupError("A curated demo source file is missing or is a link")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
        run(["git", "init", "--initial-branch=main"], cwd=source)
        run(["git", "config", "user.name", "PatchPilot Demo"], cwd=source)
        run(
            ["git", "config", "user.email", "patchpilot-demo@users.noreply.github.com"],
            cwd=source,
        )
        run(["git", "add", "--", *CURATED], cwd=source)
        run(["git", "commit", "-m", "demo: add curated PHP community site"], cwd=source)
        run(
            ["git", "remote", "add", "origin", f"https://github.com/{repository}.git"],
            cwd=source,
        )
    if run(["git", "status", "--porcelain"], cwd=source).stdout.strip():
        raise SetupError(
            "Owned demo source has local changes; review them before publishing"
        )
    tracked = run(["git", "ls-files", "-z"], cwd=source).stdout.split("\0")
    if set(filter(None, tracked)) != set(CURATED):
        raise SetupError("The demo source must contain only the curated tracked files")
    template = ROOT / "examples" / "php-community-site"
    for name in CURATED:
        target = source / name
        if target.is_symlink() or target.read_bytes() != (template / name).read_bytes():
            raise SetupError("The demo source differs from its trusted curated example")
    remote = run(["git", "remote", "get-url", "origin"], cwd=source).stdout.strip()
    if remote != f"https://github.com/{repository}.git":
        raise SetupError(
            "The demo repository remote does not match the owned destination"
        )
    commit = run(["git", "rev-parse", "HEAD"], cwd=source).stdout.strip()
    if not HEX40.fullmatch(commit):
        raise SetupError("The demo source commit is invalid")
    result = run(
        [
            "gh",
            "repo",
            "view",
            repository,
            "--json",
            "nameWithOwner,isEmpty,defaultBranchRef",
        ],
        check=False,
    )
    if result.returncode:
        # Creation cannot replace an existing repository; permission/network errors fail safely.
        run(
            [
                "gh",
                "repo",
                "create",
                repository,
                "--public",
                "--description",
                "Owned PatchPilot connected PHP repair demonstration",
            ]
        )
        empty = True
    else:
        try:
            data = json.loads(result.stdout)
            if (
                data["nameWithOwner"].lower() != repository.lower()
                or type(data["isEmpty"]) is not bool
            ):
                raise ValueError
            empty = data["isEmpty"]
        except (ValueError, KeyError, TypeError):
            raise SetupError("The remote demo repository identity is invalid") from None
        if not empty:
            if (
                not existed
                or (data.get("defaultBranchRef") or {}).get("name") != "main"
            ):
                raise SetupError(
                    "An existing nonempty repository was not created by this owned workspace"
                )
            head = gh_json(["api", f"repos/{repository}/git/ref/heads/main"])
            if head.get("object", {}).get("sha") != commit:
                raise SetupError(
                    "The remote main branch differs; no ref was changed or reset"
                )
    if empty:
        run(
            [
                "git",
                "-c",
                "credential.helper=",
                "-c",
                "credential.helper=!gh auth git-credential",
                "push",
                "origin",
                "HEAD:refs/heads/main",
            ],
            cwd=source,
            timeout=120,
        )
    head = gh_json(["api", f"repos/{repository}/git/ref/heads/main"])
    if head.get("object", {}).get("sha") != commit:
        raise SetupError("The remote main branch does not match the deployed source")
    return source, commit


def start_server(repository, source, commit, workspace, owner, port):
    sys.path.insert(0, str(ROOT / "src"))
    from patchpilot.repairs.sandbox import BASE_DIGESTS

    platform = run(
        ["docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}"]
    ).stdout.strip()
    digest = BASE_DIGESTS.get(platform)
    if digest is None:
        raise SetupError("No approved demo PHP image exists for this Docker platform")
    base = f"docker.io/library/php@{digest}"
    info = inspect("image", base)
    if info is None:
        run(["docker", "pull", base], timeout=120)
        info = inspect("image", base)
    if (
        not info
        or f"{info.get('Os')}/{info.get('Architecture')}" != platform
        or not IMAGE_ID.fullmatch(info.get("Id", ""))
    ):
        raise SetupError("The pinned PHP base image could not be verified")
    labels = {
        "patchpilot.demo.component": "connected-php",
        "patchpilot.demo.owner": owner,
        "patchpilot.demo.repository": repository,
        "patchpilot.demo.port": str(port),
    }
    name, tag = (
        f"patchpilot-connected-demo-{owner[:12]}-{port}",
        f"patchpilot-connected-demo:{owner[:12]}-{port}",
    )
    previous = inspect("container", name)
    if previous:
        if not owned(previous, labels) or not HEX64.fullmatch(previous.get("Id", "")):
            raise SetupError("An existing container lacks this demo's ownership labels")
        run(["docker", "rm", "--force", previous["Id"]])
    previous_image = inspect("image", tag)
    if previous_image:
        if not owned(previous_image, labels) or not IMAGE_ID.fullmatch(
            previous_image.get("Id", "")
        ):
            raise SetupError("An existing image tag lacks this demo's ownership labels")
        run(["docker", "image", "rm", previous_image["Id"]])
    context = workspace / "deployment-context"
    if context.exists():
        if context.is_symlink() or context.resolve().parent != workspace.resolve():
            raise SetupError("Unsafe demo build directory")
        shutil.rmtree(context)
    (context / "app").mkdir(parents=True)
    for name_in_repo in ("public/index.php", "public/contact.php", "public/upload.php"):
        shutil.copyfile(
            source / name_in_repo, context / "app" / Path(name_in_repo).name
        )
    shutil.copyfile(source / "config" / "php.ini", context / "php.ini")
    shutil.copyfile(
        ROOT / "examples" / "php-community-site" / "deployment_router.php",
        context / "deployment_router.php",
    )
    manifest = json.loads((source / ".patchpilot.json").read_text())
    marker = {"repository": repository, "commit": commit, "siteId": manifest["siteId"]}
    (workspace / "deployment-marker.json").write_text(
        json.dumps(marker, indent=2) + "\n"
    )
    (context / "marker.json").write_text(json.dumps(marker) + "\n")
    (context / "Dockerfile").write_text(
        f"FROM {base}\nCOPY app/ /app/\nCOPY php.ini /deployment/php.ini\n"
        "COPY deployment_router.php /deployment/router.php\nCOPY marker.json /deployment/marker.json\n"
        "WORKDIR /app\nUSER 65532:65532\n"
    )
    # COPY retains source modes. Explicit public modes also work with umask 077.
    for copied in context.rglob("*"):
        copied.chmod(0o755 if copied.is_dir() else 0o644)
    label_args = [
        argument
        for key, value in labels.items()
        for argument in ("--label", f"{key}={value}")
    ]
    run(
        [
            "docker",
            "build",
            "--network",
            "none",
            "--pull=false",
            "--quiet",
            "--tag",
            tag,
            *label_args,
            str(context),
        ],
        timeout=120,
    )
    image = inspect("image", tag)
    if (
        not image
        or not owned(image, labels)
        or not IMAGE_ID.fullmatch(image.get("Id", ""))
    ):
        raise SetupError("The built demo image identity could not be verified")
    disabled = "exec,passthru,shell_exec,system,proc_open,popen,pcntl_exec,pcntl_fork,posix_kill,dl,putenv"
    run(
        [
            "docker",
            "run",
            "--detach",
            "--name",
            name,
            "--publish",
            f"127.0.0.1:{port}:8080",
            "--read-only",
            "--user",
            "65532:65532",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "32",
            "--memory",
            "256m",
            "--memory-swap",
            "256m",
            "--cpus",
            "0.5",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=64m,mode=1777",
            "--ipc",
            "none",
            "--init",
            "--log-driver",
            "none",
            "--stop-timeout",
            "1",
            "--env",
            "PHP_INI_SCAN_DIR=",
            *label_args,
            "--entrypoint",
            "php",
            image["Id"],
            "-c",
            "/deployment/php.ini",
            "-d",
            f"disable_functions={disabled}",
            "-d",
            "open_basedir=/app:/tmp:/deployment",
            "-d",
            "upload_tmp_dir=/tmp",
            "-d",
            "session.save_path=/tmp",
            "-d",
            "error_log=/tmp/php-errors.log",
            "-S",
            "0.0.0.0:8080",
            "-t",
            "/app",
            "/deployment/router.php",
        ]
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        try:
            with urlopen(
                f"{base_url}/.well-known/patchpilot.json", timeout=1
            ) as response:
                if (
                    response.status == 200
                    and json.loads(response.read(16385)) == marker
                ):
                    return {
                        "repository": repository,
                        "commit": commit,
                        "siteId": manifest["siteId"],
                        "baseUrl": base_url,
                        "container": name,
                    }
        except (OSError, URLError, ValueError):
            pass
        time.sleep(0.2)
    raise SetupError(
        "The owned demo container did not serve its deployment marker before the deadline"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository",
        required=True,
        help="YOURLOGIN/patchpilot-connected-demo[-suffix]",
    )
    parser.add_argument("--port", type=int, default=8085)
    args = parser.parse_args()
    if (
        not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/patchpilot-connected-demo(?:-[A-Za-z0-9_-]{1,60})?",
            args.repository,
        )
        or not 1024 <= args.port <= 65535
    ):
        parser.error(
            "Use an owned patchpilot-connected-demo repository and an unprivileged valid port"
        )
    if not all(shutil.which(tool) for tool in ("git", "gh", "docker")):
        raise SetupError(
            "Install git, GitHub CLI, and Docker before running the demo bootstrap"
        )
    login = gh_json(["api", "user"]).get("login", "")
    if login.lower() != args.repository.split("/")[0].lower():
        raise SetupError(
            "Choose a dedicated demo repository under the currently signed-in GitHub account"
        )
    workspace = ROOT / "var" / "connected-demo"
    if workspace.resolve() != ROOT / "var" / "connected-demo":
        raise SetupError("The fixed demo workspace must not resolve through symlinks")
    owner = hashlib.sha256(str(ROOT).encode()).hexdigest()[:24]
    source, commit = setup_repository(args.repository, workspace, owner)
    result = start_server(args.repository, source, commit, workspace, owner, args.port)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (SetupError, OSError, ValueError, KeyError, TypeError) as error:
        message = (
            str(error)
            if isinstance(error, SetupError)
            else "Demo setup could not complete; no raw diagnostics were retained"
        )
        print(message, file=sys.stderr)
        raise SystemExit(1) from None

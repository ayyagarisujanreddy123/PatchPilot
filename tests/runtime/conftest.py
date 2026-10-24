"""Unique Docker fixture registrations that cannot reset the live demo fleet."""

import json
import re
import shutil
import socket
import subprocess
import uuid
from pathlib import Path

import pytest

from patchpilot.runtime.bridge import Deadline, DockerRuntime


@pytest.fixture(scope="module")
def isolated_workspace(tmp_path_factory):
    source = Path(__file__).resolve().parents[2]
    root = tmp_path_factory.mktemp("runtime-workspace")
    (root / "config").mkdir()
    shutil.copytree(source / "fixtures", root / "fixtures")
    fleet = json.loads((source / "config" / "fleet.json").read_text())
    token = uuid.uuid4().hex[:10]
    published = subprocess.run(
        ["docker", "ps", "--format", "{{.Ports}}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout
    used_ports = {int(value) for value in re.findall(r":(\d+)->", published)}
    ports = []
    # Linux/RootlessKit ephemeral allocations start above this range; a free
    # Mac ephemeral port alone does not establish availability inside the VM.
    start = int(token, 16) % 10000
    for offset in range(10000):
        port = 19000 + (start + offset) % 10000
        if port in used_ports:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            try:
                listener.bind(("127.0.0.1", port))
            except OSError:
                continue
        ports.append(port)
        if len(ports) == len(fleet):
            break
    if len(ports) != len(fleet):
        raise RuntimeError(
            "No isolated fixture ports are available below the VM ephemeral range"
        )
    for entry, port in zip(fleet, ports, strict=True):
        entry["id"] = f"test-{token}-{entry['id']}"
        entry["endpoint"] = f"http://127.0.0.1:{port}"
        entry["port"] = port
    (root / "config" / "fleet.json").write_text(json.dumps(fleet))
    yield root
    runtime = DockerRuntime(root)
    deadline = Deadline(60)
    names = runtime._docker(
        [
            "ps",
            "-a",
            "--filter",
            f"label=patchpilot.project={runtime.project_id}",
            "--format",
            "{{.Names}}",
        ],
        deadline,
    ).stdout.splitlines()
    for name in names:
        info = runtime._container(name, deadline)
        if info is not None:
            site_id = info.get("Config", {}).get("Labels", {}).get("patchpilot.site_id")
            if site_id not in runtime.sites:
                raise RuntimeError(
                    "Unregistered resource found in isolated fixture teardown"
                )
            runtime._owned(info, site_id)
            runtime._docker(["rm", "-f", info["Id"]], deadline)
    image_ids = runtime._docker(
        [
            "image",
            "ls",
            "-q",
            "--filter",
            f"label=patchpilot.project={runtime.project_id}",
        ],
        deadline,
    ).stdout.split()
    for image_id in set(image_ids):
        runtime._docker(["image", "rm", image_id], deadline)


@pytest.fixture(scope="module")
def isolated_runtime(isolated_workspace):
    runtime = DockerRuntime(isolated_workspace)
    runtime.resolve_patched_digest(timeout_s=180)
    runtime.prepare(timeout_s=240)
    return runtime

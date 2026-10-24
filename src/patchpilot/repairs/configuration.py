"""A deliberately narrow PHP configuration edit policy."""

import difflib
import re

from patchpilot.repairs.errors import ConnectedRepairError
from patchpilot.repairs.models import ConfigChange

TARGETS = {
    "display_errors": "Off",
    "display_startup_errors": "Off",
    "log_errors": "On",
    "expose_php": "Off",
}
BOOLEAN = {
    "on": True,
    "true": True,
    "yes": True,
    "1": True,
    "off": False,
    "false": False,
    "no": False,
    "0": False,
}
BOOL_KEYS = {*TARGETS, "session.upload_progress.enabled"}
SIZE_KEYS = {"upload_max_filesize", "post_max_size", "memory_limit"}
ASSIGNMENT = re.compile(r"^(\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*=\s*)([^;\r\n]+?)(\s*)$")


def inspect_ini(content: str) -> dict[str, str]:
    if len(content.encode()) > 16384 or "\x00" in content:
        raise ConnectedRepairError(
            "The supported PHP configuration must be a small UTF-8 INI file."
        )
    settings = {}
    for line in content.splitlines():
        if not line.strip() or line.lstrip().startswith((";", "#")):
            continue
        match = ASSIGNMENT.fullmatch(line)
        if not match:
            raise ConnectedRepairError(
                "This PHP profile requires simple settings without sections or inline comments. Use the supplied example profile."
            )
        key, value = match[2].lower(), match[3].strip()
        if key in settings:
            raise ConnectedRepairError(
                "Duplicate PHP settings are unsupported; review the repository configuration."
            )
        valid = key in BOOL_KEYS and value.lower() in BOOLEAN
        valid |= key in SIZE_KEYS and bool(
            re.fullmatch(r"[1-9][0-9]{0,3}[KMG]", value, re.IGNORECASE)
        )
        valid |= (
            key == "max_execution_time" and value.isdigit() and 1 <= int(value) <= 60
        )
        valid |= key == "date.timezone" and value == "UTC"
        valid |= key == "error_reporting" and value == "E_ALL"
        if not valid:
            raise ConnectedRepairError(
                "This repository uses PHP settings outside the first supported profile. Execution hooks and arbitrary configuration are not accepted."
            )
        settings[key] = value
    if not TARGETS.keys() <= settings.keys():
        raise ConnectedRepairError(
            "Add all four supported PHP settings to the INI file: display_errors, display_startup_errors, log_errors, and expose_php."
        )
    return settings


def is_secure(settings: dict[str, str]) -> bool:
    return all(
        BOOLEAN[settings[key].lower()] is BOOLEAN[value.lower()]
        for key, value in TARGETS.items()
    )


def apply_changes(
    content: str, changes: list[ConfigChange], path: str
) -> tuple[str, str]:
    settings = inspect_ini(content)
    chosen = {change.key: change.value for change in changes}
    if len(chosen) != len(changes) or any(
        TARGETS[key] != value for key, value in chosen.items()
    ):
        raise ConnectedRepairError(
            "Anthropic selected a duplicate or unapproved PHP setting; no patch was accepted."
        )
    updated = {**settings, **chosen}
    if not is_secure(updated):
        raise ConnectedRepairError(
            "The proposed patch does not resolve every supported PHP configuration check."
        )
    lines = []
    for line in content.splitlines(keepends=True):
        ending = (
            "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        )
        match = ASSIGNMENT.fullmatch(line.rstrip("\r\n"))
        key = match[2].lower() if match else None
        if (
            key in chosen
            and BOOLEAN[settings[key].lower()] != BOOLEAN[chosen[key].lower()]
        ):
            lines.append(f"{match[1]}{chosen[key]}{match[4]}{ending}")
        else:
            lines.append(line)
    candidate = "".join(lines)
    inspect_ini(candidate)
    chunks = difflib.unified_diff(
            content.splitlines(keepends=True),
            candidate.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=0,
        )
    diff = "".join(chunk if chunk.endswith("\n") else chunk + "\n\\ No newline at end of file\n" for chunk in chunks)
    if not diff:
        raise ConnectedRepairError(
            "The repository already has the supported secure settings; no change is needed."
        )
    return candidate, diff

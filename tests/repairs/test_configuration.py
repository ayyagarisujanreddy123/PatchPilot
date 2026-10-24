import pytest

from patchpilot.repairs.configuration import (
    TARGETS,
    apply_changes,
    inspect_ini,
    is_secure,
)
from patchpilot.repairs.errors import ConnectedRepairError
from patchpilot.repairs.models import ConfigChange

ORIGINAL = "display_errors = On\ndisplay_startup_errors = On\nlog_errors = Off\nexpose_php = On\nupload_max_filesize = 8M\npost_max_size = 10M\n; unchanged comment\n"


def test_only_supported_lines_change_and_upload_requirements_are_preserved():
    candidate, diff = apply_changes(
        ORIGINAL,
        [ConfigChange(key=k, value=v) for k, v in TARGETS.items()],
        "config/php.ini",
    )
    assert is_secure(inspect_ini(candidate))
    assert (
        "upload_max_filesize = 8M\npost_max_size = 10M\n; unchanged comment\n"
        in candidate
    )
    assert "upload_max_filesize" not in diff
    assert "unchanged comment" not in diff
    assert "-display_errors = On" in diff
    assert "+display_errors = Off" in diff


@pytest.mark.parametrize(
    "extra",
    [
        "auto_prepend_file = /tmp/evil.php",
        "extension = anything",
        "[PATH=/]",
        "expose_php = On",
        "secret = PRIVATE",
        "display_errors = On ; secret",
    ],
)
def test_unsupported_execution_hooks_sections_duplicates_and_inline_values_are_rejected(
    extra,
):
    with pytest.raises(ConnectedRepairError):
        inspect_ini(ORIGINAL + extra)


def test_incomplete_and_weakened_proposals_are_rejected():
    with pytest.raises(ConnectedRepairError):
        apply_changes(
            ORIGINAL, [ConfigChange(key="expose_php", value="Off")], "config/php.ini"
        )
    with pytest.raises(ConnectedRepairError):
        apply_changes(
            ORIGINAL, [ConfigChange(key="expose_php", value="On")], "config/php.ini"
        )

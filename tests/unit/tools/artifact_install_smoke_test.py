from __future__ import annotations

from tools.artifact_install_smoke import _check_packaged_resources


def test_check_packaged_resources_finds_icon_and_web_ui() -> None:
    _check_packaged_resources()

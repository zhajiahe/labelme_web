from __future__ import annotations

from pathlib import Path

import pytest

from labelme import _locale
from tools.artifact_install_smoke import _check_packaged_resources


def test_check_packaged_resources_rejects_empty_translation_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_locale, "TRANSLATE_DIR", tmp_path)

    with pytest.raises(RuntimeError, match="translation catalogs"):
        _check_packaged_resources()

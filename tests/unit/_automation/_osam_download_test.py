from __future__ import annotations

from pathlib import Path
from typing import Final

import osam.apis
import osam.types
import osam.types._blob
import pytest

from labelme._automation._osam_session import OsamSession

_MODEL_NAME: Final = "efficientsam:10m"


@pytest.fixture()
def isolated_model_type(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> type[osam.types.Model]:
    # Redirect osam blob storage to a temp directory so the model reads as not
    # downloaded, without touching the real model cache in ~/.cache/osam.
    blob_base = tmp_path / "osam_blobs"

    def patched_path(self: osam.types._blob.Blob) -> str:
        if self.attachments:
            safe_hash = self.hash.replace("sha256:", "sha256-")
            return str(blob_base / safe_hash / self.filename)
        return str(blob_base / self.hash)

    monkeypatch.setattr(osam.types._blob.Blob, "path", property(patched_path))
    return osam.apis.get_model_type_by_name(_MODEL_NAME)


@pytest.mark.network
def test_osam_session_downloads_model_from_network(
    isolated_model_type: type[osam.types.Model],
) -> None:
    expected_paths = [Path(blob.path) for blob in isolated_model_type._blobs.values()]

    OsamSession(model_name=_MODEL_NAME)._get_or_load_model()

    assert all(path.is_file() for path in expected_paths)

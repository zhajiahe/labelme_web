from __future__ import annotations

from pathlib import Path

import pytest

from labelme._config import load_config
from labelme._label_file import ShapeDict
from labelme._session import AnnotationSession
from labelme._session import SessionLoadError


def _session(data_path: Path) -> AnnotationSession:
    config = load_config(config_file=None, config_overrides={"auto_save": False})
    session = AnnotationSession(
        config=config,
        config_file=None,
        config_overrides={"auto_save": False},
        output_dir=None,
    )
    session.load_path(str(data_path / "annotated"))
    return session


def test_read_annotation_bundle_does_not_change_current(data_path: Path) -> None:
    session = _session(data_path)
    current = session.image_path
    current_index = session.current_index
    other = 1 if current_index == 0 else 0
    annotation, image_path, _, width, height = session.read_annotation_bundle(other)
    assert session.image_path == current
    assert session.current_index == current_index
    assert image_path != current
    assert annotation.shapes
    assert width > 0
    assert height > 0


def test_read_image_bytes_does_not_change_current(data_path: Path) -> None:
    session = _session(data_path)
    current = session.image_path
    data, media_type = session.read_image_bytes(1)
    assert session.image_path == current
    assert data
    assert media_type in {"image/jpeg", "image/png"}


def test_save_index_does_not_open_the_saved_image(data_path: Path) -> None:
    session = _session(data_path)
    current = session.image_path
    other = 1 if session.current_index == 0 else 0
    annotation, _, _, _, _ = session.read_annotation_bundle(other)
    extra = ShapeDict(
        label="from-save-index",
        points=[[1.0, 2.0], [3.0, 4.0]],
        shape_type="rectangle",
        flags={},
        description="",
        group_id=None,
        mask=None,
        other_data={},
    )
    saved = session.save_index(
        other, shapes=[*annotation.shapes, extra], flags=annotation.flags
    )
    assert session.image_path == current
    assert Path(saved).exists()
    assert "from-save-index" in Path(saved).read_text(encoding="utf-8")


def test_path_at_rejects_out_of_range(data_path: Path) -> None:
    session = _session(data_path)
    with pytest.raises(SessionLoadError, match="out of range"):
        session.path_at(999)

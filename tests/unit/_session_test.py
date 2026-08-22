from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import numpy as np
import pytest
from loguru import logger

from labelme import __appname__
from labelme import _automation
from labelme import _session
from labelme._label_file import ShapeDict
from labelme._shape import Shape


@pytest.mark.parametrize(
    "create_mode, ai_output_format, expected",
    [
        ("ai_points_to_shape", "mask", "mask"),
        ("ai_box_to_shape", "polygon", "polygon"),
        ("polygon", "mask", "polygon"),
        ("rectangle", "mask", "rectangle"),
        ("edit", "polygon", None),
    ],
    ids=[
        "ai-points-passthrough",
        "ai-box-passthrough",
        "text-polygon",
        "text-rectangle",
        "unrelated-mode",
    ],
)
def test_resolve_text_annotation_shape_type(
    create_mode: str,
    ai_output_format: _automation.AiOutputFormat,
    expected: _automation.AiOutputFormat | None,
) -> None:
    assert (
        _session.resolve_text_annotation_shape_type(
            create_mode=create_mode, ai_output_format=ai_output_format
        )
        == expected
    )


@pytest.mark.parametrize(
    "label, existing_labels, policy, expected",
    [
        ("cat", [], None, True),
        ("cat", ["cat"], "exact", True),
        ("cat", ["dog"], "exact", False),
        ("cat", ["cat"], "unknown", False),
    ],
    ids=["policy-none", "exact-match", "exact-no-match", "unknown-policy"],
)
def test_is_valid_label(
    label: str, existing_labels: list[str], policy: str | None, expected: bool
) -> None:
    assert (
        _session.is_valid_label(
            label=label, existing_labels=existing_labels, policy=policy
        )
        is expected
    )


@pytest.mark.parametrize(
    "image_path, file_index, file_count, dirty, expected",
    [
        (None, None, 0, False, __appname__),
        ("img.png", None, 0, False, f"{__appname__} - img.png"),
        ("img.png", 1, 5, False, f"{__appname__} - img.png [2/5]"),
        ("img.png", 0, 5, False, f"{__appname__} - img.png [1/5]"),
        ("img.png", 0, 0, False, f"{__appname__} - img.png"),
        ("img.png", None, 5, False, f"{__appname__} - img.png"),
        ("img.png", 1, 5, True, f"{__appname__} - img.png [2/5]*"),
        (None, None, 0, True, f"{__appname__}*"),
        ("img.png", None, 0, True, f"{__appname__} - img.png*"),
    ],
)
def test_format_window_title(
    image_path: str | None,
    file_index: int | None,
    file_count: int,
    dirty: bool,
    expected: str,
) -> None:
    assert (
        _session.format_window_title(
            image_path=image_path,
            file_index=file_index,
            file_count=file_count,
            dirty=dirty,
        )
        == expected
    )


def _make_shape_dict(*, label: str, flags: dict[str, bool]) -> ShapeDict:
    return ShapeDict(
        label=label,
        points=[[0.0, 0.0], [10.0, 20.0]],
        shape_type="rectangle",
        flags=flags,
        description="",
        group_id=None,
        mask=None,
        other_data={},
    )


@pytest.mark.parametrize(
    "label, saved_flags, label_flags, expected",
    [
        (
            "cat",
            {},
            {"^cat$": ["occluded", "truncated"]},
            {"occluded": False, "truncated": False},
        ),
        (
            "cat",
            {"occluded": True},
            {"^cat$": ["occluded", "truncated"]},
            {"occluded": True, "truncated": False},
        ),
        (
            "cat",
            {"reviewed": True},
            {"^cat$": ["occluded"]},
            {"occluded": False, "reviewed": True},
        ),
        ("dog", {}, {"^cat$": ["occluded"]}, {}),
        ("bigcat", {}, {"cat$": ["occluded"]}, {}),
        (
            "cat",
            {},
            {"^cat$": ["occluded"], "^ca": ["blurry"], "^dog$": ["truncated"]},
            {"occluded": False, "blurry": False},
        ),
        ("cat", {"occluded": True}, None, {"occluded": True}),
        ("cat", {"occluded": True}, {}, {"occluded": True}),
        ("cat", {}, {"cat(": ["occluded"]}, {}),
        (
            "cat",
            {},
            {"cat(": ["broken"], "^cat$": ["occluded"]},
            {"occluded": False},
        ),
        ("2024", {}, {2024: ["occluded"]}, {}),
    ],
)
def test_shapes_from_dicts_merges_label_flags(
    label: str,
    saved_flags: dict[str, bool],
    label_flags: dict[str, list[str]] | None,
    expected: dict[str, bool],
) -> None:
    (shape,) = _session.shapes_from_dicts(
        shape_dicts=[_make_shape_dict(label=label, flags=saved_flags)],
        label_flags=label_flags,
    )
    assert shape.flags == expected


def test_shapes_from_dicts_warns_once_per_shape_with_a_non_str_label() -> None:
    shape_dicts = [
        _make_shape_dict(label=cast(str, None), flags={"occluded": True}),
        _make_shape_dict(label=cast(str, None), flags={}),
    ]
    warnings_logged: list[str] = []
    sink_id = logger.add(
        lambda m: warnings_logged.append(m.record["message"]), level="WARNING"
    )
    try:
        shapes = _session.shapes_from_dicts(
            shape_dicts=shape_dicts,
            label_flags={"^cat$": ["occluded"], "^dog$": ["truncated"]},
        )
    finally:
        logger.remove(sink_id)

    assert [shape.flags for shape in shapes] == [{"occluded": True}, {}]
    assert warnings_logged == ["shape.label is not str: None"] * 2


def test_shape_to_dict_maps_all_fields() -> None:
    shape = Shape(
        label="cat",
        group_id=3,
        shape_type="rectangle",
        flags={"occluded": True},
        description="a cat",
        points=np.array([[0.0, 1.0], [2.0, 3.0]], dtype=np.float64),
        other_data={"source": "human"},
    )

    result = _session.shape_to_dict(shape)

    assert result == {
        "label": "cat",
        "points": [[0.0, 1.0], [2.0, 3.0]],
        "shape_type": "rectangle",
        "flags": {"occluded": True},
        "description": "a cat",
        "group_id": 3,
        "mask": None,
        "other_data": {"source": "human"},
    }


@pytest.mark.parametrize(
    "image_or_label_path, output_dir, expected",
    [
        (str(Path("/data/img.png")), None, str(Path("/data/img.json"))),
        (str(Path("/data/img.png")), Path("/out"), str(Path("/out/img.json"))),
        (str(Path("/data/foo.json")), None, str(Path("/data/foo.json"))),
        (str(Path("/data/foo.json")), Path("/out"), str(Path("/data/foo.json"))),
        (str(Path("/data/a.b.png")), None, str(Path("/data/a.b.json"))),
        (str(Path("/data/FOO.JSON")), None, str(Path("/data/FOO.JSON"))),
    ],
)
def test_resolve_label_path(
    image_or_label_path: str,
    output_dir: Path | None,
    expected: str,
) -> None:
    assert (
        _session.resolve_label_path(
            image_or_label_path=image_or_label_path, output_dir=output_dir
        )
        == expected
    )


def test_resolve_stored_image_path_falls_back_to_absolute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*args: object, **kwargs: object) -> str:
        raise ValueError("path is on mount 'D:', start on mount 'C:'")

    monkeypatch.setattr("os.path.relpath", _raise)

    assert _session.resolve_stored_image_path(
        image_path="img.png", label_dir=Path("/labels")
    ) == os.path.abspath("img.png")


def test_scan_image_files_finds_supported_images(tmp_path: Path) -> None:
    (tmp_path / "a.jpg").write_bytes(b"not-an-image")
    (tmp_path / "b.PNG").write_bytes(b"not-an-image")
    (tmp_path / "notes.txt").write_text("skip", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "c.webp").write_bytes(b"not-an-image")

    found = _session.scan_image_files(root_dir=str(tmp_path))

    assert any(path.endswith("a.jpg") for path in found)
    assert any(path.endswith("b.PNG") or path.endswith("b.png") for path in found)
    assert any(path.endswith("c.webp") for path in found)
    assert all(not path.endswith(".txt") for path in found)

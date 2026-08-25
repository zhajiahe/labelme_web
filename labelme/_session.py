from __future__ import annotations

import os
import re
import threading
import typing
from pathlib import Path
from typing import Any
from typing import Literal
from typing import cast

import natsort
import numpy as np
from loguru import logger

from labelme import __appname__

from . import _automation
from . import _utils
from ._label_file import LABEL_FILE_SUFFIX
from ._label_file import Annotation
from ._label_file import LabelFileError
from ._label_file import ShapeDict
from ._label_file import is_label_file_path
from ._label_file import read_image_file
from ._label_file import read_label_file
from ._label_file import write_label_file
from ._label_flags import compile_label_flags
from ._shape import Shape
from ._shape import ShapeType

_TextToAnnotationCreateMode = Literal["polygon", "rectangle"]
_AI_CREATE_MODES: tuple[str, ...] = (
    "ai_points_to_shape",
    "ai_box_to_shape",
)

SUPPORTED_IMAGE_EXTENSIONS: tuple[str, ...] = (
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".pbm",
    ".pgm",
    ".png",
    ".ppm",
    ".tif",
    ".tiff",
    ".webp",
    ".xbm",
    ".xpm",
)


class SessionError(Exception):
    """User-facing failure while loading or saving a session."""


class SessionLoadError(SessionError):
    """The requested Image or Annotation File could not replace the session."""


class SessionSaveError(SessionError):
    """Writing an Annotation File failed; the previous file is intact."""


def shapes_from_dicts(
    *,
    shape_dicts: list[ShapeDict],
    label_flags: dict[str, list[str]] | None,
) -> list[Shape]:
    compiled_label_flags = compile_label_flags(label_flags=label_flags)

    shapes: list[Shape] = []
    for shape_dict in shape_dicts:
        shape = Shape(
            label=shape_dict["label"],
            shape_type=cast(ShapeType, shape_dict["shape_type"]),
            group_id=shape_dict["group_id"],
            description=shape_dict["description"],
            mask=shape_dict["mask"],
            points=np.array(shape_dict["points"], dtype=np.float64),
            closed=True,
        )

        default_flags: dict[str, bool] = {}
        if not isinstance(shape.label, str):
            logger.warning("shape.label is not str: {}", shape.label)
        else:
            for pattern, keys in compiled_label_flags.items():
                if pattern.match(shape.label):
                    for key in keys:
                        default_flags[key] = False
        shape.flags = default_flags
        shape.flags.update(shape_dict["flags"])
        shape.other_data = shape_dict["other_data"]

        shapes.append(shape)
    return shapes


def resolve_text_annotation_shape_type(
    *, create_mode: str, ai_output_format: _automation.AiOutputFormat
) -> _automation.AiOutputFormat | None:
    if create_mode in _AI_CREATE_MODES:
        return ai_output_format
    if create_mode in typing.get_args(_TextToAnnotationCreateMode):
        return cast(_TextToAnnotationCreateMode, create_mode)
    return None


def is_valid_label(
    *, label: str, existing_labels: list[str], policy: str | None
) -> bool:
    if policy is None:
        return True
    if policy == "exact":
        return label in existing_labels
    return False


def format_window_title(
    *,
    image_path: str | None,
    file_index: int | None,
    file_count: int,
    dirty: bool,
) -> str:
    title = __appname__
    if image_path:
        title = f"{title} - {image_path}"
        if file_count and file_index is not None:
            title = f"{title} [{file_index + 1}/{file_count}]"
    if dirty:
        title = f"{title}*"
    return title


def resolve_label_path(*, image_or_label_path: str, output_dir: Path | None) -> str:
    if is_label_file_path(filename=image_or_label_path):
        return image_or_label_path
    image_path = Path(image_or_label_path)
    parent = output_dir if output_dir is not None else image_path.parent
    return str(parent / f"{image_path.stem}{LABEL_FILE_SUFFIX}")


def resolve_stored_image_path(*, image_path: str, label_dir: Path) -> str:
    try:
        return os.path.relpath(image_path, label_dir)
    except ValueError:
        return os.path.abspath(image_path)


def shape_to_dict(shape: Shape) -> ShapeDict:
    assert shape.label is not None
    return ShapeDict(
        label=shape.label,
        points=shape.points.tolist(),
        shape_type=shape.shape_type,
        flags=shape.flags or {},
        description=shape.description or "",
        group_id=shape.group_id,
        mask=shape.mask,
        other_data=shape.other_data,
    )


def list_supported_image_extensions() -> tuple[str, ...]:
    return SUPPORTED_IMAGE_EXTENSIONS


def scan_image_files(root_dir: str) -> list[str]:
    extensions = list_supported_image_extensions()

    images: list[str] = []
    for root, _dirs, files in os.walk(root_dir):
        for file in files:
            if file.lower().endswith(extensions):
                relative_path = os.path.normpath(os.path.join(root, file))
                images.append(relative_path)

    logger.debug("found {:d} images in {!r}", len(images), root_dir)
    try:
        return natsort.os_sorted(images)
    except OSError:
        logger.warning(
            "natsort.os_sorted failed (known macOS strxfrm bug), "
            "falling back to locale-unaware natural sort"
        )
        return natsort.natsorted(images)


def _image_size(image_data: bytes) -> tuple[int, int]:
    image = _utils.img_data_to_pil(img_data=image_data)
    width, height = image.size
    return width, height


def _read_image_as_annotation(image_path: str) -> Annotation:
    image_data = read_image_file(filename=image_path)
    return Annotation(
        image_path=os.path.basename(image_path),
        image_data=image_data,
        shapes=[],
        flags={},
        other_data={},
    )


class AnnotationSession:
    """In-memory annotation session used by the local web service."""

    def __init__(
        self,
        *,
        config: dict,
        config_file: Path | None,
        config_overrides: dict,
        output_dir: Path | None,
    ) -> None:
        self.config = config
        self.config_file = config_file
        self.config_overrides = config_overrides
        self.output_dir = output_dir
        self.loaded_image_paths: list[str] = []
        self.file_list_enabled = True
        self.prev_opened_dir: str | None = None
        self.current_index: int | None = None
        self.image_path: str | None = None
        self.label_file_path: str | None = None
        self.annotation: Annotation | None = None
        self.image_width: int | None = None
        self.image_height: int | None = None
        self.dirty = False
        self.revision = 0
        self.file_search: str = config.get("file_search") or ""
        self._last_failed_auto_save_path: str | None = None
        self._lock = threading.RLock()

    @property
    def settings_editable(self) -> bool:
        return self.config_file is not None and not self.config_overrides

    def visible_image_paths(self) -> list[str]:
        image_paths = self.loaded_image_paths
        pattern = self.file_search
        if not pattern:
            return list(image_paths)
        try:
            return [path for path in image_paths if re.search(pattern, path)]
        except re.error:
            return list(image_paths)

    def title(self) -> str:
        visible = self.visible_image_paths()
        file_index = None
        if self.image_path is not None and self.image_path in visible:
            file_index = visible.index(self.image_path)
        return format_window_title(
            image_path=self.image_path,
            file_index=file_index,
            file_count=len(visible),
            dirty=self.dirty,
        )

    def has_annotation(self, image_path: str) -> bool:
        label_path = resolve_label_path(
            image_or_label_path=image_path, output_dir=self.output_dir
        )
        return Path(label_path).exists()

    def path_at(self, index: int) -> str:
        """Return the Image path at a File List index without opening it."""
        visible = self.visible_image_paths()
        if visible:
            if index < 0 or index >= len(visible):
                raise SessionLoadError(f"file index out of range: {index}")
            return visible[index]
        if self.image_path is not None and index == 0:
            return self.image_path
        if self.image_path is None:
            raise SessionLoadError("no image is open")
        raise SessionLoadError(f"file index out of range: {index}")

    def load_annotation_bundle(
        self, *, image_or_label_path: str
    ) -> tuple[Annotation, str, str | None, int, int]:
        """Read an Image and Annotation File from disk without changing current.

        Returns ``(annotation, image_path, label_file_path, width, height)``.
        """
        image_or_label_path = os.path.normpath(image_or_label_path)
        if not Path(image_or_label_path).exists():
            raise SessionLoadError(f"No such file: {image_or_label_path}")

        label_path = resolve_label_path(
            image_or_label_path=image_or_label_path,
            output_dir=self.output_dir,
        )
        try:
            if Path(label_path).exists():
                annotation = read_label_file(filename=label_path)
                image_path = os.path.normpath(
                    str(Path(label_path).parent / annotation.image_path)
                )
                label_file_path = label_path
            else:
                annotation = _read_image_as_annotation(image_path=image_or_label_path)
                image_path = image_or_label_path
                label_file_path = None
            width, height = _image_size(annotation.image_data)
        except (LabelFileError, OSError, ValueError) as exc:
            raise SessionLoadError(str(exc)) from exc

        flags = {key: False for key in self.config.get("flags") or []}
        if label_file_path is not None:
            flags.update(annotation.flags)
        annotation = Annotation(
            image_path=annotation.image_path,
            image_data=annotation.image_data,
            shapes=annotation.shapes,
            flags=flags,
            other_data=annotation.other_data,
        )
        return annotation, image_path, label_file_path, width, height

    def read_image_bytes(self, index: int) -> tuple[bytes, str]:
        """Return ``(bytes, media_type)`` for an Image index without opening it."""
        image_path = self.path_at(index)
        if image_path == self.image_path and self.annotation is not None:
            data = self.annotation.image_data
        else:
            annotation, _, _, _, _ = self.load_annotation_bundle(
                image_or_label_path=image_path
            )
            data = annotation.image_data
        media_type = "image/png"
        if image_path.lower().endswith((".jpg", ".jpeg")):
            media_type = "image/jpeg"
        return data, media_type

    def read_annotation_bundle(
        self, index: int
    ) -> tuple[Annotation, str, str | None, int, int]:
        """Read the persisted Annotation at ``index`` without opening it."""
        image_path = self.path_at(index)
        annotation, resolved_path, label_path, width, height = (
            self.load_annotation_bundle(image_or_label_path=image_path)
        )
        return annotation, resolved_path, label_path, width, height

    def load_path(self, file_or_dir: str) -> None:
        if not file_or_dir:
            raise SessionLoadError("file_or_dir cannot be empty")
        file_or_dir = os.path.normpath(file_or_dir)

        if is_label_file_path(filename=file_or_dir):
            self._open_image_or_label(image_or_label_path=file_or_dir)
            self.loaded_image_paths = []
            self.file_list_enabled = False
            return

        if Path(file_or_dir).is_dir():
            self._import_images_from_dir(root_dir=file_or_dir)
            visible = self.visible_image_paths()
            if visible:
                self._open_image_or_label(image_or_label_path=visible[0])
            return

        self._open_image_or_label(image_or_label_path=file_or_dir)
        parent = str(Path(file_or_dir).parent)
        self._import_images_from_dir(root_dir=parent)

    def open_index(self, index: int) -> None:
        visible = self.visible_image_paths()
        if index < 0 or index >= len(visible):
            raise SessionLoadError(f"file index out of range: {index}")
        keep_prev_shapes = (
            list(self.annotation.shapes)
            if self.config.get("keep_prev") and self.annotation is not None
            else []
        )
        self._open_image_or_label(image_or_label_path=visible[index])
        if (
            keep_prev_shapes
            and self.annotation is not None
            and not self.annotation.shapes
        ):
            self.annotation = Annotation(
                image_path=self.annotation.image_path,
                image_data=self.annotation.image_data,
                shapes=keep_prev_shapes,
                flags=self.annotation.flags,
                other_data=self.annotation.other_data,
            )
            self.dirty = True

    def navigate(self, delta: int) -> None:
        visible = self.visible_image_paths()
        if not visible or self.image_path is None or self.image_path not in visible:
            raise SessionLoadError("no image is open")
        index = visible.index(self.image_path) + delta
        if index < 0 or index >= len(visible):
            raise SessionLoadError("no more images in that direction")
        self.open_index(index)

    def save(
        self,
        *,
        shapes: list[ShapeDict],
        flags: dict[str, bool],
        label_path: str | None = None,
    ) -> str:
        if self.annotation is None or self.image_path is None:
            raise SessionSaveError("no image is open")
        if self.image_width is None or self.image_height is None:
            raise SessionSaveError("image dimensions are unknown")
        return self._write_annotation(
            image_path=self.image_path,
            image_data=self.annotation.image_data,
            image_width=self.image_width,
            image_height=self.image_height,
            other_data=self.annotation.other_data,
            shapes=shapes,
            flags=flags,
            label_path=label_path,
            update_current=True,
        )

    def save_index(
        self,
        index: int,
        *,
        shapes: list[ShapeDict],
        flags: dict[str, bool],
        label_path: str | None = None,
    ) -> str:
        """Persist an Annotation for ``index`` without changing the current Image."""
        image_path = self.path_at(index)
        if (
            image_path == self.image_path
            and self.annotation is not None
            and self.image_width is not None
            and self.image_height is not None
        ):
            return self.save(shapes=shapes, flags=flags, label_path=label_path)
        annotation, resolved_path, _, width, height = self.load_annotation_bundle(
            image_or_label_path=image_path
        )
        return self._write_annotation(
            image_path=resolved_path,
            image_data=annotation.image_data,
            image_width=width,
            image_height=height,
            other_data=annotation.other_data,
            shapes=shapes,
            flags=flags,
            label_path=label_path,
            update_current=False,
        )

    def _write_annotation(
        self,
        *,
        image_path: str,
        image_data: bytes,
        image_width: int,
        image_height: int,
        other_data: dict[str, Any],
        shapes: list[ShapeDict],
        flags: dict[str, bool],
        label_path: str | None,
        update_current: bool,
    ) -> str:
        existing_labels = list(self.config.get("labels") or [])
        policy = self.config.get("validate_label")
        for shape in shapes:
            if not is_valid_label(
                label=shape["label"],
                existing_labels=existing_labels,
                policy=policy,
            ):
                raise SessionSaveError(
                    f"invalid label {shape['label']!r} (validate_label={policy!r})"
                )

        if (
            label_path is None
            and update_current
            and image_path == self.image_path
            and self.label_file_path
        ):
            target = self.label_file_path
        else:
            target = label_path or resolve_label_path(
                image_or_label_path=image_path, output_dir=self.output_dir
            )
        label_dir = Path(target).parent
        try:
            label_dir.mkdir(parents=True, exist_ok=True)
            annotation = Annotation(
                image_path=resolve_stored_image_path(
                    image_path=image_path, label_dir=label_dir
                ),
                image_data=image_data,
                shapes=shapes,
                flags=flags,
                other_data=other_data,
            )
            write_label_file(
                filename=target,
                annotation=annotation,
                image_height=image_height,
                image_width=image_width,
                save_image_data=bool(self.config.get("with_image_data")),
            )
        except (LabelFileError, OSError, ValueError) as exc:
            if update_current:
                self._last_failed_auto_save_path = target
            raise SessionSaveError(str(exc)) from exc

        self.revision += 1
        if update_current:
            self.annotation = annotation
            self.label_file_path = target
            self.dirty = False
            self._last_failed_auto_save_path = None
        return target

    def close(self) -> None:
        self.current_index = None
        self.image_path = None
        self.label_file_path = None
        self.annotation = None
        self.image_width = None
        self.image_height = None
        self.dirty = False

    def _import_images_from_dir(self, root_dir: str) -> None:
        self.prev_opened_dir = root_dir
        self.loaded_image_paths = scan_image_files(root_dir=root_dir)
        self.file_list_enabled = True

    def _open_image_or_label(self, *, image_or_label_path: str) -> None:
        annotation, image_path, label_file_path, width, height = (
            self.load_annotation_bundle(image_or_label_path=image_or_label_path)
        )
        self.annotation = annotation
        self.image_path = image_path
        self.label_file_path = label_file_path
        self.image_width = width
        self.image_height = height
        self.dirty = False
        visible = self.visible_image_paths()
        self.current_index = (
            visible.index(image_path) if image_path in visible else None
        )
        logger.info("Loaded file: {!r}", image_or_label_path)

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import Literal

import numpy as np
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pydantic import Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response as StarletteResponse
from starlette.types import ASGIApp

from labelme import __appname__
from labelme import __version__

from . import _ai_models
from . import _automation
from . import _config
from . import _utils
from ._config._schema import SETTINGS
from ._label_file import Annotation
from ._label_file import ShapeDict
from ._label_file import _dump_shape_to_json_obj
from ._label_file import _load_shape_json_obj
from ._session import AnnotationSession
from ._session import SessionError
from ._session import SessionLoadError
from ._session import SessionSaveError
from ._session import shape_to_dict
from ._session import shapes_from_dicts
from ._shape_color import resolve_shape_color

_WEB_DIR = Path(__file__).resolve().parent / "_web"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_PUBLIC_PATHS = frozenset({"/api/health"})


class OpenRequest(BaseModel):
    path: str


class NavigateRequest(BaseModel):
    delta: int


class CurrentRequest(BaseModel):
    index: int


class SaveRequest(BaseModel):
    shapes: list[dict[str, Any]]
    flags: dict[str, bool] = Field(default_factory=dict)
    label_path: str | None = None
    client_version: int | None = None


class ConfigPatch(BaseModel):
    key_path: list[str]
    value: object


class SearchRequest(BaseModel):
    query: str


class AiAssistRequest(BaseModel):
    prompt_kind: Literal["points", "box"]
    points: list[list[float]]
    point_labels: list[int]
    output_format: Literal["polygon", "mask", "rectangle"] = "polygon"
    existing_shapes: list[dict[str, Any]] = Field(default_factory=list)
    model_name: str | None = None


class AiTextRequest(BaseModel):
    text: str
    output_format: Literal["polygon", "rectangle"] = "polygon"
    model_name: str | None = None


def bind_requires_access_token(host: str) -> bool:
    """Non-loopback binds expose the annotator on a network and must authenticate."""
    return host.strip().lower() not in _LOOPBACK_HOSTS


def _provided_access_token(request: Request) -> str | None:
    header = request.headers.get("Authorization")
    if header and header.lower().startswith("bearer "):
        return header[7:].strip() or None
    query_token = request.query_params.get("token")
    if query_token:
        return query_token
    cookie_token = request.cookies.get("labelme_token")
    if cookie_token:
        return cookie_token
    return None


class _AccessTokenMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> StarletteResponse:
        if request.url.path in _PUBLIC_PATHS or not request.url.path.startswith(
            "/api/"
        ):
            return await call_next(request)
        if _provided_access_token(request) != self._token:
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        response = await call_next(request)
        response.set_cookie(
            "labelme_token",
            self._token,
            httponly=True,
            samesite="lax",
        )
        return response


def _rgb_image(image_data: bytes) -> np.ndarray:
    image = _utils.img_data_to_arr(img_data=image_data)
    if image.ndim == 2:
        return np.stack([image, image, image], axis=2)
    if image.ndim == 3 and image.shape[2] >= 3:
        return image[:, :, :3]
    return image


def _http_error(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail=message)


def _session_from(request: Request) -> AnnotationSession:
    session = getattr(request.app.state, "session", None)
    if session is None:
        raise _http_error(500, "annotation session is not initialized")
    return session


def _file_entries(
    session: AnnotationSession, *, offset: int, limit: int
) -> tuple[int, list[dict[str, Any]]]:
    visible = session.visible_image_paths()
    if not visible and session.image_path is not None:
        visible = [session.image_path]
    total = len(visible)
    page = visible[offset : offset + limit]
    entries: list[dict[str, Any]] = []
    for index, path in enumerate(page, start=offset):
        entries.append(
            {
                "index": index,
                "path": path,
                "name": Path(path).name,
                "has_annotation": session.has_annotation(path),
                "current": path == session.image_path,
            }
        )
    return total, entries


def _settings_payload(session: AnnotationSession) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for setting in SETTINGS:
        node: object = session.config
        for key in setting.key_path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        payload.append(
            {
                "key_path": list(setting.key_path),
                "group": setting.group,
                "label": setting.label,
                "kind": setting.kind,
                "choices": list(setting.choices)
                if setting.choices is not None
                else None,
                "choice_labels": (
                    list(setting.choice_labels)
                    if setting.choice_labels is not None
                    else None
                ),
                "note": setting.note,
                "beta": setting.beta,
                "value": node,
            }
        )
    return payload


def _annotation_payload(
    session: AnnotationSession,
    *,
    annotation: Annotation | None = None,
    image_path: str | None = None,
    label_path: str | None = None,
    image_width: int | None = None,
    image_height: int | None = None,
    dirty: bool | None = None,
) -> dict[str, Any] | None:
    annotation = session.annotation if annotation is None else annotation
    image_path = session.image_path if image_path is None else image_path
    label_path = session.label_file_path if label_path is None else label_path
    image_width = session.image_width if image_width is None else image_width
    image_height = session.image_height if image_height is None else image_height
    dirty = session.dirty if dirty is None else dirty
    if annotation is None or image_path is None:
        return None
    shapes = [
        _dump_shape_to_json_obj(shape=shape_dict) for shape_dict in annotation.shapes
    ]
    labels = list(session.config.get("labels") or [])
    used_labels = [shape["label"] for shape in annotation.shapes]
    unique_labels = list(dict.fromkeys([*labels, *used_labels]))
    if session.config.get("sort_labels"):
        unique_labels = sorted(unique_labels)
    colors = {
        label: resolve_shape_color(
            config=session.config["shape_color"],
            label=label,
            label_index=index,
        )
        for index, label in enumerate(unique_labels)
    }
    return {
        "image_path": image_path,
        "label_path": label_path,
        "flags": annotation.flags,
        "shapes": shapes,
        "other_data": annotation.other_data,
        "image_width": image_width,
        "image_height": image_height,
        "dirty": dirty,
        "colors": colors,
        "labels": unique_labels,
        "index": session.current_index if image_path == session.image_path else None,
    }


def _config_payload(session: AnnotationSession) -> dict[str, Any]:
    return {
        "auto_save": session.config.get("auto_save"),
        "display_label_popup": session.config.get("display_label_popup"),
        "with_image_data": session.config.get("with_image_data"),
        "keep_prev": session.config.get("keep_prev"),
        "keep_prev_scale": session.config.get("keep_prev_scale"),
        "keep_prev_brightness_contrast": session.config.get(
            "keep_prev_brightness_contrast"
        ),
        "color_theme": session.config.get("color_theme", "system"),
        "language": session.config.get("language"),
        "labels": session.config.get("labels") or [],
        "flags": session.config.get("flags") or [],
        "label_flags": session.config.get("label_flags") or {},
        "validate_label": session.config.get("validate_label"),
        "sort_labels": session.config.get("sort_labels"),
        "show_label_text_field": session.config.get("show_label_text_field"),
        "label_completion": session.config.get("label_completion"),
        "epsilon": session.config.get("epsilon"),
        "canvas": session.config.get("canvas") or {},
        "shape": session.config.get("shape") or {},
        "shortcuts": session.config.get("shortcuts") or {},
        "ai": session.config.get("ai") or {},
    }


def _session_payload(session: AnnotationSession) -> dict[str, Any]:
    visible = session.visible_image_paths()
    file_count = len(visible) if visible else (1 if session.image_path else 0)
    return {
        "app_name": __appname__,
        "version": __version__,
        "title": session.title(),
        "output_dir": str(session.output_dir) if session.output_dir else None,
        "file_list_enabled": session.file_list_enabled,
        "file_search": session.file_search,
        "file_count": file_count,
        "current_index": session.current_index,
        "dirty": session.dirty,
        "revision": session.revision,
        "settings_editable": session.settings_editable,
        "config": _config_payload(session),
        "settings": _settings_payload(session),
        "ai_models": [
            {
                "model_name": option.model_name,
                "display_name": option.display_name,
                "supports_point_prompts": option.supports_point_prompts,
            }
            for option in _ai_models.AI_ASSIST_MODEL_OPTIONS
        ],
        "annotation": _annotation_payload(session),
    }


def _current_payload(session: AnnotationSession) -> dict[str, Any]:
    return {
        "title": session.title(),
        "current_index": session.current_index,
        "file_count": _session_payload(session)["file_count"],
        "dirty": session.dirty,
        "revision": session.revision,
        "file_search": session.file_search,
        "file_list_enabled": session.file_list_enabled,
        "annotation": _annotation_payload(session),
    }


def _parse_shapes(raw_shapes: list[dict[str, Any]]) -> list[ShapeDict]:
    shapes = []
    for index, raw in enumerate(raw_shapes):
        try:
            shapes.append(_load_shape_json_obj(shape_json_obj=raw))
        except (TypeError, ValueError, RuntimeError) as exc:
            raise _http_error(400, f"shapes[{index}]: {exc}") from exc
    return shapes


def _model_name_from_display(*, display_name: str | None, fallback: str) -> str:
    if not display_name:
        return fallback
    for option in _ai_models.AI_ASSIST_MODEL_OPTIONS:
        if option.display_name == display_name or option.model_name == display_name:
            return option.model_name
    return fallback


def create_app(
    session: AnnotationSession, *, access_token: str | None = None
) -> FastAPI:
    app = FastAPI(title=__appname__, version=__version__)
    app.state.session = session
    app.state.access_token = access_token
    app.state.ai_assist: _automation.AiAssistSession | None = None
    app.state.text_session: _automation.OsamSession | None = None
    if access_token:
        app.add_middleware(_AccessTokenMiddleware, token=access_token)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "app": __appname__, "version": __version__}

    @app.get("/api/session")
    def get_session(request: Request) -> dict[str, Any]:
        return _session_payload(_session_from(request))

    @app.post("/api/session/open")
    def open_path(body: OpenRequest, request: Request) -> dict[str, Any]:
        session = _session_from(request)
        try:
            session.load_path(body.path)
        except SessionLoadError as exc:
            raise _http_error(400, str(exc)) from exc
        return _session_payload(session)

    @app.post("/api/session/navigate")
    def navigate(body: NavigateRequest, request: Request) -> dict[str, Any]:
        session = _session_from(request)
        try:
            session.navigate(body.delta)
        except SessionLoadError as exc:
            raise _http_error(400, str(exc)) from exc
        return _current_payload(session)

    @app.post("/api/session/current")
    def set_current(body: CurrentRequest, request: Request) -> dict[str, Any]:
        session = _session_from(request)
        try:
            session.open_index(body.index)
        except SessionLoadError as exc:
            raise _http_error(400, str(exc)) from exc
        return _current_payload(session)

    @app.post("/api/session/close")
    def close_file(request: Request) -> dict[str, Any]:
        session = _session_from(request)
        session.close()
        return _session_payload(session)

    @app.post("/api/session/search")
    def search_files(body: SearchRequest, request: Request) -> dict[str, Any]:
        session = _session_from(request)
        session.file_search = body.query
        return {
            "file_search": session.file_search,
            "file_count": _session_payload(session)["file_count"],
            "current_index": session.current_index,
        }

    @app.get("/api/files")
    def list_files(
        request: Request,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=80, ge=1, le=2000),
    ) -> dict[str, Any]:
        session = _session_from(request)
        total, files = _file_entries(session, offset=offset, limit=limit)
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "current_index": session.current_index,
            "files": files,
        }

    @app.get("/api/files/{index}/image")
    def get_image(index: int, request: Request) -> Response:
        session = _session_from(request)
        try:
            data, media_type = session.read_image_bytes(index)
        except SessionLoadError as exc:
            message = str(exc)
            status = 404 if "out of range" in message or "no image" in message else 400
            raise _http_error(status, message) from exc
        return Response(content=data, media_type=media_type)

    @app.get("/api/files/{index}/annotation")
    def get_annotation(index: int, request: Request) -> dict[str, Any]:
        session = _session_from(request)
        try:
            annotation, image_path, label_path, width, height = (
                session.read_annotation_bundle(index)
            )
        except SessionLoadError as exc:
            message = str(exc)
            status = 404 if "out of range" in message or "no image" in message else 400
            raise _http_error(status, message) from exc
        payload = _annotation_payload(
            session,
            annotation=annotation,
            image_path=image_path,
            label_path=label_path,
            image_width=width,
            image_height=height,
            dirty=False,
        )
        if payload is None:
            raise _http_error(404, "no image is open")
        payload["index"] = index
        return payload

    @app.put("/api/files/{index}/annotation")
    def save_annotation(
        index: int, body: SaveRequest, request: Request
    ) -> dict[str, Any]:
        session = _session_from(request)
        try:
            saved_path = session.save_index(
                index,
                shapes=_parse_shapes(body.shapes),
                flags=body.flags,
                label_path=body.label_path,
            )
        except SessionLoadError as exc:
            raise _http_error(404, str(exc)) from exc
        except SessionSaveError as exc:
            raise _http_error(400, str(exc)) from exc
        return {
            "ok": True,
            "revision": session.revision,
            "saved_path": saved_path,
            "saved_at": datetime.now(tz=UTC).isoformat(),
            "client_version": body.client_version,
            "index": index,
            "current_index": session.current_index,
            "has_annotation": True,
        }

    @app.patch("/api/config")
    def patch_config(body: ConfigPatch, request: Request) -> dict[str, Any]:
        session = _session_from(request)
        if not session.settings_editable:
            raise _http_error(
                400,
                "Settings cannot be edited because a --config expression or "
                "CLI override is active.",
            )
        assert session.config_file is not None
        try:
            _config.set_overrides(
                session.config_file, [(tuple(body.key_path), body.value)]
            )
            session.config = _config.load_config(
                config_file=session.config_file,
                config_overrides=session.config_overrides,
            )
        except (OSError, ValueError, TypeError) as exc:
            raise _http_error(400, str(exc)) from exc
        return {
            "config": _config_payload(session),
            "settings": _settings_payload(session),
            "settings_editable": session.settings_editable,
        }

    @app.post("/api/ai/assist")
    def ai_assist(body: AiAssistRequest, request: Request) -> dict[str, Any]:
        session = _session_from(request)
        if session.annotation is None:
            raise _http_error(400, "no image is open")
        display_name = body.model_name or session.config.get("ai", {}).get("default")
        model_name = _model_name_from_display(
            display_name=display_name, fallback="sam2:latest"
        )
        if body.prompt_kind == "points" and not _ai_models.supports_point_prompts(
            model_name=model_name
        ):
            raise _http_error(
                400,
                f"{model_name} does not support point prompts",
            )
        image = _rgb_image(session.annotation.image_data)
        existing = shapes_from_dicts(
            shape_dicts=_parse_shapes(body.existing_shapes),
            label_flags=session.config.get("label_flags"),
        )
        assist = getattr(request.app.state, "ai_assist", None)
        if assist is None or assist.model_name != model_name:
            assist = _automation.AiAssistSession(
                model_name=model_name, output_format=body.output_format
            )
            request.app.state.ai_assist = assist
        assist.output_format = body.output_format
        try:
            proposal = assist.propose_shapes(
                image=image,
                image_id=session.image_path or "current",
                prompt_kind=body.prompt_kind,
                points=np.asarray(body.points, dtype=np.float64),
                point_labels=np.asarray(body.point_labels, dtype=np.intp),
                existing_shapes=(
                    existing
                    if session.config.get("ai", {}).get(
                        "suppress_existing_shape_matches"
                    )
                    else []
                ),
                image_size=(
                    None
                    if session.config.get("canvas", {}).get(
                        "allow_out_of_bounds_points"
                    )
                    else (session.image_width or 0, session.image_height or 0)
                ),
            )
        except ValueError as exc:
            raise _http_error(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — surface model/runtime failures
            raise _http_error(500, str(exc)) from exc
        return {
            "new_shapes": [
                _dump_shape_to_json_obj(shape=shape_to_dict(shape))
                for shape in proposal.new_shapes
            ],
            "matching_existing_shapes": [
                _dump_shape_to_json_obj(shape=shape_to_dict(shape))
                for shape in proposal.matching_existing_shapes
            ],
        }

    @app.post("/api/ai/text")
    def ai_text(body: AiTextRequest, request: Request) -> dict[str, Any]:
        session = _session_from(request)
        if session.annotation is None:
            raise _http_error(400, "no image is open")
        display_name = body.model_name or session.config.get("ai", {}).get("default")
        model_name = _model_name_from_display(
            display_name=display_name, fallback="sam2:latest"
        )
        image = _rgb_image(session.annotation.image_data)
        text_session = getattr(request.app.state, "text_session", None)
        if text_session is None or text_session.model_name != model_name:
            text_session = _automation.OsamSession(model_name=model_name)
            request.app.state.text_session = text_session
        texts = [part.strip() for part in body.text.split(",") if part.strip()]
        if not texts:
            raise _http_error(400, "text prompt is empty")
        try:
            boxes, scores, labels, masks = _automation.get_bboxes_from_texts(
                session=text_session,
                image=image,
                image_id=session.image_path or "current",
                texts=texts,
            )
            boxes, scores, labels, indices = _automation.nms_bboxes(
                boxes=boxes,
                scores=scores,
                labels=labels,
                iou_threshold=0.5,
                score_threshold=0.1,
                max_num_detections=100,
            )
            if masks is None:
                mask_list: list[np.ndarray | None] = [None] * len(boxes)
            else:
                mask_list = [masks[int(index)] for index in indices]
            detections = []
            for box, score, label, mask in zip(boxes, scores, labels, mask_list):
                detections.append(
                    _automation.Detection(
                        bbox=(
                            float(box[0]),
                            float(box[1]),
                            float(box[2]),
                            float(box[3]),
                        ),
                        mask=mask,
                        label=texts[int(label)],
                        score=float(score),
                    )
                )
            allow_oob = bool(
                session.config.get("canvas", {}).get("allow_out_of_bounds_points")
            )
            shapes = _automation.shapes_from_detections(
                detections=detections,
                shape_type=body.output_format,
                image_size=(
                    None
                    if allow_oob
                    else (session.image_width or 0, session.image_height or 0)
                ),
            )
        except ValueError as exc:
            raise _http_error(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — surface model/runtime failures
            raise _http_error(500, str(exc)) from exc
        return {
            "new_shapes": [
                _dump_shape_to_json_obj(shape=shape_to_dict(shape)) for shape in shapes
            ]
        }

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_WEB_DIR / "index.html")

    @app.get("/favicon.ico")
    @app.get("/static/favicon.png")
    def favicon() -> FileResponse:
        return FileResponse(Path(__file__).resolve().parent / "icons" / "icon-256.png")

    if _WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=_WEB_DIR), name="static")

    return app


def build_session(
    *,
    config_file: Path | None,
    config_overrides: dict,
    file_or_dir: str | None,
    output_dir: Path | None,
) -> AnnotationSession:
    config = _config.load_config(
        config_file=config_file, config_overrides=config_overrides
    )
    session = AnnotationSession(
        config=config,
        config_file=config_file,
        config_overrides=config_overrides,
        output_dir=output_dir,
    )
    if file_or_dir:
        try:
            session.load_path(file_or_dir)
        except SessionError as exc:
            raise SystemExit(f"Failed to open {file_or_dir!r}: {exc}") from exc
    return session

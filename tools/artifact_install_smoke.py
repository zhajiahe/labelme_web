from __future__ import annotations

from pathlib import Path

import onnxruntime  # noqa: F401  # load DLLs before other native extensions on Windows

import labelme
from labelme import _locale
from labelme._config import load_config
from labelme._session import AnnotationSession
from labelme._webapp import create_app


def _check_source_isolation(*, source_root: Path, package_path: Path) -> None:
    if package_path.is_relative_to(source_root):
        raise RuntimeError(f"labelme imported from source checkout: {package_path}")


def _check_packaged_resources() -> None:
    icon_path = Path(labelme.__file__).parent / "icons" / "icon-256.png"
    if not icon_path.is_file() or icon_path.stat().st_size == 0:
        raise RuntimeError(f"packaged icon is missing: {icon_path}")

    web_index = Path(labelme.__file__).parent / "_web" / "index.html"
    if not web_index.is_file():
        raise RuntimeError(f"packaged web UI is missing: {web_index}")

    locales = _locale.available_translation_locales()
    if not locales:
        raise RuntimeError("packaged artifact ships no translation catalogs")


def _check_application_starts() -> None:
    session = AnnotationSession(
        config=load_config(config_file=None, config_overrides={}),
        config_file=None,
        config_overrides={},
        output_dir=None,
    )
    app = create_app(session=session)
    routes = {getattr(route, "path", "") for route in app.routes}
    if "/api/health" not in routes:
        raise RuntimeError(f"web app is missing /api/health: {sorted(routes)}")
    if "/" not in routes:
        raise RuntimeError("web app is missing the SPA index route")


def main() -> None:
    source_root = Path(__file__).resolve().parent.parent
    package_path = Path(labelme.__file__).resolve()

    _check_source_isolation(source_root=source_root, package_path=package_path)
    _check_packaged_resources()
    _check_application_starts()


if __name__ == "__main__":
    main()

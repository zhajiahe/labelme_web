from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from labelme._config import load_config
from labelme._session import AnnotationSession
from labelme._webapp import create_app


def make_session(
    data_path: Path, *, extra_overrides: dict[str, Any] | None = None
) -> AnnotationSession:
    overrides = {"auto_save": False, **(extra_overrides or {})}
    config = load_config(config_file=None, config_overrides=overrides)
    session = AnnotationSession(
        config=config,
        config_file=None,
        config_overrides=overrides,
        output_dir=None,
    )
    session.load_path(str(data_path / "annotated"))
    return session


@pytest.fixture()
def client(data_path: Path) -> TestClient:
    return TestClient(create_app(session=make_session(data_path)))

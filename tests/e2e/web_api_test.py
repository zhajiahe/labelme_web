from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from labelme._config import load_config
from labelme._session import AnnotationSession
from labelme._webapp import create_app


@pytest.fixture()
def client(data_path: Path) -> TestClient:
    config = load_config(config_file=None, config_overrides={"auto_save": False})
    session = AnnotationSession(
        config=config,
        config_file=None,
        config_overrides={"auto_save": False},
        output_dir=None,
    )
    session.load_path(str(data_path / "annotated"))
    return TestClient(create_app(session=session))


def test_health_and_spa(client: TestClient) -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    page = client.get("/")
    assert page.status_code == 200
    assert "Labelme" in page.text
    assert "canvas" in page.text


def test_session_lists_annotated_images(client: TestClient) -> None:
    payload = client.get("/api/session").json()
    assert payload["files"]
    assert any(file["has_annotation"] for file in payload["files"])
    assert payload["annotation"] is not None
    assert payload["annotation"]["shapes"]


def test_annotation_round_trip(client: TestClient, data_path: Path) -> None:
    session = client.get("/api/session").json()
    index = next(file["index"] for file in session["files"] if file["current"])
    annotation = client.get(f"/api/files/{index}/annotation").json()
    shapes = annotation["shapes"]
    assert shapes
    shapes.append(
        {
            "label": "smoke-rect",
            "points": [[10.0, 10.0], [40.0, 30.0]],
            "group_id": None,
            "description": "",
            "shape_type": "rectangle",
            "flags": {},
            "mask": None,
        }
    )
    saved = client.put(
        f"/api/files/{index}/annotation",
        json={"shapes": shapes, "flags": annotation["flags"]},
    )
    assert saved.status_code == 200
    saved_path = Path(saved.json()["saved_path"])
    assert saved_path.exists()
    on_disk = json.loads(saved_path.read_text(encoding="utf-8"))
    labels = [shape["label"] for shape in on_disk["shapes"]]
    assert "smoke-rect" in labels


def test_navigation_and_image_bytes(client: TestClient) -> None:
    session = client.get("/api/session").json()
    assert len(session["files"]) >= 2
    first = session["files"][0]["path"]
    moved = client.post("/api/session/navigate", json={"delta": 1})
    assert moved.status_code == 200
    assert moved.json()["annotation"]["image_path"] != first
    image = client.get("/api/files/1/image")
    assert image.status_code == 200
    assert image.content[:2] in (b"\xff\xd8", b"\x89P") or len(image.content) > 100


def test_open_rejects_missing_path(client: TestClient) -> None:
    response = client.post("/api/session/open", json={"path": "/no/such/labelme/file"})
    assert response.status_code == 400


def test_validate_label_rejects_unknown(
    data_path: Path,
) -> None:
    config = load_config(
        config_file=None,
        config_overrides={"labels": ["cat"], "validate_label": "exact"},
    )
    session = AnnotationSession(
        config=config,
        config_file=None,
        config_overrides={"labels": ["cat"], "validate_label": "exact"},
        output_dir=None,
    )
    session.load_path(str(next((data_path / "annotated").glob("*.jpg"))))
    client = TestClient(create_app(session=session))
    response = client.put(
        "/api/files/0/annotation",
        json={
            "shapes": [
                {
                    "label": "not-in-list",
                    "points": [[1.0, 1.0], [2.0, 2.0]],
                    "group_id": None,
                    "description": "",
                    "shape_type": "rectangle",
                    "flags": {},
                    "mask": None,
                }
            ],
            "flags": {},
        },
    )
    assert response.status_code == 400
    assert "invalid label" in response.json()["detail"]


def test_open_corrupt_sidecar_stays_usable(data_path: Path, tmp_path: Path) -> None:
    import shutil

    jpg = next((data_path / "annotated").glob("*.jpg"))
    shutil.copy(jpg, tmp_path / jpg.name)
    (tmp_path / f"{jpg.stem}.json").write_text("{ not json", encoding="utf-8")

    config = load_config(config_file=None, config_overrides={})
    session = AnnotationSession(
        config=config,
        config_file=None,
        config_overrides={},
        output_dir=None,
    )
    client = TestClient(create_app(session=session))
    response = client.post("/api/session/open", json={"path": str(tmp_path)})
    assert response.status_code == 200
    payload = response.json()
    assert payload["annotation"] is not None
    assert payload["annotation"]["shapes"] == []
    assert payload["load_warning"]
    assert "failed to load" in payload["load_warning"]


def test_ai_point_prompt_compatibility(client: TestClient) -> None:
    response = client.post(
        "/api/ai/assist",
        json={
            "prompt_kind": "points",
            "points": [[10.0, 10.0]],
            "point_labels": [1],
            "model_name": "Sam3",
        },
    )
    assert response.status_code == 400
    assert "does not support point prompts" in response.json()["detail"]

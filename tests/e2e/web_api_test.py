from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from labelme._config import load_config
from labelme._session import AnnotationSession
from labelme._webapp import create_app


def test_health_and_spa(client: TestClient) -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    page = client.get("/")
    assert page.status_code == 200
    assert "Labelme" in page.text
    assert "canvas" in page.text
    assert 'type="module"' in page.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/canvas/renderer.js").status_code == 200


def test_session_lists_annotated_images(client: TestClient) -> None:
    payload = client.get("/api/session").json()
    files = client.get("/api/files").json()
    assert "files" not in payload
    assert files["files"]
    assert any(file["has_annotation"] for file in files["files"])
    assert payload["annotation"] is not None
    assert payload["annotation"]["shapes"]
    assert payload["file_count"] == files["total"]


def test_annotation_round_trip(client: TestClient) -> None:
    files = client.get("/api/files").json()["files"]
    index = next(file["index"] for file in files if file["current"])
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
        json={"shapes": shapes, "flags": annotation["flags"], "client_version": 1},
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["ok"] is True
    assert "files" not in body
    assert body["client_version"] == 1
    saved_path = Path(body["saved_path"])
    assert saved_path.exists()
    on_disk = json.loads(saved_path.read_text(encoding="utf-8"))
    labels = [shape["label"] for shape in on_disk["shapes"]]
    assert "smoke-rect" in labels


def test_navigation_and_image_bytes(client: TestClient) -> None:
    files = client.get("/api/files").json()["files"]
    assert len(files) >= 2
    first = files[0]["path"]
    started = client.get("/api/session").json()["current_index"]
    moved = client.post("/api/session/navigate", json={"delta": 1})
    assert moved.status_code == 200
    assert moved.json()["annotation"]["image_path"] != first
    image = client.get("/api/files/0/image")
    assert image.status_code == 200
    assert image.content[:2] in (b"\xff\xd8", b"\x89P") or len(image.content) > 100
    assert (
        client.get("/api/session").json()["current_index"]
        == moved.json()["current_index"]
    )
    assert client.get("/api/session").json()["current_index"] != started


def test_open_rejects_missing_path(client: TestClient) -> None:
    response = client.post("/api/session/open", json={"path": "/no/such/labelme/file"})
    assert response.status_code == 400


def test_validate_label_rejects_unknown(data_path: Path) -> None:
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

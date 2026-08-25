from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from labelme._webapp import bind_requires_access_token
from labelme._webapp import create_app

from .conftest import make_session


def _rect(label: str) -> dict:
    return {
        "label": label,
        "points": [[10.0, 10.0], [40.0, 30.0]],
        "group_id": None,
        "description": "",
        "shape_type": "rectangle",
        "flags": {},
        "mask": None,
    }


def test_get_image_and_annotation_do_not_change_current(client: TestClient) -> None:
    started = client.get("/api/session").json()
    current = started["current_index"]
    current_path = started["annotation"]["image_path"]
    files = client.get("/api/files").json()["files"]
    other = next(file["index"] for file in files if file["index"] != current)

    other_annotation = client.get(f"/api/files/{other}/annotation")
    assert other_annotation.status_code == 200
    assert other_annotation.json()["image_path"] != current_path
    assert client.get("/api/session").json()["current_index"] == current
    assert client.get("/api/session").json()["annotation"]["image_path"] == current_path

    image = client.get(f"/api/files/{other}/image")
    assert image.status_code == 200
    after = client.get("/api/session").json()
    assert after["current_index"] == current
    assert after["annotation"]["image_path"] == current_path


def test_concurrent_image_gets_do_not_reorder_current(client: TestClient) -> None:
    started = client.get("/api/session").json()["current_index"]
    files = client.get("/api/files").json()["files"]
    indices = [file["index"] for file in files]

    def fetch(index: int) -> int:
        response = client.get(f"/api/files/{index}/image")
        return response.status_code

    with ThreadPoolExecutor(max_workers=len(indices)) as pool:
        statuses = list(pool.map(fetch, indices * 3))
    assert set(statuses) == {200}
    assert client.get("/api/session").json()["current_index"] == started


def test_save_other_index_does_not_switch_current(client: TestClient) -> None:
    started = client.get("/api/session").json()
    current = started["current_index"]
    current_path = started["annotation"]["image_path"]
    other = 1 if current == 0 else 0
    annotation = client.get(f"/api/files/{other}/annotation").json()
    shapes = [*annotation["shapes"], _rect("saved-other")]
    saved = client.put(
        f"/api/files/{other}/annotation",
        json={"shapes": shapes, "flags": annotation["flags"]},
    )
    assert saved.status_code == 200
    after = client.get("/api/session").json()
    assert after["current_index"] == current
    assert after["annotation"]["image_path"] == current_path
    on_disk = json.loads(Path(saved.json()["saved_path"]).read_text(encoding="utf-8"))
    assert "saved-other" in [shape["label"] for shape in on_disk["shapes"]]


def test_post_current_opens_index(client: TestClient) -> None:
    files = client.get("/api/files").json()["files"]
    target = files[-1]["index"]
    payload = client.post("/api/session/current", json={"index": target})
    assert payload.status_code == 200
    assert payload.json()["current_index"] == target
    assert "files" not in payload.json()
    assert client.get("/api/session").json()["current_index"] == target


def test_search_does_not_return_annotation_or_switch_file(client: TestClient) -> None:
    started = client.get("/api/session").json()
    response = client.post("/api/session/search", json={"query": "000025"})
    assert response.status_code == 200
    body = response.json()
    assert "annotation" not in body
    assert body["file_count"] >= 1
    assert (
        client.get("/api/session").json()["current_index"] == started["current_index"]
    )
    assert (
        client.get("/api/session").json()["annotation"]["image_path"]
        == started["annotation"]["image_path"]
    )


def test_file_list_is_paginated(data_path: Path) -> None:
    session = make_session(data_path)
    session.loaded_image_paths = [
        f"/tmp/labelme-fake/{i:05d}.jpg" for i in range(10_000)
    ]
    client = TestClient(create_app(session=session))
    page = client.get("/api/files?offset=5000&limit=40").json()
    assert page["total"] == 10_000
    assert len(page["files"]) == 40
    assert page["files"][0]["index"] == 5000
    assert page["files"][-1]["index"] == 5039


def test_annotation_json_roundtrip_preserves_points(
    client: TestClient, data_path: Path
) -> None:
    source = data_path / "annotated" / "2011_000003.json"
    original = json.loads(source.read_text(encoding="utf-8"))
    files = client.get("/api/files").json()["files"]
    index = next(
        file["index"] for file in files if file["name"].startswith("2011_000003")
    )
    loaded = client.get(f"/api/files/{index}/annotation").json()
    for orig, got in zip(original["shapes"], loaded["shapes"], strict=True):
        assert orig["points"] == got["points"]
        assert orig["label"] == got["label"]
        assert orig["shape_type"] == got["shape_type"]
    saved = client.put(
        f"/api/files/{index}/annotation",
        json={"shapes": loaded["shapes"], "flags": loaded["flags"]},
    )
    assert saved.status_code == 200
    on_disk = json.loads(Path(saved.json()["saved_path"]).read_text(encoding="utf-8"))
    for orig, got in zip(original["shapes"], on_disk["shapes"], strict=True):
        assert orig["points"] == got["points"]
        assert orig["label"] == got["label"]
        assert orig["shape_type"] == got["shape_type"]


def test_bind_requires_access_token_for_non_loopback() -> None:
    assert bind_requires_access_token("127.0.0.1") is False
    assert bind_requires_access_token("localhost") is False
    assert bind_requires_access_token("::1") is False
    assert bind_requires_access_token("0.0.0.0") is True
    assert bind_requires_access_token("192.168.1.8") is True


def test_access_token_protects_api_not_health(data_path: Path) -> None:
    session = make_session(data_path)
    client = TestClient(create_app(session=session, access_token="s3cret"))
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/api/session").status_code == 401
    assert (
        client.get(
            "/api/session", headers={"Authorization": "Bearer s3cret"}
        ).status_code
        == 200
    )
    assert client.get("/api/session?token=s3cret").status_code == 200

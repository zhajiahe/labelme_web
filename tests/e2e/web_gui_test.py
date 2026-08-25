from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TypedDict
from typing import cast

import pytest
import uvicorn
from fastapi import FastAPI
from PIL import Image
from playwright.sync_api import Browser
from playwright.sync_api import Page
from playwright.sync_api import sync_playwright

from labelme._config import load_config
from labelme._session import AnnotationSession
from labelme._webapp import create_app

pytestmark = pytest.mark.gui


class _GuiShape(TypedDict):
    label: str
    points: list[list[float]]
    shape_type: str


class _GuiState(TypedDict):
    shapes: list[_GuiShape]
    flags: dict[str, object]
    dirty: bool
    editVersion: int
    savedVersion: int
    currentIndex: int | None
    imageIndex: int | None
    scale: float
    offsetX: float
    offsetY: float
    tool: str
    imageSize: dict[str, int] | None


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_server(app: FastAPI, port: int) -> uvicorn.Server:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 8
    while time.time() < deadline:
        if server.started:
            return server
        time.sleep(0.05)
    raise RuntimeError("uvicorn failed to start")


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    try:
        with sync_playwright() as playwright:
            try:
                launched = playwright.chromium.launch(headless=True)
            except Exception as exc:  # noqa: BLE001 — missing browser is a skip
                pytest.skip(f"Chromium is not installed: {exc}")
            yield launched
            launched.close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Playwright is unavailable: {exc}")


@pytest.fixture()
def page(browser: Browser) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    opened = context.new_page()
    yield opened
    opened.close()
    context.close()


@pytest.fixture()
def live_url(data_path: Path) -> Iterator[str]:
    overrides = {"auto_save": False, "display_label_popup": False}
    config = load_config(config_file=None, config_overrides=overrides)
    session = AnnotationSession(
        config=config,
        config_file=None,
        config_overrides=overrides,
        output_dir=None,
    )
    session.load_path(str(data_path / "annotated"))
    port = _free_port()
    server = _start_server(create_app(session=session), port)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


@pytest.fixture()
def autosave_url(data_path: Path) -> Iterator[str]:
    overrides = {"auto_save": True, "display_label_popup": False}
    config = load_config(config_file=None, config_overrides=overrides)
    session = AnnotationSession(
        config=config,
        config_file=None,
        config_overrides=overrides,
        output_dir=None,
    )
    session.load_path(str(data_path / "annotated"))
    port = _free_port()
    server = _start_server(create_app(session=session), port)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


def _ready(page: Page, url: str) -> None:
    page.goto(url)
    page.wait_for_function(
        "() => window.__labelme && window.__labelme.getState().imageSize",
        timeout=15_000,
    )


def _click_image(page: Page, x: float, y: float) -> None:
    pos = page.evaluate("([x, y]) => window.__labelme.imageToClient(x, y)", [x, y])
    page.mouse.click(pos["x"], pos["y"])


def _state(page: Page) -> _GuiState:
    return cast(_GuiState, page.evaluate("() => window.__labelme.getState()"))


def test_rectangle_create_move_vertex_delete_undo(page: Page, live_url: str) -> None:
    _ready(page, live_url)
    page.evaluate("() => window.__labelme.setTool('rectangle')")
    _click_image(page, 20, 20)
    _click_image(page, 80, 60)
    shapes = _state(page)["shapes"]
    assert any(
        shape["shape_type"] == "rectangle" and shape["label"] == "object"
        for shape in shapes
    )
    rect = next(shape for shape in shapes if shape["label"] == "object")
    assert rect["points"][0][0] == pytest.approx(20, abs=2)
    assert rect["points"][1][0] == pytest.approx(80, abs=2)

    page.evaluate("() => window.__labelme.setTool('edit')")
    _click_image(page, 50, 40)
    page.mouse.down()
    end = page.evaluate("([x, y]) => window.__labelme.imageToClient(x, y)", [70, 55])
    page.mouse.move(end["x"], end["y"])
    page.mouse.up()
    moved = _state(page)["shapes"][-1]["points"]
    assert moved[0][0] != pytest.approx(20, abs=0.1) or moved[1][0] != pytest.approx(
        80, abs=0.1
    )

    page.locator("#btn-delete").click()
    assert all(shape["label"] != "object" for shape in _state(page)["shapes"])
    page.locator("#btn-undo").click()
    assert any(shape["label"] == "object" for shape in _state(page)["shapes"])
    page.locator("#btn-redo").click()
    assert all(shape["label"] != "object" for shape in _state(page)["shapes"])


def test_polygon_create(page: Page, live_url: str) -> None:
    _ready(page, live_url)
    page.evaluate("() => window.__labelme.setTool('polygon')")
    _click_image(page, 30, 30)
    _click_image(page, 90, 30)
    _click_image(page, 60, 80)
    page.locator("#canvas").dblclick()
    shapes = _state(page)["shapes"]
    assert any(
        shape["shape_type"] == "polygon" and len(shape["points"]) >= 3
        for shape in shapes
    )


def test_zoom_and_pan_keep_image_coordinates(page: Page, live_url: str) -> None:
    _ready(page, live_url)
    before = _state(page)
    page.mouse.wheel(0, -400)
    page.mouse.move(400, 300)
    page.keyboard.down("Shift")
    page.mouse.down()
    page.mouse.move(450, 340)
    page.mouse.up()
    page.keyboard.up("Shift")
    after = _state(page)
    assert after["scale"] != before["scale"] or after["offsetX"] != before["offsetX"]
    page.evaluate("() => window.__labelme.setTool('rectangle')")
    _click_image(page, 15, 15)
    _click_image(page, 45, 45)
    rect = next(shape for shape in _state(page)["shapes"] if shape["label"] == "object")
    assert rect["points"][0][0] == pytest.approx(15, abs=3)
    assert rect["points"][1][1] == pytest.approx(45, abs=3)


def test_unsaved_navigation_prompts(page: Page, live_url: str, data_path: Path) -> None:
    _ready(page, live_url)
    source = next((data_path / "annotated").glob("2011_000003.json"))
    before = source.read_text(encoding="utf-8")
    page.evaluate("() => window.__labelme.setTool('rectangle')")
    _click_image(page, 12, 12)
    _click_image(page, 40, 40)
    assert _state(page)["dirty"] is True
    page.locator("#btn-next").click()
    dialog = page.locator("#unsaved-dialog")
    dialog.wait_for(state="visible")
    page.locator("#unsaved-dialog button[value='discard']").click()
    page.wait_for_function("() => !window.__labelme.getState().dirty")
    assert source.read_text(encoding="utf-8") == before


def test_autosave_keeps_latest_edit(
    page: Page, autosave_url: str, data_path: Path
) -> None:
    _ready(page, autosave_url)
    page.evaluate("() => window.__labelme.setTool('rectangle')")
    _click_image(page, 10, 10)
    _click_image(page, 30, 30)
    _click_image(page, 50, 50)
    _click_image(page, 90, 90)
    page.wait_for_function(
        "() => window.__labelme.getState().dirty === false",
        timeout=5_000,
    )
    saved = json.loads(
        next((data_path / "annotated").glob("2011_000003.json")).read_text(
            encoding="utf-8"
        )
    )
    labels = [shape["label"] for shape in saved["shapes"]]
    assert labels.count("object") >= 2


def test_rapid_navigation_keeps_image_aligned(page: Page, live_url: str) -> None:
    _ready(page, live_url)
    for _ in range(8):
        page.locator("#btn-next").click()
        page.locator("#btn-prev").click()
    page.wait_for_timeout(400)
    state = _state(page)
    assert state["imageIndex"] == state["currentIndex"]


def test_draw_1000_boxes_stays_interactive(page: Page, live_url: str) -> None:
    _ready(page, live_url)
    elapsed = page.evaluate(
        """() => {
          const shapes = [];
          for (let i = 0; i < 1000; i += 1) {
            const x = i % 200;
            const y = Math.floor(i / 200) * 6;
            shapes.push({
              label: "n",
              points: [[x, y], [x + 4, y + 4]],
              shape_type: "rectangle",
              flags: {},
              description: "",
              group_id: null,
              mask: null,
            });
          }
          window.__labelme.replaceShapes(shapes);
          const t0 = performance.now();
          window.__labelme.draw();
          return performance.now() - t0;
        }"""
    )
    assert elapsed < 2000
    assert len(_state(page)["shapes"]) == 1000


def test_virtual_file_list_does_not_mount_every_row(tmp_path: Path, page: Page) -> None:
    root = tmp_path / "many"
    root.mkdir()
    image = Image.new("RGB", (8, 8), (20, 20, 20))
    for index in range(200):
        image.save(root / f"{index:03d}.png")
    overrides = {"auto_save": False, "display_label_popup": False}
    config = load_config(config_file=None, config_overrides=overrides)
    session = AnnotationSession(
        config=config,
        config_file=None,
        config_overrides=overrides,
        output_dir=None,
    )
    session.load_path(str(root))
    port = _free_port()
    server = _start_server(create_app(session=session), port)
    try:
        _ready(page, f"http://127.0.0.1:{port}")
        count = page.locator("#file-list li").count()
        assert count < 80
        assert count > 0
    finally:
        server.should_exit = True

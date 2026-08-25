import { emptyShape, neededPoints, orientedRectPoints } from "../annotation/shapes.js";
import { cloneShapes } from "../annotation/shapes.js";
import { pushHistory } from "../annotation/history.js";
import { $ } from "../dom.js";
import { markDirty, state } from "../store.js";
import { askLabel } from "../ui/dialogs.js";
import { hitTest } from "./hit-test.js";
import { draw, setStatus } from "./renderer.js";
import { canvas, canvasToImage, clampPoint, pointerInfo } from "./transform.js";

export function setTool(tool) {
  state.tool = tool;
  state.draft = null;
  document.querySelectorAll(".tool").forEach((button) => {
    button.classList.toggle("active", button.dataset.tool === tool);
  });
  canvas.style.cursor = tool === "edit" ? "default" : "crosshair";
}

function startDraft(type, point) {
  state.draft = emptyShape(type, point);
  if (type === "oriented_rectangle") state.draft.stage = "edge";
}

async function finalizeDraft({ onChanged } = {}) {
  const draft = state.draft;
  if (!draft) return;
  const needed = neededPoints(draft.shape_type);
  if (draft.points.length < needed) return;
  if (state.session?.config?.display_label_popup) {
    const meta = await askLabel(draft);
    if (!meta || !meta.label) {
      state.draft = null;
      draw();
      return;
    }
    Object.assign(draft, meta);
    state.lastLabel = meta.label;
  } else {
    draft.label = draft.label || state.lastLabel || "object";
  }
  const labels = state.session?.config?.labels || [];
  if (state.session?.config?.validate_label === "exact" && !labels.includes(draft.label)) {
    setStatus(`Invalid label: ${draft.label}`);
    state.draft = null;
    draw();
    return;
  }
  delete draft.stage;
  delete draft._ai;
  pushHistory();
  state.shapes.push(draft);
  state.draft = null;
  state.selected = new Set([state.shapes.length - 1]);
  markDirty();
  onChanged?.();
}

function updateCrosshair(event) {
  const show = Boolean(state.session?.config?.canvas?.crosshair?.[state.tool]);
  $("crosshair-x").classList.toggle("hidden", !show);
  $("crosshair-y").classList.toggle("hidden", !show);
  if (!show) return;
  const { canvasPoint } = pointerInfo(event);
  $("crosshair-x").style.top = `${canvasPoint[1]}px`;
  $("crosshair-y").style.left = `${canvasPoint[0]}px`;
}

export function bindCanvas({ onChanged, onAiBox, onAiPoints, runAiPoints } = {}) {
  canvas.addEventListener("mousedown", async (event) => {
    const { imagePoint, canvasPoint } = pointerInfo(event);
    if (event.button === 1 || event.shiftKey || state.tool === "pan") {
      state.drag = {
        kind: "pan",
        x: canvasPoint[0],
        y: canvasPoint[1],
        ox: state.offsetX,
        oy: state.offsetY,
      };
      return;
    }
    if (state.tool === "edit") {
      const hit = hitTest(imagePoint);
      if (event.button === 2) return;
      if (hit?.kind === "vertex") {
        pushHistory();
        state.selected = new Set([hit.index]);
        state.drag = { kind: "vertex", index: hit.index, vertex: hit.vertex };
      } else if (hit?.kind === "body") {
        pushHistory();
        state.selected = new Set([hit.index]);
        state.drag = {
          kind: "move",
          index: hit.index,
          origin: imagePoint,
          start: cloneShapes([hit.shape])[0].points,
        };
      } else {
        state.selected.clear();
      }
      onChanged?.({ lists: true, autosave: false });
      return;
    }
    if (state.tool === "ai_points") {
      state.aiPoints.push({ xy: imagePoint, label: event.altKey ? 0 : 1 });
      draw();
      return;
    }
    if (state.tool === "ai_box") {
      startDraft("rectangle", imagePoint);
      state.draft._ai = true;
      return;
    }
    if (state.draft?.shape_type === "oriented_rectangle" && state.draft.stage === "edge") {
      state.draft.points[1] = imagePoint;
      state.draft.stage = "height";
      state.draft.points = orientedRectPoints(
        state.draft.points[0],
        state.draft.points[1],
        imagePoint,
      );
      draw();
      return;
    }
    if (state.draft?.shape_type === "oriented_rectangle" && state.draft.stage === "height") {
      await finalizeDraft({ onChanged: () => onChanged?.({ lists: true }) });
      return;
    }
    if (!state.draft) {
      const type = state.tool === "oriented_rectangle" ? "oriented_rectangle" : state.tool;
      startDraft(type, imagePoint);
      if (type === "point") await finalizeDraft({ onChanged: () => onChanged?.({ lists: true }) });
      draw();
      return;
    }
    if (["rectangle", "circle", "line"].includes(state.draft.shape_type)) {
      state.draft.points[1] = imagePoint;
      if (state.draft._ai) {
        const box = state.draft;
        state.draft = null;
        await onAiBox?.(box);
        return;
      }
      await finalizeDraft({ onChanged: () => onChanged?.({ lists: true }) });
      return;
    }
    state.draft.points.push(imagePoint);
    draw();
  });

  canvas.addEventListener("dblclick", async (event) => {
    event.preventDefault();
    if (state.draft && ["polygon", "linestrip"].includes(state.draft.shape_type)) {
      await finalizeDraft({ onChanged: () => onChanged?.({ lists: true }) });
    }
  });

  canvas.addEventListener("mousemove", (event) => {
    updateCrosshair(event);
    const { imagePoint, canvasPoint } = pointerInfo(event);
    if (state.drag?.kind === "pan") {
      state.offsetX = state.drag.ox + (canvasPoint[0] - state.drag.x);
      state.offsetY = state.drag.oy + (canvasPoint[1] - state.drag.y);
      draw();
      return;
    }
    if (state.drag?.kind === "vertex") {
      state.shapes[state.drag.index].points[state.drag.vertex] = imagePoint;
      draw();
      return;
    }
    if (state.drag?.kind === "move") {
      const dx = imagePoint[0] - state.drag.origin[0];
      const dy = imagePoint[1] - state.drag.origin[1];
      state.shapes[state.drag.index].points = state.drag.start.map((p) => (
        clampPoint([p[0] + dx, p[1] + dy])
      ));
      draw();
      return;
    }
    if (state.draft?.shape_type === "oriented_rectangle" && state.draft.stage === "height") {
      const [a, b] = state.draft.points;
      state.draft.points = orientedRectPoints(a, b, imagePoint);
      draw();
      return;
    }
    if (state.draft && ["rectangle", "circle", "line", "oriented_rectangle"].includes(state.draft.shape_type)) {
      state.draft.points[1] = imagePoint;
      draw();
    }
    state.hover = hitTest(imagePoint);
    const stats = state.hover
      ? `x=${imagePoint[0].toFixed(1)} y=${imagePoint[1].toFixed(1)} ${state.hover.kind}`
      : `x=${imagePoint[0].toFixed(1)} y=${imagePoint[1].toFixed(1)}`;
    setStatus(stats);
  });

  canvas.addEventListener("mouseup", () => {
    if (state.drag && state.drag.kind !== "pan") {
      markDirty();
      onChanged?.({ lists: true });
    }
    state.drag = null;
  });

  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    const { canvasPoint } = pointerInfo(event);
    const before = canvasToImage(canvasPoint);
    const factor = event.deltaY < 0 ? 1.1 : 0.9;
    state.scale = Math.min(8, Math.max(0.05, state.scale * factor));
    const after = [
      before[0] * state.scale + state.offsetX,
      before[1] * state.scale + state.offsetY,
    ];
    state.offsetX += canvasPoint[0] - after[0];
    state.offsetY += canvasPoint[1] - after[1];
    $("zoom").value = String(Math.round(state.scale * 100));
    draw();
  }, { passive: false });

  canvas.addEventListener("contextmenu", (event) => event.preventDefault());

  window.addEventListener("keydown", async (event) => {
    if (event.target.closest("input, textarea, select, dialog")) return;
    if (event.key === "Enter" && state.draft) {
      event.preventDefault();
      await finalizeDraft({ onChanged: () => onChanged?.({ lists: true }) });
    } else if (event.key === "Enter" && state.tool === "ai_points") {
      await runAiPoints?.();
    }
  });
}

export { finalizeDraft };

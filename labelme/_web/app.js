const state = {
  session: null,
  image: null,
  imageUrl: null,
  shapes: [],
  flags: {},
  selected: new Set(),
  tool: "edit",
  draft: null,
  hover: null,
  drag: null,
  scale: 1,
  offsetX: 0,
  offsetY: 0,
  brightness: 0,
  contrast: 0,
  history: [],
  lastLabel: "",
  aiPoints: [],
};

const $ = (id) => document.getElementById(id);
const canvas = $("canvas");
const ctx = canvas.getContext("2d");

function themeFromConfig(theme) {
  if (theme === "light" || theme === "dark") return theme;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = themeFromConfig(theme);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      detail = await response.text();
    }
    throw new Error(detail);
  }
  if (response.headers.get("content-type")?.includes("application/json")) {
    return response.json();
  }
  return response;
}

function setStatus(message) {
  $("status").textContent = message;
}

function currentIndex() {
  const files = state.session?.files || [];
  const current = files.find((file) => file.current);
  return current ? current.index : 0;
}

function colorFor(label) {
  const colors = state.session?.annotation?.colors || {};
  return colors[label] || [0, 220, 90];
}

function cssColor(rgb, alpha = 1) {
  return `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})`;
}

function cloneShapes(shapes) {
  return JSON.parse(JSON.stringify(shapes));
}

function pushHistory() {
  state.history.push(cloneShapes(state.shapes));
  if (state.history.length > 30) state.history.shift();
}

function undo() {
  const previous = state.history.pop();
  if (!previous) return;
  state.shapes = previous;
  state.selected.clear();
  renderAll();
  maybeAutosave();
}

function imageToCanvas([x, y]) {
  return [x * state.scale + state.offsetX, y * state.scale + state.offsetY];
}

function canvasToImage([x, y]) {
  return [(x - state.offsetX) / state.scale, (y - state.offsetY) / state.scale];
}

function clampPoint(point) {
  const allow = state.session?.config?.canvas?.allow_out_of_bounds_points;
  if (allow || !state.image) return point;
  return [
    Math.min(Math.max(point[0], 0), state.image.width),
    Math.min(Math.max(point[1], 0), state.image.height),
  ];
}

function dist(a, b) {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

function pointInPoly(point, vertices) {
  let inside = false;
  for (let i = 0, j = vertices.length - 1; i < vertices.length; j = i++) {
    const xi = vertices[i][0];
    const yi = vertices[i][1];
    const xj = vertices[j][0];
    const yj = vertices[j][1];
    const intersect = yi > point[1] !== yj > point[1]
      && point[0] < ((xj - xi) * (point[1] - yi)) / (yj - yi + 1e-12) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

function shapeContains(shape, point) {
  const pts = shape.points;
  if (shape.shape_type === "point") return dist(pts[0], point) * state.scale <= 8;
  if (shape.shape_type === "line" || shape.shape_type === "linestrip") {
    for (let i = 1; i < pts.length; i += 1) {
      const a = pts[i - 1];
      const b = pts[i];
      const t = Math.max(
        0,
        Math.min(
          1,
          ((point[0] - a[0]) * (b[0] - a[0]) + (point[1] - a[1]) * (b[1] - a[1]))
            / (dist(a, b) ** 2 || 1),
        ),
      );
      const proj = [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])];
      if (dist(proj, point) * state.scale < 8) return true;
    }
    return false;
  }
  if (shape.shape_type === "circle") {
    return dist(pts[0], point) <= dist(pts[0], pts[1]);
  }
  if (shape.shape_type === "rectangle" || shape.shape_type === "mask") {
    const xs = [pts[0][0], pts[1][0]];
    const ys = [pts[0][1], pts[1][1]];
    return point[0] >= Math.min(...xs) && point[0] <= Math.max(...xs)
      && point[1] >= Math.min(...ys) && point[1] <= Math.max(...ys);
  }
  return pointInPoly(point, pts);
}

function nearestVertex(shape, point, epsilon = 10) {
  let best = null;
  shape.points.forEach((vertex, index) => {
    const d = dist(vertex, point) * state.scale;
    if (d <= epsilon && (best === null || d < best.d)) best = { index, d };
  });
  return best?.index ?? null;
}

function hitTest(point) {
  for (let i = state.shapes.length - 1; i >= 0; i -= 1) {
    const shape = state.shapes[i];
    const vertex = nearestVertex(shape, point);
    if (vertex !== null) return { kind: "vertex", shape, index: i, vertex };
    if (shapeContains(shape, point)) return { kind: "body", shape, index: i };
  }
  return null;
}

function resizeCanvas() {
  const wrap = canvas.parentElement;
  canvas.width = wrap.clientWidth;
  canvas.height = wrap.clientHeight;
  draw();
}

function fitImage() {
  if (!state.image) return;
  const pad = 24;
  const sx = (canvas.width - pad) / state.image.width;
  const sy = (canvas.height - pad) / state.image.height;
  state.scale = Math.max(0.05, Math.min(sx, sy));
  state.offsetX = (canvas.width - state.image.width * state.scale) / 2;
  state.offsetY = (canvas.height - state.image.height * state.scale) / 2;
  $("zoom").value = String(Math.round(state.scale * 100));
}

function drawShape(shape, { selected = false, draft = false } = {}) {
  const rgb = colorFor(shape.label || "");
  ctx.lineWidth = selected ? 2.5 : 2;
  ctx.strokeStyle = selected ? "#fff" : cssColor(rgb, 0.95);
  ctx.fillStyle = cssColor(rgb, draft || state.session?.config?.canvas?.fill_drawing ? 0.18 : 0.08);
  const pts = shape.points.map(imageToCanvas);
  ctx.beginPath();
  if (shape.shape_type === "point" && pts[0]) {
    ctx.arc(pts[0][0], pts[0][1], 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    return;
  }
  if (shape.shape_type === "circle" && pts.length >= 2) {
    const radius = dist(pts[0], pts[1]);
    ctx.arc(pts[0][0], pts[0][1], radius, 0, Math.PI * 2);
  } else if ((shape.shape_type === "rectangle" || shape.shape_type === "mask") && pts.length >= 2) {
    const x = Math.min(pts[0][0], pts[1][0]);
    const y = Math.min(pts[0][1], pts[1][1]);
    ctx.rect(x, y, Math.abs(pts[1][0] - pts[0][0]), Math.abs(pts[1][1] - pts[0][1]));
  } else if (pts.length) {
    ctx.moveTo(pts[0][0], pts[0][1]);
    pts.slice(1).forEach((p) => ctx.lineTo(p[0], p[1]));
    if (["polygon", "oriented_rectangle"].includes(shape.shape_type) && !draft) ctx.closePath();
  }
  if (shape.shape_type !== "line" && shape.shape_type !== "linestrip") ctx.fill();
  ctx.stroke();
  pts.forEach((p, index) => {
    ctx.fillStyle = selected && state.hover?.vertex === index ? "#fff" : cssColor(rgb);
    ctx.fillRect(p[0] - 3, p[1] - 3, 6, 6);
  });
  if (state.session?.config?.shape?.show_labels && shape.label && pts[0]) {
    ctx.fillStyle = "#fff";
    ctx.font = "12px sans-serif";
    ctx.fillText(shape.label, pts[0][0] + 6, pts[0][1] - 6);
  }
}

function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (state.image) {
    ctx.save();
    const b = 1 + state.brightness / 100;
    const c = 1 + state.contrast / 100;
    ctx.filter = `brightness(${b}) contrast(${c})`;
    ctx.drawImage(
      state.image,
      state.offsetX,
      state.offsetY,
      state.image.width * state.scale,
      state.image.height * state.scale,
    );
    ctx.restore();
  }
  state.shapes.forEach((shape, index) => {
    drawShape(shape, { selected: state.selected.has(index) });
  });
  if (state.draft) drawShape(state.draft, { draft: true, selected: true });
  state.aiPoints.forEach((point) => {
    const [x, y] = imageToCanvas(point.xy);
    ctx.fillStyle = point.label > 0 ? "#22c55e" : "#f43f5e";
    ctx.beginPath();
    ctx.arc(x, y, 5, 0, Math.PI * 2);
    ctx.fill();
  });
}

function renderFiles() {
  const list = $("file-list");
  list.innerHTML = "";
  (state.session?.files || []).forEach((file) => {
    const item = document.createElement("li");
    item.textContent = `${file.has_annotation ? "●" : "○"} ${file.name}`;
    item.title = file.path;
    item.className = file.current ? "current" : "";
    item.addEventListener("click", () => openIndex(file.index));
    list.appendChild(item);
  });
}

function renderShapes() {
  const list = $("shape-list");
  list.innerHTML = "";
  state.shapes.forEach((shape, index) => {
    const item = document.createElement("li");
    item.textContent = `${shape.label || "(unlabeled)"} · ${shape.shape_type}`;
    if (state.selected.has(index)) item.classList.add("selected");
    item.addEventListener("click", () => {
      state.selected = new Set([index]);
      renderAll();
    });
    list.appendChild(item);
  });
}

function renderLabels() {
  const list = $("label-list");
  const options = $("label-options");
  list.innerHTML = "";
  options.innerHTML = "";
  const labels = state.session?.annotation?.labels || state.session?.config?.labels || [];
  labels.forEach((label) => {
    const item = document.createElement("li");
    const rgb = colorFor(label);
    item.textContent = label;
    item.style.borderColor = cssColor(rgb);
    list.appendChild(item);
    const option = document.createElement("option");
    option.value = label;
    options.appendChild(option);
  });
}

function renderFlags() {
  const list = $("flag-list");
  list.innerHTML = "";
  const names = new Set([
    ...(state.session?.config?.flags || []),
    ...Object.keys(state.flags || {}),
  ]);
  names.forEach((name) => {
    const item = document.createElement("li");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = Boolean(state.flags[name]);
    box.addEventListener("change", () => {
      state.flags[name] = box.checked;
      maybeAutosave();
    });
    item.append(box, ` ${name}`);
    list.appendChild(item);
  });
}

function renderAll() {
  $("title").textContent = state.session?.title || "Labelme";
  document.title = state.session?.title || "Labelme";
  applyTheme(state.session?.config?.color_theme);
  renderFiles();
  renderShapes();
  renderLabels();
  renderFlags();
  draw();
}

function applySession(session, { resetView = false } = {}) {
  state.session = session;
  const annotation = session.annotation;
  state.shapes = annotation ? cloneShapes(annotation.shapes) : [];
  state.flags = { ...(annotation?.flags || {}) };
  state.selected.clear();
  state.draft = null;
  state.aiPoints = [];
  const model = $("ai-model");
  if (!model.options.length) {
    (session.ai_models || []).forEach((option) => {
      const el = document.createElement("option");
      el.value = option.display_name;
      el.textContent = option.display_name;
      model.appendChild(el);
    });
  }
  model.value = session.config?.ai?.default || model.value;
  renderAll();
  if (annotation) loadImage(currentIndex(), resetView);
  else {
    state.image = null;
    draw();
  }
}

async function loadImage(index, resetView) {
  if (state.imageUrl) URL.revokeObjectURL(state.imageUrl);
  const response = await fetch(`/api/files/${index}/image`);
  if (!response.ok) throw new Error("Failed to load image");
  const blob = await response.blob();
  state.imageUrl = URL.createObjectURL(blob);
  const image = new Image();
  await new Promise((resolve, reject) => {
    image.onload = resolve;
    image.onerror = reject;
    image.src = state.imageUrl;
  });
  state.image = image;
  if (resetView || state.scale === 1) fitImage();
  draw();
}

async function refreshSession() {
  applySession(await api("/api/session"), { resetView: !state.image });
}

async function openPath(path) {
  setStatus(`Opening ${path}…`);
  applySession(await api("/api/session/open", {
    method: "POST",
    body: JSON.stringify({ path }),
  }), { resetView: true });
  setStatus("Ready");
}

async function openIndex(index) {
  setStatus("Loading…");
  applySession(await api(`/api/files/${index}/annotation`).then(async () => api("/api/session")), {
    resetView: !state.session?.config?.keep_prev_scale,
  });
  setStatus("Ready");
}

function payload() {
  return {
    shapes: state.shapes,
    flags: state.flags,
  };
}

async function save() {
  const index = currentIndex();
  setStatus("Saving…");
  applySession(await api(`/api/files/${index}/annotation`, {
    method: "PUT",
    body: JSON.stringify(payload()),
  }));
  setStatus("Saved");
}

let saveTimer = null;
function maybeAutosave() {
  if (!state.session?.config?.auto_save) {
    if (state.session) state.session.dirty = true;
    $("title").textContent = `${state.session?.title || "Labelme"}`.replace(/\*?$/, "*");
    return;
  }
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => save().catch((error) => setStatus(error.message)), 400);
}

function askLabel(shape) {
  return new Promise((resolve) => {
    const dialog = $("label-dialog");
    $("label-input").value = shape.label || state.lastLabel || "";
    $("group-id").value = shape.group_id ?? "";
    $("description").value = shape.description || "";
    const flagHost = $("shape-flag-list");
    flagHost.innerHTML = "";
    const labelFlags = state.session?.config?.label_flags || {};
    Object.entries(labelFlags).forEach(([pattern, keys]) => {
      try {
        if (!new RegExp(pattern).test($("label-input").value || ".*")) return;
      } catch {
        return;
      }
      keys.forEach((key) => {
        const label = document.createElement("label");
        const box = document.createElement("input");
        box.type = "checkbox";
        box.dataset.flag = key;
        box.checked = Boolean(shape.flags?.[key]);
        label.append(box, ` ${key}`);
        flagHost.appendChild(label);
      });
    });
    const finish = (ok) => {
      dialog.close();
      if (!ok) return resolve(null);
      const flags = {};
      flagHost.querySelectorAll("input[data-flag]").forEach((box) => {
        flags[box.dataset.flag] = box.checked;
      });
      resolve({
        label: $("label-input").value.trim(),
        group_id: $("group-id").value === "" ? null : Number($("group-id").value),
        description: $("description").value,
        flags,
      });
    };
    $("label-ok").onclick = (event) => {
      event.preventDefault();
      finish(true);
    };
    dialog.addEventListener("close", () => finish(dialog.returnValue === "ok"), { once: true });
    dialog.showModal();
    $("label-input").focus();
  });
}

async function finalizeDraft() {
  const draft = state.draft;
  if (!draft) return;
  const needed = {
    point: 1,
    line: 2,
    rectangle: 2,
    circle: 2,
    mask: 2,
    polygon: 3,
    linestrip: 2,
    oriented_rectangle: 4,
  }[draft.shape_type] || 1;
  if (draft.points.length < needed) return;
  if (draft.shape_type === "oriented_rectangle" && draft.points.length === 2) {
    const [a, b] = draft.points;
    draft.points = [[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]];
  }
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
  pushHistory();
  state.shapes.push(draft);
  state.draft = null;
  state.selected = new Set([state.shapes.length - 1]);
  renderAll();
  maybeAutosave();
}

function startDraft(type, point) {
  state.draft = {
    label: "",
    points: [point],
    shape_type: type,
    flags: {},
    description: "",
    group_id: null,
    mask: null,
  };
}

function pointerInfo(event) {
  const rect = canvas.getBoundingClientRect();
  const canvasPoint = [event.clientX - rect.left, event.clientY - rect.top];
  return { canvasPoint, imagePoint: clampPoint(canvasToImage(canvasPoint)) };
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

canvas.addEventListener("mousedown", async (event) => {
  const { imagePoint, canvasPoint } = pointerInfo(event);
  if (event.button === 1 || event.shiftKey || state.tool === "pan") {
    state.drag = { kind: "pan", x: canvasPoint[0], y: canvasPoint[1], ox: state.offsetX, oy: state.offsetY };
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
      state.drag = { kind: "move", index: hit.index, origin: imagePoint, start: cloneShapes([hit.shape])[0].points };
    } else {
      state.selected.clear();
    }
    renderAll();
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
  if (!state.draft) {
    const type = state.tool === "oriented_rectangle" ? "oriented_rectangle" : state.tool;
    startDraft(type, imagePoint);
    if (type === "point") await finalizeDraft();
    draw();
    return;
  }
  if (["rectangle", "circle", "line", "oriented_rectangle"].includes(state.draft.shape_type)
    && state.draft.points.length === 1) {
    state.draft.points[1] = imagePoint;
    if (state.draft.shape_type === "oriented_rectangle") {
      const [a, b] = state.draft.points;
      state.draft.points = [[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]];
    }
    await finalizeDraft();
    return;
  }
  state.draft.points.push(imagePoint);
  draw();
});

canvas.addEventListener("dblclick", async (event) => {
  event.preventDefault();
  if (state.draft && ["polygon", "linestrip"].includes(state.draft.shape_type)) {
    await finalizeDraft();
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
    state.shapes[state.drag.index].points = state.drag.start.map((p) => clampPoint([p[0] + dx, p[1] + dy]));
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
  if (state.drag && state.drag.kind !== "pan") maybeAutosave();
  state.drag = null;
});

canvas.addEventListener("wheel", (event) => {
  event.preventDefault();
  const { canvasPoint } = pointerInfo(event);
  const before = canvasToImage(canvasPoint);
  const factor = event.deltaY < 0 ? 1.1 : 0.9;
  state.scale = Math.min(8, Math.max(0.05, state.scale * factor));
  const after = imageToCanvas(before);
  state.offsetX += canvasPoint[0] - after[0];
  state.offsetY += canvasPoint[1] - after[1];
  $("zoom").value = String(Math.round(state.scale * 100));
  draw();
}, { passive: false });

canvas.addEventListener("contextmenu", (event) => event.preventDefault());

function setTool(tool) {
  state.tool = tool;
  state.draft = null;
  document.querySelectorAll(".tool").forEach((button) => {
    button.classList.toggle("active", button.dataset.tool === tool);
  });
  canvas.style.cursor = tool === "edit" ? "default" : "crosshair";
}

document.querySelectorAll(".tool").forEach((button) => {
  button.addEventListener("click", () => setTool(button.dataset.tool));
});

$("btn-open").addEventListener("click", () => {
  const path = $("open-path").value.trim();
  if (path) openPath(path).catch((error) => setStatus(error.message));
});
$("open-path").addEventListener("keydown", (event) => {
  if (event.key === "Enter") $("btn-open").click();
});
$("btn-prev").addEventListener("click", () => api("/api/session/navigate", {
  method: "POST",
  body: JSON.stringify({ delta: -1 }),
}).then((session) => applySession(session, { resetView: !state.session?.config?.keep_prev_scale })).catch((error) => setStatus(error.message)));
$("btn-next").addEventListener("click", () => api("/api/session/navigate", {
  method: "POST",
  body: JSON.stringify({ delta: 1 }),
}).then((session) => applySession(session, { resetView: !state.session?.config?.keep_prev_scale })).catch((error) => setStatus(error.message)));
$("btn-save").addEventListener("click", () => save().catch((error) => setStatus(error.message)));
$("btn-undo").addEventListener("click", undo);
$("btn-delete").addEventListener("click", () => {
  if (!state.selected.size) return;
  pushHistory();
  state.shapes = state.shapes.filter((_, index) => !state.selected.has(index));
  state.selected.clear();
  renderAll();
  maybeAutosave();
});
$("btn-fit").addEventListener("click", () => {
  fitImage();
  draw();
});
$("zoom").addEventListener("input", () => {
  state.scale = Number($("zoom").value) / 100;
  draw();
});
$("brightness").addEventListener("input", () => {
  state.brightness = Number($("brightness").value);
  draw();
});
$("contrast").addEventListener("input", () => {
  state.contrast = Number($("contrast").value);
  draw();
});
$("file-search").addEventListener("input", () => {
  api("/api/session/search", {
    method: "POST",
    body: JSON.stringify({ query: $("file-search").value }),
  }).then((session) => applySession(session)).catch((error) => setStatus(error.message));
});

$("btn-ai-text").addEventListener("click", async () => {
  try {
    setStatus("Running AI text prompt…");
    const result = await api("/api/ai/text", {
      method: "POST",
      body: JSON.stringify({
        text: $("ai-text").value,
        output_format: $("ai-text-format").value,
        model_name: $("ai-model").value,
      }),
    });
    pushHistory();
    state.shapes.push(...(result.new_shapes || []));
    renderAll();
    maybeAutosave();
    setStatus(`Added ${result.new_shapes?.length || 0} shapes`);
  } catch (error) {
    setStatus(error.message);
  }
});

async function runAiPoints() {
  if (!state.aiPoints.length) return;
  try {
    setStatus("Running AI Assist…");
    const result = await api("/api/ai/assist", {
      method: "POST",
      body: JSON.stringify({
        prompt_kind: "points",
        points: state.aiPoints.map((p) => p.xy),
        point_labels: state.aiPoints.map((p) => p.label),
        output_format: "polygon",
        existing_shapes: state.shapes,
        model_name: $("ai-model").value,
      }),
    });
    pushHistory();
    state.shapes.push(...(result.new_shapes || []));
    state.aiPoints = [];
    renderAll();
    maybeAutosave();
    setStatus(`AI Assist added ${result.new_shapes?.length || 0}`);
  } catch (error) {
    setStatus(error.message);
  }
}

$("btn-settings").addEventListener("click", () => {
  const body = $("settings-body");
  body.innerHTML = "";
  const groups = {};
  (state.session?.settings || []).forEach((setting) => {
    groups[setting.group] ||= [];
    groups[setting.group].push(setting);
  });
  Object.entries(groups).forEach(([group, settings]) => {
    const section = document.createElement("section");
    const heading = document.createElement("h2");
    heading.textContent = group;
    section.appendChild(heading);
    settings.forEach((setting) => {
      const label = document.createElement("label");
      label.textContent = setting.label + (setting.beta ? " (BETA)" : "");
      let control;
      if (setting.kind === "bool") {
        control = document.createElement("input");
        control.type = "checkbox";
        control.checked = Boolean(setting.value);
      } else if (setting.kind === "enum") {
        control = document.createElement("select");
        (setting.choices || []).forEach((choice, index) => {
          const option = document.createElement("option");
          option.value = choice === null ? "" : String(choice);
          option.textContent = setting.choice_labels?.[index] || String(choice);
          control.appendChild(option);
        });
        control.value = setting.value === null || setting.value === undefined ? "" : String(setting.value);
      } else if (setting.kind === "str_list") {
        control = document.createElement("input");
        control.value = (setting.value || []).join(", ");
      } else {
        control = document.createElement("input");
        control.value = setting.value ?? "";
      }
      control.addEventListener("change", async () => {
        let value;
        if (setting.kind === "bool") value = control.checked;
        else if (setting.kind === "str_list") {
          value = control.value.split(",").map((item) => item.trim()).filter(Boolean);
        } else if (setting.kind === "enum") value = control.value === "" ? null : control.value;
        else value = control.value || null;
        try {
          applySession(await api("/api/config", {
            method: "PATCH",
            body: JSON.stringify({ key_path: setting.key_path, value }),
          }));
        } catch (error) {
          setStatus(error.message);
        }
      });
      label.appendChild(control);
      if (setting.note) {
        const note = document.createElement("div");
        note.className = "muted";
        note.textContent = setting.note;
        label.appendChild(note);
      }
      section.appendChild(label);
    });
    body.appendChild(section);
  });
  $("settings-dialog").showModal();
});

window.addEventListener("keydown", async (event) => {
  const shortcuts = state.session?.config?.shortcuts || {};
  const combo = [
    event.ctrlKey || event.metaKey ? "Ctrl" : null,
    event.shiftKey ? "Shift" : null,
    event.key.length === 1 ? event.key.toUpperCase() : event.key,
  ].filter(Boolean).join("+");
  const matches = (value) => {
    const items = Array.isArray(value) ? value : [value];
    return items.filter(Boolean).some((item) => item.replace("Ctrl+", "Ctrl+").toLowerCase() === combo.toLowerCase()
      || item === event.key);
  };
  if (event.key === "Escape") {
    state.draft = null;
    state.aiPoints = [];
    setTool("edit");
    draw();
  } else if (event.key === "Enter" && state.draft) {
    event.preventDefault();
    await finalizeDraft();
  } else if (event.key === "Enter" && state.tool === "ai_points") {
    await runAiPoints();
  } else if (matches(shortcuts.save) || (event.ctrlKey && event.key.toLowerCase() === "s")) {
    event.preventDefault();
    save().catch((error) => setStatus(error.message));
  } else if (matches(shortcuts.undo) || (event.ctrlKey && event.key.toLowerCase() === "z")) {
    event.preventDefault();
    undo();
  } else if (matches(shortcuts.delete_shape) || event.key === "Delete" || event.key === "Backspace") {
    $("btn-delete").click();
  } else if (matches(shortcuts.open_next) || event.key.toLowerCase() === "d") {
    $("btn-next").click();
  } else if (matches(shortcuts.open_prev) || event.key.toLowerCase() === "a") {
    $("btn-prev").click();
  } else if (matches(shortcuts.create_polygon)) setTool("polygon");
  else if (matches(shortcuts.create_rectangle)) setTool("rectangle");
  else if (matches(shortcuts.fit_window)) $("btn-fit").click();
});

window.addEventListener("resize", resizeCanvas);

refreshSession()
  .then(() => {
    resizeCanvas();
    setStatus("Ready");
  })
  .catch((error) => setStatus(error.message));

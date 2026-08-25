import { colorFor, cssColor } from "../annotation/shapes.js";
import { $ } from "../dom.js";
import { state } from "../store.js";
import { dist } from "./hit-test.js";
import { canvas, cssSize, ctx, imageToCanvas } from "./transform.js";

export function drawShape(shape, { selected = false, draft = false } = {}) {
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
    if (["polygon", "oriented_rectangle"].includes(shape.shape_type) && pts.length >= 3 && !draft) {
      ctx.closePath();
    }
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

export function draw() {
  const { width, height } = cssSize();
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.clearRect(0, 0, width, height);
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

export function themeFromConfig(theme) {
  if (theme === "light" || theme === "dark") return theme;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme) {
  document.documentElement.dataset.theme = themeFromConfig(theme);
}

export function setStatus(message) {
  $("status").textContent = message;
}

export function renderChrome() {
  const base = (state.session?.title || "Labelme").replace(/\*+$/, "");
  const dirty = state.editVersion !== state.savedVersion;
  const title = dirty ? `${base}*` : base;
  $("title").textContent = title;
  document.title = title;
  applyTheme(state.session?.config?.color_theme);
}

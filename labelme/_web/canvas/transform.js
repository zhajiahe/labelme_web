import { state } from "../store.js";
import { $ } from "../dom.js";

export const canvas = $("canvas");
export const ctx = canvas.getContext("2d");

export function cssSize() {
  return { width: canvas.clientWidth, height: canvas.clientHeight };
}

export function resizeCanvas() {
  const wrap = canvas.parentElement;
  const dpr = window.devicePixelRatio || 1;
  const width = wrap.clientWidth;
  const height = wrap.clientHeight;
  canvas.width = Math.max(1, Math.round(width * dpr));
  canvas.height = Math.max(1, Math.round(height * dpr));
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

export function imageToCanvas([x, y]) {
  return [x * state.scale + state.offsetX, y * state.scale + state.offsetY];
}

export function canvasToImage([x, y]) {
  return [(x - state.offsetX) / state.scale, (y - state.offsetY) / state.scale];
}

export function clampPoint(point) {
  const allow = state.session?.config?.canvas?.allow_out_of_bounds_points;
  if (allow || !state.image) return point;
  return [
    Math.min(Math.max(point[0], 0), state.image.width),
    Math.min(Math.max(point[1], 0), state.image.height),
  ];
}

export function fitImage() {
  if (!state.image) return;
  const { width, height } = cssSize();
  const pad = 24;
  const sx = (width - pad) / state.image.width;
  const sy = (height - pad) / state.image.height;
  state.scale = Math.max(0.05, Math.min(sx, sy));
  state.offsetX = (width - state.image.width * state.scale) / 2;
  state.offsetY = (height - state.image.height * state.scale) / 2;
  $("zoom").value = String(Math.round(state.scale * 100));
}

export function pointerInfo(event) {
  const rect = canvas.getBoundingClientRect();
  const canvasPoint = [event.clientX - rect.left, event.clientY - rect.top];
  return { canvasPoint, imagePoint: clampPoint(canvasToImage(canvasPoint)) };
}

export function imageToClient(x, y) {
  const rect = canvas.getBoundingClientRect();
  const [cx, cy] = imageToCanvas([x, y]);
  return { x: rect.left + cx, y: rect.top + cy };
}

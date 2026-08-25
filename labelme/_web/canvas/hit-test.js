import { state } from "../store.js";

export function dist(a, b) {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

export function pointInPoly(point, vertices) {
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

export function shapeContains(shape, point) {
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

export function nearestVertex(shape, point, epsilon = 10) {
  let best = null;
  shape.points.forEach((vertex, index) => {
    const d = dist(vertex, point) * state.scale;
    if (d <= epsilon && (best === null || d < best.d)) best = { index, d };
  });
  return best?.index ?? null;
}

export function hitTest(point) {
  for (let i = state.shapes.length - 1; i >= 0; i -= 1) {
    const shape = state.shapes[i];
    const vertex = nearestVertex(shape, point);
    if (vertex !== null) return { kind: "vertex", shape, index: i, vertex };
    if (shapeContains(shape, point)) return { kind: "body", shape, index: i };
  }
  return null;
}

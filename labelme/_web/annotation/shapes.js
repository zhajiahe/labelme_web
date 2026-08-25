import { state } from "../store.js";

export function cloneShapes(shapes) {
  return structuredClone(shapes);
}

export function savePayload(clientVersion) {
  return {
    shapes: cloneShapes(state.shapes),
    flags: { ...state.flags },
    client_version: clientVersion,
  };
}

export function colorFor(label) {
  const colors = state.session?.annotation?.colors || {};
  return colors[label] || [0, 220, 90];
}

export function cssColor(rgb, alpha = 1) {
  return `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})`;
}

export function neededPoints(shapeType) {
  return {
    point: 1,
    line: 2,
    rectangle: 2,
    circle: 2,
    mask: 2,
    polygon: 3,
    linestrip: 2,
    oriented_rectangle: 4,
  }[shapeType] || 1;
}

export function emptyShape(type, point) {
  return {
    label: "",
    points: [point],
    shape_type: type,
    flags: {},
    description: "",
    group_id: null,
    mask: null,
  };
}

export function orientedRectPoints(start, end, mouse) {
  const dx = end[0] - start[0];
  const dy = end[1] - start[1];
  const length = Math.hypot(dx, dy) || 1;
  const px = -dy / length;
  const py = dx / length;
  const dist = (mouse[0] - start[0]) * px + (mouse[1] - start[1]) * py;
  const ox = px * dist;
  const oy = py * dist;
  return [
    [start[0], start[1]],
    [end[0], end[1]],
    [end[0] + ox, end[1] + oy],
    [start[0] + ox, start[1] + oy],
  ];
}

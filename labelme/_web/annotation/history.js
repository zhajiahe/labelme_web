import { cloneShapes } from "./shapes.js";
import { markDirty, state } from "../store.js";

function snapshot() {
  return { shapes: cloneShapes(state.shapes), flags: { ...state.flags } };
}

function applySnapshot(entry) {
  state.shapes = cloneShapes(entry.shapes);
  state.flags = { ...entry.flags };
  state.selected.clear();
}

export function historyLimit() {
  return state.session?.config?.canvas?.num_backups || 10;
}

export function pushHistory() {
  state.history.undo.push(snapshot());
  const limit = historyLimit();
  if (state.history.undo.length > limit) state.history.undo.shift();
  state.history.redo = [];
}

export function undo() {
  if (!state.history.undo.length) return false;
  state.history.redo.push(snapshot());
  applySnapshot(state.history.undo.pop());
  markDirty();
  return true;
}

export function redo() {
  if (!state.history.redo.length) return false;
  state.history.undo.push(snapshot());
  applySnapshot(state.history.redo.pop());
  markDirty();
  return true;
}

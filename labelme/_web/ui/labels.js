import { cssColor, colorFor } from "../annotation/shapes.js";
import { $ } from "../dom.js";
import { markDirty, state } from "../store.js";
import { draw } from "../canvas/renderer.js";

export function renderShapes({ onSelect } = {}) {
  const list = $("shape-list");
  list.innerHTML = "";
  state.shapes.forEach((shape, index) => {
    const item = document.createElement("li");
    item.textContent = `${shape.label || "(unlabeled)"} · ${shape.shape_type}`;
    if (state.selected.has(index)) item.classList.add("selected");
    item.addEventListener("click", () => onSelect?.(index));
    list.appendChild(item);
  });
}

export function renderLabels() {
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

export function renderFlags({ onChange } = {}) {
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
      markDirty();
      onChange?.();
    });
    item.append(box, ` ${name}`);
    list.appendChild(item);
  });
}

export function renderShapeLists({ onSelect, onFlagChange } = {}) {
  renderShapes({ onSelect });
  renderLabels();
  renderFlags({ onChange: onFlagChange });
  draw();
}

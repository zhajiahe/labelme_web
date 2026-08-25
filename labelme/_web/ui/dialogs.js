import { $ } from "../dom.js";
import { isDirty, state } from "../store.js";

export function askLabel(shape) {
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

export function unsavedDialog() {
  return new Promise((resolve) => {
    const dialog = $("unsaved-dialog");
    const onClose = () => {
      dialog.removeEventListener("close", onClose);
      resolve(dialog.returnValue || "cancel");
    };
    dialog.addEventListener("close", onClose);
    dialog.showModal();
  });
}

export async function guardUnsavedChanges({ saveFn } = {}) {
  if (!isDirty()) return "continue";
  if (state.session?.config?.auto_save) {
    try {
      await saveFn();
    } catch (error) {
      return "cancel";
    }
    return isDirty() ? "cancel" : "continue";
  }
  const choice = await unsavedDialog();
  if (choice === "save") {
    try {
      await saveFn();
    } catch {
      return "cancel";
    }
    return isDirty() ? "cancel" : "continue";
  }
  if (choice === "discard") return "discard";
  return "cancel";
}

export function bindBeforeUnload() {
  window.addEventListener("beforeunload", (event) => {
    if (!isDirty()) return;
    event.preventDefault();
    event.returnValue = "";
  });
}

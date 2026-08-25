import { closeSession, fetchImageBlob, getSession, listFiles, navigate, openPath, patchConfig, saveAnnotation, searchFiles, setCurrent } from "./api.js";
import { pushHistory, redo, undo } from "./annotation/history.js";
import { savePayload } from "./annotation/shapes.js";
import { runAiBox, runAiPoints, runAiText, fillAiModels } from "./ai/assist.js";
import { bindCanvas, setTool } from "./canvas/interaction.js";
import { draw, renderChrome, setStatus } from "./canvas/renderer.js";
import { fitImage, imageToClient, resizeCanvas } from "./canvas/transform.js";
import { $ } from "./dom.js";
import { applyConfigPatch, applyCurrent, applyProject, isDirty, markClean, markDirty, state } from "./store.js";
import { bindBeforeUnload, guardUnsavedChanges } from "./ui/dialogs.js";
import { bindFileList, clearFileCache, ensureFileWindow, markCurrent, markHasAnnotation, rememberFiles, renderFileList } from "./ui/files.js";
import { renderShapeLists } from "./ui/labels.js";

let saveChain = Promise.resolve();

function renderCanvasAndLists() {
  renderChrome();
  renderShapeLists({
    onSelect: (index) => {
      state.selected = new Set([index]);
      renderCanvasAndLists();
    },
    onFlagChange: () => maybeAutosave(),
  });
}

function renderFiles() {
  renderFileList({ onOpen: (index) => openIndex(index).catch((error) => setStatus(error.message)) });
}

async function refreshFiles() {
  const page = await listFiles(0, 80);
  rememberFiles(page.files, page.total, page.current_index);
  await ensureFileWindow();
  renderFiles();
}

async function loadImage(index, resetView) {
  const requestId = ++state.imageRequestId;
  const blob = await fetchImageBlob(index);
  if (requestId !== state.imageRequestId) return;
  const url = URL.createObjectURL(blob);
  const image = new Image();
  await new Promise((resolve, reject) => {
    image.onload = resolve;
    image.onerror = reject;
    image.src = url;
  });
  if (requestId !== state.imageRequestId) {
    URL.revokeObjectURL(url);
    return;
  }
  if (state.imageUrl) URL.revokeObjectURL(state.imageUrl);
  state.imageUrl = url;
  state.image = image;
  state.imageIndex = index;
  if (resetView || state.scale === 1) fitImage();
  draw();
}

async function showCurrent(payload, { resetView = false } = {}) {
  applyCurrent(payload);
  fillAiModels(state.session);
  markCurrent(state.currentIndex);
  renderChrome();
  renderCanvasAndLists();
  renderFiles();
  if (payload.annotation) {
    await loadImage(state.currentIndex, resetView);
  } else {
    state.image = null;
    state.imageIndex = null;
    draw();
  }
}

async function save() {
  if (!state.session || state.currentIndex === null || state.currentIndex === undefined) return;
  if (!isDirty() && !state.saving) return;
  const version = state.editVersion;
  const index = state.currentIndex;
  const body = savePayload(version);
  state.saving = true;
  setStatus("Saving…");
  try {
    const result = await saveAnnotation(index, body);
    if (result.client_version === version || version === state.editVersion) {
      markClean(version);
    }
    markHasAnnotation(index, true);
    renderChrome();
    renderFiles();
    setStatus("Saved");
    if (state.session?.config?.auto_save && isDirty()) {
      maybeAutosave();
    }
    return result;
  } catch (error) {
    setStatus(error.message);
    throw error;
  } finally {
    state.saving = false;
  }
}

function enqueueSave() {
  saveChain = saveChain.then(() => save()).catch(() => undefined);
  return saveChain;
}

function maybeAutosave() {
  if (!state.session?.config?.auto_save) {
    renderChrome();
    return;
  }
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(() => enqueueSave(), 400);
}

function onEditorChanged({ lists = false } = {}) {
  if (lists) renderCanvasAndLists();
  else {
    renderChrome();
    draw();
  }
  maybeAutosave();
}

async function withUnsavedGuard(action) {
  const decision = await guardUnsavedChanges({ saveFn: () => enqueueSave() });
  if (decision === "cancel") return;
  await action();
}

async function openIndex(index) {
  if (index === state.currentIndex && state.imageIndex === index) return;
  await withUnsavedGuard(async () => {
    setStatus("Loading…");
    const payload = await setCurrent(index);
    await showCurrent(payload, { resetView: !state.session?.config?.keep_prev_scale });
    setStatus("Ready");
  });
}

async function step(delta) {
  await withUnsavedGuard(async () => {
    setStatus("Loading…");
    const payload = await navigate(delta);
    await showCurrent(payload, { resetView: !state.session?.config?.keep_prev_scale });
    setStatus("Ready");
  });
}

async function openFromPath(path) {
  await withUnsavedGuard(async () => {
    setStatus(`Opening ${path}…`);
    const session = await openPath(path);
    applyProject(session);
    fillAiModels(session);
    clearFileCache();
    await refreshFiles();
    await showCurrent({
      title: session.title,
      current_index: session.current_index,
      file_count: session.file_count,
      dirty: session.dirty,
      file_search: session.file_search,
      file_list_enabled: session.file_list_enabled,
      annotation: session.annotation,
    }, { resetView: true });
    setStatus("Ready");
  });
}

function bindSettings() {
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
            const payload = await patchConfig(setting.key_path, value);
            applyConfigPatch(payload);
            renderChrome();
            if (setting.key_path?.[0] === "auto_save" && value && isDirty()) {
              enqueueSave();
            }
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
}

function bindChrome() {
  $("btn-open").addEventListener("click", () => {
    const path = $("open-path").value.trim();
    if (path) openFromPath(path).catch((error) => setStatus(error.message));
  });
  $("open-path").addEventListener("keydown", (event) => {
    if (event.key === "Enter") $("btn-open").click();
  });
  $("btn-prev").addEventListener("click", () => step(-1).catch((error) => setStatus(error.message)));
  $("btn-next").addEventListener("click", () => step(1).catch((error) => setStatus(error.message)));
  $("btn-save").addEventListener("click", () => enqueueSave());
  $("btn-undo").addEventListener("click", () => {
    if (undo()) onEditorChanged({ lists: true });
  });
  $("btn-redo").addEventListener("click", () => {
    if (redo()) onEditorChanged({ lists: true });
  });
  $("btn-delete").addEventListener("click", () => {
    if (!state.selected.size) return;
    pushHistory();
    state.shapes = state.shapes.filter((_, index) => !state.selected.has(index));
    state.selected.clear();
    markDirty();
    onEditorChanged({ lists: true });
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
  $("file-search").addEventListener("input", async () => {
    try {
      const result = await searchFiles($("file-search").value);
      state.fileTotal = result.file_count;
      if (state.session) state.session.file_search = result.file_search;
      clearFileCache();
      await refreshFiles();
    } catch (error) {
      setStatus(error.message);
    }
  });
  $("btn-ai-text").addEventListener("click", () => {
    runAiText({ onChanged: () => onEditorChanged({ lists: true }) }).catch((error) => setStatus(error.message));
  });
  document.querySelectorAll(".tool").forEach((button) => {
    button.addEventListener("click", () => setTool(button.dataset.tool));
  });
}

function bindKeys() {
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
    const typing = event.target.closest("input, textarea, select");
    if (typing && !event.ctrlKey && !event.metaKey) return;
    if (event.key === "Escape") {
      state.draft = null;
      state.aiPoints = [];
      setTool("edit");
      draw();
    } else if (matches(shortcuts.save) || (event.ctrlKey && event.key.toLowerCase() === "s")) {
      event.preventDefault();
      enqueueSave();
    } else if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "z") {
      event.preventDefault();
      if (redo()) onEditorChanged({ lists: true });
    } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") {
      event.preventDefault();
      if (redo()) onEditorChanged({ lists: true });
    } else if (matches(shortcuts.undo) || (event.ctrlKey && event.key.toLowerCase() === "z")) {
      event.preventDefault();
      if (undo()) onEditorChanged({ lists: true });
    } else if (matches(shortcuts.delete_shape) || event.key === "Delete" || event.key === "Backspace") {
      $("btn-delete").click();
    } else if (matches(shortcuts.open_next) || event.key.toLowerCase() === "d") {
      $("btn-next").click();
    } else if (matches(shortcuts.open_prev) || event.key.toLowerCase() === "a") {
      $("btn-prev").click();
    } else if (matches(shortcuts.close)) {
      event.preventDefault();
      await withUnsavedGuard(async () => {
        const session = await closeSession();
        applyProject(session);
        applyCurrent({
          title: session.title,
          current_index: session.current_index,
          file_count: session.file_count,
          dirty: false,
          file_search: session.file_search,
          file_list_enabled: session.file_list_enabled,
          annotation: session.annotation,
        });
        state.image = null;
        renderChrome();
        renderCanvasAndLists();
        renderFiles();
      });
    } else if (matches(shortcuts.create_polygon)) setTool("polygon");
    else if (matches(shortcuts.create_rectangle)) setTool("rectangle");
    else if (matches(shortcuts.fit_window)) $("btn-fit").click();
  });
}

function exposeTestHooks() {
  window.__labelme = {
    getState() {
      return {
        shapes: state.shapes,
        flags: state.flags,
        dirty: isDirty(),
        editVersion: state.editVersion,
        savedVersion: state.savedVersion,
        currentIndex: state.currentIndex,
        imageIndex: state.imageIndex,
        scale: state.scale,
        offsetX: state.offsetX,
        offsetY: state.offsetY,
        tool: state.tool,
        imageSize: state.image ? { width: state.image.width, height: state.image.height } : null,
      };
    },
    imageToClient,
    setTool,
    draw,
    replaceShapes(shapes) {
      state.shapes = shapes;
      markDirty();
      draw();
    },
  };
}

bindCanvas({
  onChanged: onEditorChanged,
  onAiBox: (box) => runAiBox(box, { onChanged: () => onEditorChanged({ lists: true }) }),
  runAiPoints: () => runAiPoints({ onChanged: () => onEditorChanged({ lists: true }) }),
});
bindFileList({ onOpen: (index) => openIndex(index).catch((error) => setStatus(error.message)) });
bindChrome();
bindSettings();
bindKeys();
bindBeforeUnload();
exposeTestHooks();
window.addEventListener("resize", () => {
  resizeCanvas();
  draw();
});

getSession()
  .then(async (session) => {
    applyProject(session);
    fillAiModels(session);
    resizeCanvas();
    await refreshFiles();
    await showCurrent({
      title: session.title,
      current_index: session.current_index,
      file_count: session.file_count,
      dirty: session.dirty,
      file_search: session.file_search,
      file_list_enabled: session.file_list_enabled,
      annotation: session.annotation,
    }, { resetView: true });
    setStatus("Ready");
  })
  .catch((error) => setStatus(error.message));

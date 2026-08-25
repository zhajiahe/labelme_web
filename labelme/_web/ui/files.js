import { listFiles } from "../api.js";
import { $ } from "../dom.js";
import { state } from "../store.js";

const ROW = 28;
const OVERSCAN = 8;
const fileCache = new Map();

export function rememberFiles(files, total, currentIndex) {
  if (typeof total === "number") state.fileTotal = total;
  if (typeof currentIndex === "number") state.currentIndex = currentIndex;
  (files || []).forEach((file) => {
    fileCache.set(file.index, file);
  });
}

export function clearFileCache() {
  fileCache.clear();
}

export function markCurrent(index) {
  state.currentIndex = index;
  fileCache.forEach((file) => {
    file.current = file.index === index;
  });
}

export function markHasAnnotation(index, hasAnnotation = true) {
  const file = fileCache.get(index);
  if (file) file.has_annotation = hasAnnotation;
}

function missingRange(start, end) {
  for (let index = start; index < end; index += 1) {
    if (!fileCache.has(index)) return index;
  }
  return null;
}

export async function ensureFileWindow() {
  const viewport = $("file-list-viewport");
  if (!viewport || !state.fileTotal) return;
  const start = Math.max(0, Math.floor(viewport.scrollTop / ROW) - OVERSCAN);
  const visible = Math.ceil(viewport.clientHeight / ROW) + OVERSCAN * 2;
  const end = Math.min(state.fileTotal, start + visible);
  const hole = missingRange(start, end);
  if (hole !== null) {
    const page = await listFiles(hole, 80);
    rememberFiles(page.files, page.total, page.current_index);
  }
}

export function renderFileList({ onOpen } = {}) {
  const viewport = $("file-list-viewport");
  const spacer = $("file-list-spacer");
  const list = $("file-list");
  if (!viewport || !list || !spacer) return;
  spacer.style.height = `${state.fileTotal * ROW}px`;
  const start = Math.max(0, Math.floor(viewport.scrollTop / ROW) - OVERSCAN);
  const visible = Math.ceil(Math.max(viewport.clientHeight, ROW) / ROW) + OVERSCAN * 2;
  const end = Math.min(state.fileTotal, start + visible);
  list.style.transform = `translateY(${start * ROW}px)`;
  list.innerHTML = "";
  for (let index = start; index < end; index += 1) {
    const file = fileCache.get(index);
    const item = document.createElement("li");
    item.style.height = `${ROW}px`;
    if (!file) {
      item.textContent = "…";
      item.className = "placeholder";
    } else {
      item.textContent = `${file.has_annotation ? "●" : "○"} ${file.name}`;
      item.title = file.path;
      item.className = file.index === state.currentIndex ? "current" : "";
      item.addEventListener("click", () => onOpen?.(file.index));
    }
    list.appendChild(item);
  }
}

export function bindFileList({ onOpen } = {}) {
  const viewport = $("file-list-viewport");
  if (!viewport) return;
  let ticking = false;
  viewport.addEventListener("scroll", () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(async () => {
      ticking = false;
      try {
        await ensureFileWindow();
      } catch {
        // Keep the last rendered window if a page fetch fails.
      }
      renderFileList({ onOpen });
    });
  });
}

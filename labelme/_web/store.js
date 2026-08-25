export const state = {
  session: null,
  fileTotal: 0,
  currentIndex: null,
  image: null,
  imageUrl: null,
  imageIndex: null,
  imageRequestId: 0,
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
  lastLabel: "",
  aiPoints: [],
  editVersion: 0,
  savedVersion: 0,
  saving: false,
  saveTimer: null,
  history: { undo: [], redo: [] },
};

export function isDirty() {
  return state.editVersion !== state.savedVersion;
}

export function markDirty() {
  state.editVersion += 1;
}

export function markClean(version) {
  if (version === state.editVersion) {
    state.savedVersion = version;
  }
}

export function resetEditState() {
  state.editVersion = 0;
  state.savedVersion = 0;
  state.selected = new Set();
  state.draft = null;
  state.aiPoints = [];
  state.hover = null;
  state.drag = null;
  state.history = { undo: [], redo: [] };
}

export function applyProject(session) {
  state.session = session;
  state.fileTotal = session.file_count || 0;
  if (typeof session.current_index === "number") {
    state.currentIndex = session.current_index;
  }
}

export function applyConfigPatch(payload) {
  if (!state.session) return;
  state.session.config = payload.config;
  state.session.settings = payload.settings;
  state.session.settings_editable = payload.settings_editable;
}

export function applyAnnotation(annotation, { index = null } = {}) {
  state.shapes = annotation ? structuredClone(annotation.shapes || []) : [];
  state.flags = { ...(annotation?.flags || {}) };
  if (index !== null && index !== undefined) {
    state.currentIndex = index;
  } else if (typeof annotation?.index === "number") {
    state.currentIndex = annotation.index;
  }
  if (state.session) {
    state.session.annotation = annotation;
  }
  resetEditState();
}

export function applyCurrent(payload) {
  if (!state.session) {
    state.session = {};
  }
  state.session.title = payload.title;
  state.session.dirty = payload.dirty;
  state.session.file_search = payload.file_search;
  state.session.file_list_enabled = payload.file_list_enabled;
  if (typeof payload.file_count === "number") {
    state.fileTotal = payload.file_count;
    state.session.file_count = payload.file_count;
  }
  if (typeof payload.current_index === "number") {
    state.currentIndex = payload.current_index;
    state.session.current_index = payload.current_index;
  } else if (payload.annotation) {
    state.currentIndex = 0;
    state.session.current_index = 0;
  } else {
    state.currentIndex = null;
    state.session.current_index = null;
  }
  applyAnnotation(payload.annotation, { index: state.currentIndex });
}

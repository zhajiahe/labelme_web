const TOKEN_KEY = "labelme_token";

function readToken() {
  const params = new URLSearchParams(window.location.search);
  const fromQuery = params.get("token");
  if (fromQuery) {
    sessionStorage.setItem(TOKEN_KEY, fromQuery);
    params.delete("token");
    const query = params.toString();
    const next = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
    window.history.replaceState({}, "", next);
    return fromQuery;
  }
  return sessionStorage.getItem(TOKEN_KEY);
}

const accessToken = readToken();

export function authHeaders() {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

export async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...authHeaders(),
    ...(options.headers || {}),
  };
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      detail = await response.text();
    }
    throw new Error(detail);
  }
  if (response.headers.get("content-type")?.includes("application/json")) {
    return response.json();
  }
  return response;
}

export function getSession() {
  return api("/api/session");
}

export function listFiles(offset = 0, limit = 80) {
  return api(`/api/files?offset=${offset}&limit=${limit}`);
}

export function openPath(path) {
  return api("/api/session/open", { method: "POST", body: JSON.stringify({ path }) });
}

export function navigate(delta) {
  return api("/api/session/navigate", { method: "POST", body: JSON.stringify({ delta }) });
}

export function setCurrent(index) {
  return api("/api/session/current", { method: "POST", body: JSON.stringify({ index }) });
}

export function closeSession() {
  return api("/api/session/close", { method: "POST" });
}

export function searchFiles(query) {
  return api("/api/session/search", { method: "POST", body: JSON.stringify({ query }) });
}

export function saveAnnotation(index, payload) {
  return api(`/api/files/${index}/annotation`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function getAnnotation(index) {
  return api(`/api/files/${index}/annotation`);
}

export function patchConfig(keyPath, value) {
  return api("/api/config", {
    method: "PATCH",
    body: JSON.stringify({ key_path: keyPath, value }),
  });
}

export function aiAssist(body) {
  return api("/api/ai/assist", { method: "POST", body: JSON.stringify(body) });
}

export function aiText(body) {
  return api("/api/ai/text", { method: "POST", body: JSON.stringify(body) });
}

export async function fetchImageBlob(index, signal) {
  const response = await fetch(`/api/files/${index}/image`, {
    headers: authHeaders(),
    signal,
  });
  if (!response.ok) throw new Error("Failed to load image");
  return response.blob();
}

async function api(path, options = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text}`);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

const apiGet = (p) => api(p);
const apiPost = (p, body) => api(p, { method: "POST", body: JSON.stringify(body || {}) });
const apiPatch = (p, body) => api(p, { method: "PATCH", body: JSON.stringify(body || {}) });

function escapeHtml(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
  }[c]));
}

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

const VOICES = [
  { value: "sage", label: "The Sage" },
  { value: "bookseller", label: "The Bookseller" },
  { value: "provocateur", label: "The Provocateur" },
  { value: "companion", label: "The Companion" },
];

const READ_STATUSES = ["want_to_read", "reading", "read", "abandoned"];
const SUG_STATUSES = ["suggested", "purchased", "reading", "read", "dismissed"];

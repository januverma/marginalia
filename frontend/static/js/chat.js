let currentSessionId = null;

const $ = (id) => document.getElementById(id);

const PROMPT_SEEDS = [
  "Something that feels like walking through rain in a foreign city",
  "A book that will change how I think about power",
  "I just finished a long novel — something short and perfect",
  "The best book from the last five years I probably haven't heard of",
  "Something from a literary tradition I know nothing about",
];

function renderVoiceOptions(current) {
  const sel = $("voice-select");
  sel.innerHTML = VOICES.map(
    (v) => `<option value="${v.value}" ${v.value === current ? "selected" : ""}>${v.label}</option>`
  ).join("");
}

async function loadProfile() {
  const p = await apiGet("/api/profile");
  renderVoiceOptions(p.voice);
  $("search-toggle").checked = p.web_search_enabled !== false;
}

async function changeVoice(voice) {
  await apiPatch("/api/profile", { voice });
}

async function changeSearch(enabled) {
  await apiPatch("/api/profile", { web_search_enabled: enabled });
}

async function loadSessions() {
  const sessions = await apiGet("/api/sessions");
  const list = $("sessions-list");
  list.innerHTML = "";
  sessions.forEach((s) => {
    const div = document.createElement("div");
    div.className = "session-item" + (s.id === currentSessionId ? " active" : "");
    const label = s.title || "Untitled";
    div.innerHTML = `
      <div class="session-row">
        <div class="session-info">
          <div class="session-title">${escapeHtml(label)}</div>
          <div class="date">${formatDate(s.created_at)} · ${s.message_count} ${s.message_count === 1 ? "msg" : "msgs"}</div>
        </div>
        <button class="session-delete" aria-label="Delete conversation" title="Delete">×</button>
      </div>
    `;
    div.querySelector(".session-info").onclick = () => loadSession(s.id);
    div.querySelector(".session-delete").onclick = (e) => {
      e.stopPropagation();
      deleteSession(s.id, label);
    };
    list.appendChild(div);
  });

  // No auto-select. Landing on / shows the welcome state until the user picks a session.
  if (!currentSessionId) {
    renderMessages([]);
  }
}

async function deleteSession(id, label) {
  if (!confirm(`Delete this conversation?\n\n"${label}"\n\nMessages will be removed. Books in your library are kept.`)) return;
  await api(`/api/sessions/${id}`, { method: "DELETE" });
  if (currentSessionId === id) {
    currentSessionId = null;
    renderMessages([]);
  }
  loadSessions();
}

async function loadSession(id) {
  const session = await apiGet(`/api/sessions/${id}`);
  currentSessionId = id;
  renderMessages(session.messages);
  loadSessions();
}

function renderWelcome() {
  const container = $("messages");
  container.innerHTML = `
    <div class="welcome">
      <div class="big-monogram" aria-hidden="true">M</div>
      <h2>Marginalia</h2>
      <p class="subtitle">Your private librarian. Describe a feeling, a question, a mood — and receive books worth reading, not just books you'll like.</p>
      <div id="librarian-prompt-slot"></div>
      <p class="prompt-label">Try asking</p>
      <div class="prompt-grid">
        ${PROMPT_SEEDS.map((p) => `<button class="prompt-chip">${escapeHtml(p)}</button>`).join("")}
      </div>
    </div>
  `;
  container.querySelectorAll(".prompt-chip").forEach((chip) => {
    chip.onclick = () => {
      const input = $("message-input");
      input.value = chip.textContent;
      autoResize(input);
      input.focus();
    };
  });
  loadLibrarianPrompt();
}

async function loadLibrarianPrompt() {
  try {
    const p = await apiGet("/api/librarian-prompts/pending");
    if (!p) return;
    const slot = $("librarian-prompt-slot");
    if (!slot) return;
    slot.innerHTML = `
      <div class="librarian-prompt-card" data-id="${p.id}">
        <div class="lp-label">The librarian has something to ask you</div>
        <div class="lp-question">${escapeHtml(p.question)}</div>
        <div class="lp-actions">
          <button class="lp-reply">Reply</button>
          <button class="lp-dismiss secondary">Not now</button>
        </div>
      </div>
    `;
    slot.querySelector(".lp-reply").onclick = () => answerLibrarianPrompt(p.id);
    slot.querySelector(".lp-dismiss").onclick = () => dismissLibrarianPrompt(p.id);
  } catch (e) {
    // Silent — the librarian's prompt is purely additive
    console.warn("[loadLibrarianPrompt]", e);
  }
}

async function answerLibrarianPrompt(id) {
  const result = await apiPost(`/api/librarian-prompts/${id}/start`, {});
  // Navigate to the freshly-created session — chat.js will load it on init.
  window.location.href = `/?session=${result.session_id}`;
}

async function dismissLibrarianPrompt(id) {
  await apiPost(`/api/librarian-prompts/${id}/dismiss`, {});
  const slot = $("librarian-prompt-slot");
  if (slot) slot.innerHTML = "";
}

function renderMessages(messages) {
  const container = $("messages");
  if (messages.length === 0) {
    renderWelcome();
    return;
  }
  container.innerHTML = "";
  messages.forEach((m) => container.appendChild(messageNode(m.role, m.content)));
  scrollToBottom();
}

function messageNode(role, content, { streaming = false } = {}) {
  const div = document.createElement("div");
  div.className = `message ${role}` + (streaming ? " streaming" : "");
  const body = role === "assistant" ? renderMarkdown(content) : escapeHtml(content).replace(/\n/g, "<br>");
  div.innerHTML = `<div class="role visually-hidden">${role === "user" ? "You" : "Librarian"}</div><div class="content">${body}</div>`;
  return div;
}

function scrollToBottom() {
  const c = $("messages");
  c.scrollTop = c.scrollHeight;
}

function autoResize(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 140) + "px";
}

function newSession() {
  // Lazy: don't create a Session row until the user sends their first message.
  currentSessionId = null;
  renderMessages([]);
  document.querySelectorAll(".session-item.active").forEach(el => el.classList.remove("active"));
}

async function sendMessage() {
  const input = $("message-input");
  const text = input.value.trim();
  if (!text) return;

  // Lazily create a session on first message
  if (!currentSessionId) {
    const s = await apiPost("/api/sessions", {});
    currentSessionId = s.id;
  }

  const container = $("messages");
  const welcome = container.querySelector(".welcome");
  if (welcome) container.innerHTML = "";

  container.appendChild(messageNode("user", text));
  const assistantNode = messageNode("assistant", "", { streaming: true });
  const contentEl = assistantNode.querySelector(".content");
  contentEl.innerHTML = '<span class="typing-dots"><span></span><span></span><span></span></span>';
  container.appendChild(assistantNode);
  scrollToBottom();

  input.value = "";
  autoResize(input);
  input.disabled = true;
  $("send-btn").disabled = true;

  try {
    await streamChat(currentSessionId, text, contentEl, assistantNode);
  } catch (e) {
    contentEl.innerHTML = `<span class="error">Error: ${escapeHtml(e.message)}</span>`;
  } finally {
    input.disabled = false;
    $("send-btn").disabled = false;
    assistantNode.classList.remove("streaming");
    input.focus();
    loadSessions();
  }
}

function thinkingHtml(label) {
  const status = label
    ? `<div class="search-status"><span class="search-icon">⌕</span> ${escapeHtml(label)}</div>`
    : "";
  return `${status}<span class="typing-dots"><span></span><span></span><span></span></span>`;
}

async function streamChat(sessionId, message, contentEl, wrapperEl) {
  const resp = await fetch(`/api/chat/${sessionId}/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!resp.ok) throw new Error(`${resp.status}`);

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let accumulated = "";
  let mode = "thinking"; // thinking | searching | streaming

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const parts = buffer.split("\n\n");
    buffer = parts.pop();

    for (const part of parts) {
      if (!part.startsWith("data: ")) continue;
      let event;
      try {
        event = JSON.parse(part.slice(6));
      } catch {
        continue;
      }

      if (event.type === "status") {
        if (mode !== "streaming") {
          if (event.message) {
            mode = "searching";
            contentEl.innerHTML = thinkingHtml(event.message);
          } else {
            mode = "thinking";
            contentEl.innerHTML = thinkingHtml("");
          }
        }
      } else if (event.type === "delta") {
        if (mode !== "streaming") {
          contentEl.innerHTML = "";
          mode = "streaming";
        }
        accumulated += event.text;
        contentEl.innerHTML = renderMarkdown(accumulated);
        scrollToBottom();
      } else if (event.type === "done") {
        contentEl.innerHTML = renderMarkdown(event.clean || accumulated);
        if (event.tracked) {
          const badge = document.createElement("div");
          badge.className = "tracked-badge";
          badge.textContent = `${event.tracked} book${event.tracked === 1 ? "" : "s"} tracked`;
          wrapperEl.appendChild(badge);
        }
      } else if (event.type === "error") {
        throw new Error(event.message || "stream error");
      }
    }
  }
}

$("new-session-btn").onclick = newSession;
$("send-btn").onclick = sendMessage;

const messageInput = $("message-input");
messageInput.addEventListener("input", () => autoResize(messageInput));
messageInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});
$("voice-select").addEventListener("change", (e) => changeVoice(e.target.value));
$("search-toggle").addEventListener("change", (e) => changeSearch(e.target.checked));

loadProfile().then(() => {
  const params = new URLSearchParams(window.location.search);
  const sid = parseInt(params.get("session") || "0", 10);
  if (sid) {
    currentSessionId = sid;
    loadSession(sid);
  } else {
    loadSessions();
  }
});

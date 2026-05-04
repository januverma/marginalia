/*
 * Command-palette search. Self-installing — included on every page, injects its
 * own overlay markup and a trigger button, binds ⌘K / Ctrl+K.
 */
(function () {
  let overlay, input, resultsEl, debounceTimer;
  let lastQuery = "";

  function injectOverlay() {
    overlay = document.createElement("div");
    overlay.id = "search-overlay";
    overlay.className = "search-overlay hidden";
    overlay.innerHTML = `
      <div class="search-card" role="dialog" aria-label="Search">
        <div class="search-input-row">
          <span class="search-icon" aria-hidden="true">⌕</span>
          <input id="search-input" type="text" placeholder="Search messages, notes, passages…" autocomplete="off" spellcheck="false">
          <span class="search-hint">Esc</span>
        </div>
        <div id="search-results" class="search-results"></div>
      </div>
    `;
    document.body.appendChild(overlay);
    input = overlay.querySelector("#search-input");
    resultsEl = overlay.querySelector("#search-results");

    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) close();
    });
    input.addEventListener("input", onInput);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Escape") close();
    });
  }

  function injectTrigger() {
    const header = document.querySelector("header");
    if (!header) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "search-trigger";
    btn.setAttribute("aria-label", "Search");
    btn.title = "Search (⌘K)";
    btn.innerHTML = `<span aria-hidden="true">⌕</span><span class="kbd">⌘K</span>`;
    btn.onclick = open;
    // Insert before the voice-switcher if present, otherwise at the end
    const voice = header.querySelector(".voice-switcher");
    if (voice) header.insertBefore(btn, voice);
    else header.appendChild(btn);
  }

  function open() {
    overlay.classList.remove("hidden");
    setTimeout(() => input.focus(), 0);
  }

  function close() {
    overlay.classList.add("hidden");
    input.value = "";
    resultsEl.innerHTML = "";
    lastQuery = "";
  }

  function onInput() {
    clearTimeout(debounceTimer);
    const q = input.value.trim();
    if (!q) {
      resultsEl.innerHTML = `<div class="search-empty">Type to search across messages, notes, and passages.</div>`;
      lastQuery = "";
      return;
    }
    debounceTimer = setTimeout(() => runSearch(q), 200);
  }

  async function runSearch(q) {
    if (q === lastQuery) return;
    lastQuery = q;
    resultsEl.innerHTML = `<div class="search-empty">Searching…</div>`;
    try {
      const data = await apiGet(`/api/search?q=${encodeURIComponent(q)}`);
      if (q !== lastQuery) return;
      render(data);
    } catch (e) {
      resultsEl.innerHTML = `<div class="search-empty error">Error: ${escapeHtml(e.message)}</div>`;
    }
  }

  function render(data) {
    const total = data.messages.length + data.notes.length + data.quotes.length;
    if (!total) {
      resultsEl.innerHTML = `<div class="search-empty">No matches.</div>`;
      return;
    }
    const sections = [];
    if (data.messages.length) sections.push(renderSection("Conversations", data.messages, renderMessage));
    if (data.notes.length)    sections.push(renderSection("Notes", data.notes, renderNote));
    if (data.quotes.length)   sections.push(renderSection("Passages", data.quotes, renderQuote));
    resultsEl.innerHTML = sections.join("");

    resultsEl.querySelectorAll(".search-result").forEach((el) => {
      el.addEventListener("click", () => {
        const href = el.dataset.href;
        if (href) window.location.href = href;
      });
    });
  }

  function renderSection(label, items, fn) {
    return `
      <div class="search-section">
        <div class="search-section-label">${label}</div>
        ${items.map(fn).join("")}
      </div>
    `;
  }

  function renderMessage(m) {
    const who = m.role === "user" ? "You" : "Librarian";
    return `
      <a class="search-result" data-href="/?session=${m.session_id}">
        <div class="result-icon">${m.role === "user" ? "›" : "✎"}</div>
        <div class="result-body">
          <div class="result-header"><span class="result-context">${who}</span><span class="result-date">${formatDate(m.created_at)}</span></div>
          <div class="result-snippet">${m.snippet}</div>
        </div>
      </a>
    `;
  }

  function renderNote(n) {
    return `
      <a class="search-result" data-href="/library?book=${n.book_id}">
        <div class="result-icon">✎</div>
        <div class="result-body">
          <div class="result-header"><span class="result-context">${escapeHtml(n.book_title || "Note")}</span><span class="result-date">${formatDate(n.created_at)}</span></div>
          <div class="result-snippet">${n.snippet}</div>
        </div>
      </a>
    `;
  }

  function renderQuote(q) {
    const ctx = (q.book_title || "Passage") + (q.page ? ` · p.${q.page}` : "");
    return `
      <a class="search-result" data-href="/library?book=${q.book_id}">
        <div class="result-icon">”</div>
        <div class="result-body">
          <div class="result-header"><span class="result-context">${escapeHtml(ctx)}</span><span class="result-date">${formatDate(q.created_at)}</span></div>
          <div class="result-snippet">${q.snippet}</div>
        </div>
      </a>
    `;
  }

  // Global ⌘K / Ctrl+K
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      if (!overlay) return;
      if (overlay.classList.contains("hidden")) open();
      else close();
    }
  });

  function init() {
    injectOverlay();
    injectTrigger();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

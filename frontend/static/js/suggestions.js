const $ = (id) => document.getElementById(id);

async function loadSuggestions() {
  const status = $("status-filter").value;
  const path = status ? `/api/suggestions?status=${status}` : "/api/suggestions";
  const sugs = await apiGet(path);

  const wrap = $("suggestions-list");
  wrap.innerHTML = "";

  if (sugs.length === 0) {
    const msg = status === "suggested"
      ? `<p>No pending suggestions</p><p>Chat with the librarian to receive new recommendations.</p>`
      : `<p>Nothing here</p><p>Try a different filter.</p>`;
    wrap.innerHTML = `<div class="empty">${msg}</div>`;
    return;
  }

  sugs.forEach((s) => wrap.appendChild(renderSuggestionCard(s)));
}

const VOICE_LABELS = {
  sage: "The Sage",
  bookseller: "The Bookseller",
  provocateur: "The Provocateur",
  companion: "The Companion",
};

function renderSuggestionCard(s) {
  const card = document.createElement("div");
  card.className = "suggestion-card" + (s.status === "dismissed" ? " dismissed" : "");

  const cover = s.book.cover_url
    ? `<img src="${escapeHtml(s.book.cover_url)}" alt="" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
       <div class="cover-fallback" style="display:none">${escapeHtml(s.book.title)}</div>`
    : `<div class="cover-fallback">${escapeHtml(s.book.title)}</div>`;

  const voiceLabel = s.voice ? VOICE_LABELS[s.voice] || s.voice : null;
  const meta = [
    s.book.pub_year ? `${s.book.pub_year}` : null,
    `by ${escapeHtml(s.book.author)}`,
  ].filter(Boolean).join(" · ");

  const provenance = [
    voiceLabel ? `Suggested by <strong>${escapeHtml(voiceLabel)}</strong>` : "Suggested",
    formatDate(s.suggested_at),
  ].join(" · ");

  let actions = "";
  if (s.status === "suggested") {
    actions = `
      <button class="small add-btn">Add to library</button>
      <button class="small secondary dismiss-btn">Dismiss</button>
    `;
  } else if (s.status === "dismissed") {
    actions = `<button class="small secondary restore-btn">Restore</button>`;
  } else {
    actions = `<span class="reason">In library</span>`;
  }

  card.innerHTML = `
    <div class="cover-sm">${cover}</div>
    <div class="info">
      <div class="title">${escapeHtml(s.book.title)}</div>
      <div class="meta">${meta}</div>
      <div class="provenance">${provenance}</div>
      ${s.reason_given ? `<div class="reason-text">"${escapeHtml(s.reason_given)}"</div>` : ""}
      <div class="actions">${actions}</div>
    </div>
  `;

  const addBtn = card.querySelector(".add-btn");
  if (addBtn) addBtn.onclick = async () => {
    addBtn.disabled = true;
    addBtn.textContent = "Adding…";
    await apiPost(`/api/suggestions/${s.id}/add-to-library`, {});
    loadSuggestions();
  };

  const dismissBtn = card.querySelector(".dismiss-btn");
  if (dismissBtn) dismissBtn.onclick = async () => {
    await apiPatch(`/api/suggestions/${s.id}`, { status: "dismissed" });
    loadSuggestions();
  };

  const restoreBtn = card.querySelector(".restore-btn");
  if (restoreBtn) restoreBtn.onclick = async () => {
    await apiPatch(`/api/suggestions/${s.id}`, { status: "suggested" });
    loadSuggestions();
  };

  return card;
}

$("status-filter").addEventListener("change", loadSuggestions);
loadSuggestions();

const $ = (id) => document.getElementById(id);

const SHELF_ORDER = [
  { key: "reading", label: "Currently reading" },
  { key: "want_to_read", label: "Want to read" },
  { key: "read", label: "Read" },
  { key: "abandoned", label: "Abandoned" },
];

const STATUS_LABELS = {
  reading: "Reading",
  want_to_read: "Want to read",
  read: "Read",
  abandoned: "Abandoned",
};

let currentBookId = null;

async function loadLibrary() {
  const lib = await apiGet("/api/library");
  const wrap = $("shelves");
  wrap.innerHTML = "";

  const total = SHELF_ORDER.reduce((s, sh) => s + (lib[sh.key] || []).length, 0);
  if (total === 0) {
    wrap.innerHTML = `
      <div class="empty">
        <p>Your shelves are empty</p>
        <p>Add a book above, or accept a suggestion from the librarian.</p>
      </div>`;
    return;
  }

  for (const shelf of SHELF_ORDER) {
    const items = lib[shelf.key] || [];
    if (items.length === 0) continue;
    const section = document.createElement("section");
    section.className = "shelf";
    section.innerHTML = `
      <div class="shelf-header">
        <h3>${shelf.label}</h3>
        <span class="shelf-count">${items.length} ${items.length === 1 ? "book" : "books"}</span>
      </div>
      <div class="book-grid"></div>
    `;
    const grid = section.querySelector(".book-grid");
    items.forEach((b) => grid.appendChild(renderBookCard(b)));
    wrap.appendChild(section);
  }
}

function renderBookCard(b) {
  const card = document.createElement("div");
  card.className = "book-card";
  card.dataset.bookId = b.book_id;

  const cover = b.cover_url
    ? `<img src="${escapeHtml(b.cover_url)}" alt="" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
       <div class="cover-fallback" style="display:none">${escapeHtml(b.title)}</div>`
    : `<div class="cover-fallback">${escapeHtml(b.title)}</div>`;

  const stars = b.rating ? "★".repeat(b.rating) + "☆".repeat(5 - b.rating) : "";

  card.innerHTML = `
    <div class="cover-wrap">${cover}</div>
    <div class="book-info">
      <div class="book-title-card">${escapeHtml(b.title)}</div>
      <div class="book-author">${escapeHtml(b.author)}</div>
      ${stars ? `<div class="book-rating">${stars}</div>` : ""}
    </div>
  `;
  card.onclick = () => openBookDetail(b.book_id);
  return card;
}

async function openBookDetail(bookId) {
  currentBookId = bookId;
  const book = await apiGet(`/api/books/${bookId}`);
  const modal = $("book-modal");
  $("modal-content").innerHTML = renderBookDetail(book);
  modal.classList.remove("hidden");
  wireDetailHandlers(book);
}

function renderBookDetail(book) {
  const log = (book.reading_log || [])[0]; // most recent
  const cover = book.cover_url
    ? `<img src="${escapeHtml(book.cover_url)}" alt="">`
    : `<div class="cover-fallback">${escapeHtml(book.title)}</div>`;

  const statusOpts = ["want_to_read", "reading", "read", "abandoned"]
    .map((s) => `<option value="${s}" ${log && log.status === s ? "selected" : ""}>${STATUS_LABELS[s]}</option>`)
    .join("");
  const ratingOpts = [["", "—"], [1, "★"], [2, "★★"], [3, "★★★"], [4, "★★★★"], [5, "★★★★★"]]
    .map(([v, l]) => `<option value="${v}" ${log && log.rating == v ? "selected" : ""}>${l}</option>`)
    .join("");

  const notesHtml = (book.notes || []).length
    ? book.notes.map((n) => `
        <div class="note">
          <div class="note-date">${formatDate(n.created_at)}</div>
          <div>${escapeHtml(n.content)}</div>
        </div>`).join("")
    : `<div class="reason">No notes yet.</div>`;

  const quotesHtml = (book.quotes || []).length
    ? book.quotes.map((q) => `
        <div class="quote" data-quote-id="${q.id}">
          <button class="quote-delete" aria-label="Delete">×</button>
          <div class="quote-content">${escapeHtml(q.content)}</div>
          <div class="quote-meta">${q.page ? `p.&nbsp;${q.page} · ` : ""}${formatDate(q.created_at)}</div>
        </div>`).join("")
    : `<div class="reason">No passages yet.</div>`;

  return `
    <div class="book-detail">
      <div class="cover-large">${cover}</div>
      <div>
        <div class="title-row">
          <h2 id="detail-title-text">${escapeHtml(book.title)}</h2>
          <button id="detail-edit-btn" class="secondary small" title="Edit title, author, year">Edit</button>
        </div>
        <div class="author-line" id="detail-author-text">by ${escapeHtml(book.author)}${book.pub_year ? ` &middot; ${book.pub_year}` : ""}</div>

        <div id="detail-edit-form" class="book-edit-form" style="display: none;">
          <div class="field-row">
            <div class="field" style="grid-column: span 2;">
              <label>Title</label>
              <input type="text" id="edit-title" value="${escapeHtml(book.title)}">
            </div>
          </div>
          <div class="field-row">
            <div class="field">
              <label>Author</label>
              <input type="text" id="edit-author" value="${escapeHtml(book.author)}">
            </div>
            <div class="field">
              <label>Year</label>
              <input type="number" id="edit-year" value="${book.pub_year || ''}" min="1" max="2200">
            </div>
          </div>
          <div class="edit-actions">
            <button id="edit-save-btn" class="small">Save</button>
            <button id="edit-cancel-btn" class="secondary small">Cancel</button>
            <span class="reason edit-hint">Changing title or author re-fetches metadata from Google Books.</span>
          </div>
        </div>


        ${log ? `
          <div class="field-row">
            <div class="field">
              <label>Shelf</label>
              <select id="detail-status">${statusOpts}</select>
            </div>
            <div class="field">
              <label>Rating</label>
              <select id="detail-rating">${ratingOpts}</select>
            </div>
          </div>
          <div class="field-row">
            <div class="field">
              <label>Started</label>
              <input type="date" id="detail-started" value="${log.started_at ? log.started_at.slice(0, 10) : ''}">
            </div>
            <div class="field">
              <label>Finished</label>
              <input type="date" id="detail-finished" value="${log.finished_at ? log.finished_at.slice(0, 10) : ''}">
            </div>
          </div>
        ` : `
          <div class="field">
            <label>Add to library</label>
            <select id="detail-add-status">
              <option value="">Select shelf…</option>
              ${["want_to_read", "reading", "read", "abandoned"].map(s => `<option value="${s}">${STATUS_LABELS[s]}</option>`).join("")}
            </select>
          </div>
        `}

        <div class="field">
          <label>Notes</label>
          <div class="notes-list">${notesHtml}</div>
          <div class="add-note">
            <textarea id="detail-note-input" placeholder="Add a note…"></textarea>
            <button id="detail-note-add" class="small">Save</button>
          </div>
        </div>

        <div class="field">
          <label>Passages</label>
          <div class="quotes-list">${quotesHtml}</div>
          <div class="add-quote">
            <textarea id="detail-quote-input" placeholder="Paste a passage from the book…"></textarea>
            <div class="quote-row">
              <input type="number" id="detail-quote-page" placeholder="Page" class="inline" min="1">
              <button id="detail-quote-add" class="small">Save passage</button>
            </div>
          </div>
        </div>

        ${book.buy_link ? `<a class="buy-link" href="${escapeHtml(book.buy_link)}" target="_blank" rel="noopener">View on Google Books →</a>` : ""}
      </div>
    </div>
  `;
}

function wireDetailHandlers(book) {
  const log = (book.reading_log || [])[0];

  const statusSel = $("detail-status");
  if (statusSel) {
    statusSel.onchange = async (e) => {
      await apiPatch(`/api/reading-log/${log.id}`, { status: e.target.value });
      loadLibrary();
    };
  }

  const ratingSel = $("detail-rating");
  if (ratingSel) {
    ratingSel.onchange = async (e) => {
      const rating = e.target.value ? parseInt(e.target.value) : null;
      await apiPatch(`/api/reading-log/${log.id}`, { rating });
      loadLibrary();
    };
  }

  const startedInput = $("detail-started");
  if (startedInput) {
    startedInput.onchange = async (e) => {
      await apiPatch(`/api/reading-log/${log.id}`, { started_at: dateToIso(e.target.value) });
      loadLibrary();
    };
  }

  const finishedInput = $("detail-finished");
  if (finishedInput) {
    finishedInput.onchange = async (e) => {
      await apiPatch(`/api/reading-log/${log.id}`, { finished_at: dateToIso(e.target.value) });
      loadLibrary();
    };
  }

  const addStatusSel = $("detail-add-status");
  if (addStatusSel) {
    addStatusSel.onchange = async (e) => {
      if (!e.target.value) return;
      await apiPost("/api/reading-log", { book_id: book.id, status: e.target.value });
      closeModal();
      loadLibrary();
    };
  }

  $("detail-note-add").onclick = async () => {
    const input = $("detail-note-input");
    const content = input.value.trim();
    if (!content) return;
    await apiPost("/api/notes", { book_id: book.id, content });
    openBookDetail(book.id); // re-render
  };

  $("detail-quote-add").onclick = async () => {
    const input = $("detail-quote-input");
    const pageInput = $("detail-quote-page");
    const content = input.value.trim();
    if (!content) return;
    const page = pageInput.value ? parseInt(pageInput.value) : null;
    await apiPost("/api/quotes", { book_id: book.id, content, page });
    openBookDetail(book.id);
  };

  document.querySelectorAll(".quote-delete").forEach((btn) => {
    btn.onclick = async () => {
      const quoteEl = btn.closest(".quote");
      const id = quoteEl.dataset.quoteId;
      if (!confirm("Delete this passage?")) return;
      await api(`/api/quotes/${id}`, { method: "DELETE" });
      openBookDetail(book.id);
    };
  });

  // Edit title/author/year
  $("detail-edit-btn").onclick = () => {
    $("detail-title-text").style.display = "none";
    $("detail-author-text").style.display = "none";
    $("detail-edit-btn").style.display = "none";
    $("detail-edit-form").style.display = "block";
    $("edit-title").focus();
  };

  $("edit-cancel-btn").onclick = () => {
    $("detail-title-text").style.display = "";
    $("detail-author-text").style.display = "";
    $("detail-edit-btn").style.display = "";
    $("detail-edit-form").style.display = "none";
  };

  $("edit-save-btn").onclick = async () => {
    const title = $("edit-title").value.trim();
    const author = $("edit-author").value.trim();
    const yearStr = $("edit-year").value.trim();
    if (!title || !author) { alert("Title and author are required."); return; }

    const btn = $("edit-save-btn");
    btn.disabled = true;
    btn.textContent = "Saving…";
    try {
      await apiPatch(`/api/books/${book.id}`, {
        title,
        author,
        pub_year: yearStr ? parseInt(yearStr, 10) : null,
      });
      // Re-render modal with fresh data (cover may have changed)
      openBookDetail(book.id);
      // Library list may also need to update titles
      loadLibrary();
    } catch (e) {
      alert("Couldn't save: " + e.message);
      btn.disabled = false;
      btn.textContent = "Save";
    }
  };
}

function closeModal() {
  $("book-modal").classList.add("hidden");
  currentBookId = null;
}

$("book-modal").addEventListener("click", (e) => {
  if (e.target === $("book-modal") || e.target.classList.contains("modal-close")) {
    closeModal();
  }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("book-modal").classList.contains("hidden")) {
    closeModal();
  }
});

$("add-toggle").onclick = () => {
  const form = $("add-form");
  form.style.display = form.style.display === "none" ? "flex" : "none";
};

function dateToIso(value) {
  if (!value) return null;
  // <input type="date"> gives "YYYY-MM-DD"; expand to ISO datetime for the API
  return `${value}T12:00:00Z`;
}

$("add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const title = f.title.value.trim();
  const author = f.author.value.trim();
  const status = f.status.value;
  const rating = f.rating.value ? parseInt(f.rating.value) : null;
  const started_at = dateToIso(f.started_at.value);
  const finished_at = dateToIso(f.finished_at.value);
  if (!title || !author) return;

  await apiPost("/api/reading-log", {
    title, author, status, rating, started_at, finished_at,
  });
  f.reset();
  f.style.display = "none";
  loadLibrary();
});

loadLibrary().then(() => {
  const params = new URLSearchParams(window.location.search);
  const bid = parseInt(params.get("book") || "0", 10);
  if (bid) openBookDetail(bid);
});

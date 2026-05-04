const $ = (id) => document.getElementById(id);

function pad(n) { return String(n).padStart(2, "0"); }

function renderGoal(stats) {
  const section = $("goal-section");
  const g = stats.goal_progress;
  const year = new Date().getFullYear();

  if (!g) {
    section.innerHTML = `
      <div class="goal-empty">
        <span>No reading goal set for ${year}.</span>
        <button id="goal-set-btn" class="secondary small">Set a goal</button>
      </div>
    `;
    $("goal-set-btn").onclick = () => promptGoal(year, 24);
    return;
  }

  const pct = Math.max(0, Math.min(100, (g.completed / g.target) * 100));
  let pace;
  if (g.completed >= g.target) {
    pace = `<span class="pace good">Goal met!</span>`;
  } else if (Math.abs(g.pace_delta) < 0.5) {
    pace = `<span class="pace good">On pace</span>`;
  } else if (g.pace_delta > 0) {
    pace = `<span class="pace good">${g.pace_delta} ${g.pace_delta === 1 ? 'book' : 'books'} ahead of schedule</span>`;
  } else {
    const behind = Math.abs(g.pace_delta);
    pace = `<span class="pace behind">${behind} ${behind === 1 ? 'book' : 'books'} behind schedule</span>`;
  }

  section.innerHTML = `
    <div class="goal-card">
      <div class="goal-header">
        <div class="goal-title">Reading goal · ${g.year}</div>
        <button id="goal-edit-btn" class="secondary small">Edit</button>
      </div>
      <div class="goal-progress">
        <div class="goal-count">
          <span class="goal-current">${g.completed}</span>
          <span class="goal-of">of</span>
          <span class="goal-target">${g.target}</span>
        </div>
        <div class="goal-pace">${pace}</div>
      </div>
      <div class="goal-bar">
        <div class="goal-bar-fill" style="width: ${pct}%"></div>
      </div>
    </div>
  `;
  $("goal-edit-btn").onclick = () => promptGoal(g.year, g.target);
}

function promptGoal(currentYear, currentTarget) {
  const yearStr = prompt("Goal year:", String(currentYear));
  if (!yearStr) return;
  const year = parseInt(yearStr, 10);
  if (!year || year < 1900 || year > 2200) { alert("Invalid year."); return; }

  const targetStr = prompt(`How many books in ${year}? (0 to clear goal)`, String(currentTarget));
  if (targetStr === null) return;
  const target = parseInt(targetStr, 10);
  if (isNaN(target) || target < 0) { alert("Invalid target."); return; }

  apiPatch("/api/profile", {
    annual_goal_year: year,
    annual_goal_count: target,
  }).then(loadAll);
}

function renderStats(stats) {
  const row = $("stats-row");
  const cards = [
    { value: stats.shelves.read, label: "Books read" },
    { value: stats.shelves.reading, label: "Currently reading" },
    { value: stats.avg_rating ?? "—", label: "Average rating", muted: stats.avg_rating == null },
    { value: stats.total_notes, label: "Notes written" },
  ];
  row.innerHTML = cards.map(c => `
    <div class="stat-card">
      <div class="stat-value${c.muted ? " muted" : ""}">${c.value}</div>
      <div class="stat-label">${c.label}</div>
    </div>
  `).join("");
}

function monthLabel(year, monthIdx) {
  return new Date(year, monthIdx, 1).toLocaleString(undefined, { month: "long", year: "numeric" });
}

async function renderMonthlyGallery() {
  const lib = await apiGet("/api/library");
  const finished = (lib.read || []).filter((b) => b.finished_at);
  const undated = (lib.read || []).filter((b) => !b.finished_at);

  const section = $("monthly-section");

  if (finished.length === 0 && undated.length === 0) {
    section.innerHTML = "";
    return;
  }

  // Group by YYYY-MM
  const byMonth = {};
  for (const b of finished) {
    const d = new Date(b.finished_at);
    const key = `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
    (byMonth[key] = byMonth[key] || []).push(b);
  }
  const months = Object.keys(byMonth).sort().reverse();

  const monthSections = months.map((m) => {
    const [y, mo] = m.split("-").map(Number);
    const books = byMonth[m].sort((a, b) => new Date(b.finished_at) - new Date(a.finished_at));
    const grid = books.map(renderMonthBook).join("");
    return `
      <div class="month-section">
        <div class="month-header">
          <span class="month-title">${monthLabel(y, mo - 1)}</span>
          <span class="month-count">${books.length} ${books.length === 1 ? "book" : "books"}</span>
        </div>
        <div class="month-grid">${grid}</div>
      </div>
    `;
  }).join("");

  let undatedHtml = "";
  if (undated.length > 0) {
    undatedHtml = `
      <div class="month-section">
        <div class="month-header">
          <span class="month-title">No date set</span>
          <span class="month-count">${undated.length} ${undated.length === 1 ? "book" : "books"} · click to backfill</span>
        </div>
        <div class="month-grid">${undated.map(renderMonthBook).join("")}</div>
      </div>
    `;
  }

  section.innerHTML = `
    <h2 style="margin-top: 32px;">Books finished, by month</h2>
    ${monthSections}
    ${undatedHtml}
  `;
}

function renderMonthBook(b) {
  const cover = b.cover_url
    ? `<img src="${escapeHtml(b.cover_url)}" alt="" loading="lazy">`
    : `<div class="cover-fallback">${escapeHtml(b.title)}</div>`;
  const stars = b.rating ? "★".repeat(b.rating) : "";
  const date = b.finished_at ? formatDate(b.finished_at) : "no date";
  return `
    <a class="month-book" href="/library" title="${escapeHtml(b.title)} · ${date}">
      <div class="cover-wrap">${cover}</div>
      <div class="mb-title">${escapeHtml(b.title)}</div>
      ${stars ? `<div class="mb-rating">${stars}</div>` : ""}
    </a>
  `;
}

function extractPullQuote(summary) {
  if (!summary) return null;
  // Pull the first compact, declarative sentence that isn't "About this reader" type scaffold
  const sentences = summary.replace(/\n+/g, " ").split(/(?<=[.!?])\s+/);
  for (const s of sentences) {
    const trimmed = s.trim();
    if (trimmed.length >= 60 && trimmed.length <= 220) return trimmed.replace(/^["'“”]+|["'“”]+$/g, "");
  }
  return sentences[0]?.trim() || null;
}

function extractHighlights(prose) {
  if (!prose) return [];
  const matches = [...prose.matchAll(/==([^=\n]+)==/g)];
  // De-dupe while preserving order
  const seen = new Set();
  const out = [];
  for (const m of matches) {
    const phrase = m[1].trim();
    if (phrase && !seen.has(phrase.toLowerCase())) {
      seen.add(phrase.toLowerCase());
      out.push(phrase);
    }
  }
  return out.slice(0, 7);
}

function renderProfile(p) {
  const meta = $("taste-meta");
  const proseEl = $("prose-section");
  const pullEl = $("pull-quote");
  const deltaEl = $("delta-section");
  const highlightsEl = $("highlights-section");

  if (p.taste_summary) {
    const quote = extractPullQuote(p.taste_summary);
    pullEl.innerHTML = quote ? `<div class="pull-quote">${escapeHtml(quote.replace(/==/g, ""))}</div>` : "";
    meta.textContent = p.taste_generated_at ? `Last generated ${formatDate(p.taste_generated_at)}` : "";

    // Key observations — pulled out of ==phrase== markers
    const highlights = extractHighlights(p.taste_summary);
    if (highlights.length > 0) {
      highlightsEl.innerHTML = `
        <div class="highlights-block">
          <div class="highlights-label">Key observations</div>
          <ul class="highlights-list">
            ${highlights.map(h => `<li>${escapeHtml(h)}</li>`).join("")}
          </ul>
        </div>
      `;
    } else {
      highlightsEl.innerHTML = "";
    }

    // Full prose — collapsed by default behind a toggle
    proseEl.innerHTML = `
      <details class="prose-toggle">
        <summary>
          <span class="prose-toggle-label">Read the full portrait</span>
          <span class="prose-toggle-chevron" aria-hidden="true">⌄</span>
        </summary>
        <div class="taste-card">${renderMarkdown(p.taste_summary)}</div>
      </details>
    `;
  } else {
    pullEl.innerHTML = "";
    highlightsEl.innerHTML = "";
    proseEl.innerHTML = `
      <div class="empty">
        <p>Not yet portrayed</p>
        <p>Read some books, add notes, and talk with the librarian. A prose portrait will appear here.</p>
      </div>`;
    meta.textContent = "";
  }

  // What's shifted card
  if (p.taste_delta) {
    const since = p.taste_delta_since ? `Since ${formatDate(p.taste_delta_since)}` : "Recent shift";
    deltaEl.innerHTML = `
      <div class="delta-card">
        <div class="delta-label"><span class="delta-icon" aria-hidden="true">↻</span> ${since}</div>
        <div class="delta-content">${renderMarkdown(p.taste_delta)}</div>
      </div>
    `;
  } else {
    deltaEl.innerHTML = "";
  }

  renderConstellation(p.taste_constellation);
}

const CATEGORY_COLORS = {
  form: "#8B4513",
  mood: "#A0694B",
  region: "#6B7E5C",
  era: "#4D6B7E",
  concern: "#8B6B4A",
  style: "#B9885E",
};

function categoryColor(c) { return CATEGORY_COLORS[c] || "#8B4513"; }

function renderConstellation(data) {
  const section = $("constellation-section");
  if (!data || !data.themes || data.themes.length === 0) {
    section.innerHTML = `
      <div class="constellation-wrap empty-constellation">
        <div class="empty">
          <p>Your constellation hasn't been charted yet</p>
          <p>Click <em>Refresh portrait</em> above to chart your taste as a constellation of themes and the connections between them.</p>
        </div>
      </div>`;
    return;
  }

  const themes = data.themes.slice(0, 20);
  const connections = (data.connections || []).filter(c =>
    themes.some(t => t.name === c.from) && themes.some(t => t.name === c.to)
  );

  // Force-layout the nodes
  const W = 800, H = 480;
  const positions = layoutForce(themes, connections, W, H);

  // Build SVG
  const edgesSvg = connections.map(c => {
    const a = positions[c.from], b = positions[c.to];
    if (!a || !b) return "";
    return `<line class="edge" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"
            data-from="${escapeHtml(c.from)}" data-to="${escapeHtml(c.to)}"
            ><title>${escapeHtml(c.reason || c.from + ' ↔ ' + c.to)}</title></line>`;
  }).join("");

  const nodesSvg = themes.map(t => {
    const p = positions[t.name];
    if (!p) return "";
    const r = 6 + (Math.max(1, Math.min(10, t.weight || 5)) * 1.4);
    const color = categoryColor(t.category);
    const safe = escapeHtml(t.name);
    return `
      <g class="theme-node" data-name="${safe}">
        <circle class="halo" cx="${p.x}" cy="${p.y}" r="${r + 8}" fill="${color}" opacity="0"/>
        <circle class="star" cx="${p.x}" cy="${p.y}" r="${r}" fill="${color}"/>
        <text class="theme-label" x="${p.x}" y="${p.y - r - 6}" text-anchor="middle">${safe}</text>
      </g>`;
  }).join("");

  section.innerHTML = `
    <div class="constellation-wrap">
      <div class="constellation-header">
        <h2>Your taste, charted</h2>
        <div class="constellation-legend">
          ${Object.entries(CATEGORY_COLORS).map(([k, v]) =>
            `<span class="legend-item"><span class="dot" style="background:${v}"></span>${k}</span>`
          ).join("")}
        </div>
      </div>
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" class="constellation-svg">
        <g class="edges">${edgesSvg}</g>
        <g class="nodes">${nodesSvg}</g>
      </svg>
      <div id="theme-detail"></div>
    </div>
  `;

  // Wire interactions
  const svg = section.querySelector("svg");
  svg.querySelectorAll(".theme-node").forEach(g => {
    g.addEventListener("mouseenter", () => highlightTheme(g.dataset.name, svg, true));
    g.addEventListener("mouseleave", () => highlightTheme(g.dataset.name, svg, false));
    g.addEventListener("click", () => showThemeDetail(g.dataset.name, themes, connections));
  });
}

function highlightTheme(name, svg, on) {
  const edges = svg.querySelectorAll(".edge");
  edges.forEach(e => {
    const involved = e.dataset.from === name || e.dataset.to === name;
    e.classList.toggle("highlight", on && involved);
    e.classList.toggle("dim", on && !involved);
  });
  svg.querySelectorAll(".theme-node").forEach(n => {
    if (n.dataset.name === name) {
      n.classList.toggle("active", on);
    } else {
      n.classList.toggle("dim", on);
    }
  });
}

function showThemeDetail(name, themes, connections) {
  const t = themes.find(x => x.name === name);
  if (!t) return;
  const detail = $("theme-detail");

  const linked = connections.filter(c => c.from === name || c.to === name);
  const linkedNames = linked.map(c => c.from === name ? c.to : c.from);

  detail.innerHTML = `
    <div class="theme-card">
      <button class="modal-close" aria-label="Close">×</button>
      <div class="theme-cat-pill" style="background:${categoryColor(t.category)}1a; color:${categoryColor(t.category)}">${escapeHtml(t.category || 'theme')}</div>
      <h3 class="theme-name">${escapeHtml(t.name)}</h3>
      ${t.books && t.books.length ? `
        <div class="theme-section">
          <div class="theme-label-sm">Anchored by</div>
          <ul class="theme-list">${t.books.map(b => `<li>${escapeHtml(b)}</li>`).join("")}</ul>
        </div>` : ""}
      ${linkedNames.length ? `
        <div class="theme-section">
          <div class="theme-label-sm">Connected to</div>
          <ul class="theme-list">${linkedNames.map(b => `<li>${escapeHtml(b)}</li>`).join("")}</ul>
        </div>` : ""}
    </div>
  `;
  detail.querySelector(".modal-close").onclick = () => { detail.innerHTML = ""; };
}

// ── Force-directed layout ──────────────────────────────────────────────────
function layoutForce(themes, connections, W, H) {
  const cx = W / 2, cy = H / 2;
  const nodes = themes.map((t, i) => {
    // Initial positions: weighted random in a circle
    const angle = (i / themes.length) * Math.PI * 2 + Math.random() * 0.6;
    const r = 80 + Math.random() * 140;
    return {
      name: t.name,
      weight: t.weight || 5,
      radius: 6 + (t.weight || 5) * 1.4,
      x: cx + Math.cos(angle) * r,
      y: cy + Math.sin(angle) * r,
      vx: 0, vy: 0,
    };
  });
  const byName = Object.fromEntries(nodes.map(n => [n.name, n]));
  const edges = connections
    .map(c => ({ a: byName[c.from], b: byName[c.to] }))
    .filter(e => e.a && e.b);

  const REPEL = 9000;
  const SPRING_K = 0.012;
  const REST_LEN = 130;
  const CENTER_K = 0.005;
  const DAMP = 0.82;
  const MARGIN = 60;

  for (let iter = 0; iter < 280; iter++) {
    // Repulsion
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 0.01) { dx = Math.random(); dy = Math.random(); d2 = dx*dx + dy*dy; }
        const f = REPEL / d2;
        const dist = Math.sqrt(d2);
        const fx = (dx / dist) * f, fy = (dy / dist) * f;
        a.vx += fx; a.vy += fy;
        b.vx -= fx; b.vy -= fy;
      }
    }
    // Spring along edges
    for (const e of edges) {
      const dx = e.b.x - e.a.x, dy = e.b.y - e.a.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const f = SPRING_K * (dist - REST_LEN);
      const fx = (dx / dist) * f, fy = (dy / dist) * f;
      e.a.vx += fx; e.a.vy += fy;
      e.b.vx -= fx; e.b.vy -= fy;
    }
    // Center gravity
    for (const n of nodes) {
      n.vx += (cx - n.x) * CENTER_K;
      n.vy += (cy - n.y) * CENTER_K;
      n.vx *= DAMP;
      n.vy *= DAMP;
      n.x += n.vx;
      n.y += n.vy;
      // Soft boundary
      n.x = Math.max(MARGIN, Math.min(W - MARGIN, n.x));
      n.y = Math.max(MARGIN, Math.min(H - MARGIN, n.y));
    }
  }

  return Object.fromEntries(nodes.map(n => [n.name, { x: n.x, y: n.y }]));
}

async function renderTimeline() {
  const lib = await apiGet("/api/library");
  // Most recent reading activity across read + reading shelves
  const items = [
    ...lib.read.map(b => ({ ...b, event: "Finished", date: b.finished_at })),
    ...lib.reading.map(b => ({ ...b, event: "Started", date: b.started_at || null })),
  ]
  .filter(b => b.date)
  .sort((a, b) => new Date(b.date) - new Date(a.date))
  .slice(0, 8);

  const section = $("timeline-section");
  if (items.length === 0) {
    section.innerHTML = "";
    return;
  }

  const itemsHtml = items.map(b => {
    const cover = b.cover_url
      ? `<img class="cover-mini" src="${escapeHtml(b.cover_url)}" alt="" loading="lazy">`
      : `<div class="cover-mini-empty"></div>`;
    const stars = b.rating ? "★".repeat(b.rating) : "";
    return `
      <div class="timeline-item">
        ${cover}
        <div class="ti-info">
          <div class="ti-title">${escapeHtml(b.title)}</div>
          <div class="ti-meta">${escapeHtml(b.author)} · ${b.event} ${formatDate(b.date)}${stars ? ` · ${stars}` : ""}</div>
        </div>
      </div>
    `;
  }).join("");

  section.innerHTML = `
    <h2 style="margin-top: 36px;">Recent reading</h2>
    <div class="timeline">${itemsHtml}</div>
  `;
}

function safe(fn, label) {
  try {
    const r = fn();
    if (r && typeof r.catch === "function") r.catch((e) => console.error(`[${label}]`, e));
  } catch (e) {
    console.error(`[${label}]`, e);
  }
}

async function loadAll() {
  let profile, stats;
  try {
    [profile, stats] = await Promise.all([apiGet("/api/profile"), apiGet("/api/stats")]);
  } catch (e) {
    console.error("[loadAll fetch]", e);
    return;
  }
  safe(() => renderGoal(stats), "renderGoal");
  safe(() => renderStats(stats), "renderStats");
  safe(() => renderProfile(profile), "renderProfile");
  safe(() => renderMonthlyGallery(), "renderMonthlyGallery");
  safe(() => renderTimeline(), "renderTimeline");
}

$("refresh-btn").onclick = async () => {
  const btn = $("refresh-btn");
  btn.disabled = true;
  btn.textContent = "Writing…";
  try {
    const p = await apiPost("/api/profile/refresh-taste", {});
    renderProfile(p);
  } catch (e) {
    alert("Couldn't refresh: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Refresh portrait";
  }
};

loadAll();

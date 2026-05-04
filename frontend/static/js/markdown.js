/*
 * Minimal markdown renderer for Claude's literary output.
 * Handles: bold, italic, headers, bullet/numbered lists, blockquotes, paragraphs,
 * plus special patterns for book titles and evocative one-liners.
 * Input is HTML-escaped first, so no injection risk.
 */
function renderMarkdown(text) {
  if (!text) return "";
  const html = escapeHtml(text);
  const blocks = html.split(/\n{2,}/);
  return blocks.map(renderBlock).join("\n");
}

function renderBlock(block) {
  const lines = block.split("\n");
  const trimmed = block.trim();

  // Headers
  const h = trimmed.match(/^(#{1,3})\s+(.+)$/);
  if (h && lines.length === 1) {
    const level = h[1].length;
    return `<h${level}>${renderInline(h[2])}</h${level}>`;
  }

  // Standalone book title line: **Title** or **Title** by Author (year)
  if (lines.length === 1) {
    const bookTitle = trimmed.match(/^\*\*([^*]+)\*\*(\s+by\s+.+)?$/);
    if (bookTitle) {
      const title = bookTitle[1];
      const trailer = bookTitle[2] || "";
      return `<p class="book-title-line">${renderInline(title)}${renderInline(trailer)}</p>`;
    }

    // Standalone evocative/italic line: *A single evocative sentence.*
    const evocative = trimmed.match(/^\*([^*].+?)\*$/);
    if (evocative) {
      return `<p class="evocative-line">${renderInline(evocative[1])}</p>`;
    }
  }

  // Unordered list
  if (lines.every((l) => /^\s*[-*]\s+/.test(l))) {
    const items = lines.map((l) => `<li>${renderInline(l.replace(/^\s*[-*]\s+/, ""))}</li>`).join("");
    return `<ul>${items}</ul>`;
  }

  // Ordered list
  if (lines.every((l) => /^\s*\d+\.\s+/.test(l))) {
    const items = lines.map((l) => `<li>${renderInline(l.replace(/^\s*\d+\.\s+/, ""))}</li>`).join("");
    return `<ol>${items}</ol>`;
  }

  // Blockquote
  if (lines.every((l) => /^\s*&gt;\s?/.test(l))) {
    const content = lines.map((l) => l.replace(/^\s*&gt;\s?/, "")).join(" ");
    return `<blockquote>${renderInline(content)}</blockquote>`;
  }

  // Paragraph
  return `<p>${renderInline(lines.join("<br>"))}</p>`;
}

function renderInline(s) {
  return s
    .replace(/==([^=\n]+)==/g, '<mark class="highlight">$1</mark>')
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(?<![\*\w])\*([^*\n]+)\*(?![\*\w])/g, "<em>$1</em>")
    .replace(/(?<![\w_])_([^_\n]+)_(?![\w_])/g, "<em>$1</em>");
}

# Future Work

Ideas deferred intentionally, with the reasoning, so they're not lost.

## History-lookup tool (replace the inline "already in their library" dump)

**Now:** `build_reading_summary` injects the reader's *entire* library into every
system prompt as a "do NOT recommend these again" list. Correct and simple, but it
doesn't scale — at 200+ books it bloats the prompt and the librarian can't filter
intelligently.

**Future:** give the librarian a small set of tools to *query* reading history
instead of receiving it wholesale, e.g.:

- `has_read(title, author) -> bool` — exclusion check before finalizing a pick
- `search_history(query) -> [books]` — find what the reader has read by
  author / theme / era / region (lets personas reason about gaps and patterns
  without the whole list in context)
- maybe `library_stats()` — counts by shelf / rating distribution

**Why defer:** it's an architecture change (tool-use loop in the chat path) and is
best slotted in while the persona behavior is stable, not while it's being actively
evaluated. When added, re-verify the "never re-recommend a read book" guarantee holds
via the tool rather than the inline list.

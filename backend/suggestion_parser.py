from __future__ import annotations

import re
import json
from typing import List, Tuple


def parse_suggestions(response_text: str) -> Tuple[str, List[dict]]:
    """
    Extract the trailing ```json [...] ``` block Claude appends to every reply.
    Returns (clean_text, books) where clean_text has the block removed.
    Books is a list of {title, author, pub_year, reason} dicts.
    """
    pattern = r"```json\s*(\[.*?\])\s*```"
    match = re.search(pattern, response_text, re.DOTALL)
    if not match:
        return response_text.strip(), []

    clean = (response_text[: match.start()] + response_text[match.end() :]).strip()

    try:
        books = json.loads(match.group(1))
        if isinstance(books, list):
            return clean, books
    except (json.JSONDecodeError, ValueError):
        pass

    return clean, []

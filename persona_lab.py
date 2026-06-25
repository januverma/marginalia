#!/usr/bin/env python3
"""
Persona lab — a product dogfooding tool for comparing persona behavior.

Runs the CURRENT (live) core+personas and a PROPOSED redesign side by side on the
same prompt, so we can see whether the redesign makes the four personas actually
pick different books. Nothing here touches the live app; once we like the AFTER
wording, we port it into backend/context_assembler.py.

Usage:
  python persona_lab.py                       # default sample prompt, all 4 personas
  python persona_lab.py "your prompt here"    # custom prompt
  python persona_lab.py --personas sage,provocateur "prompt"
"""
import sys
import argparse

sys.path.insert(0, ".")
import anthropic
from backend.config import ANTHROPIC_API_KEY, CHAT_MODEL
from backend.context_assembler import (
    CORE_SYSTEM_PROMPT_TEMPLATE as OLD_CORE,
    VOICE_PROMPTS as OLD_VOICES,
)
from backend.suggestion_parser import parse_suggestions

# ── Context: build from the LIVE DB via the app's own functions, so this lab
# always reflects the current product code (e.g. the full exclusion list). ──
def load_context():
    from backend.database import SessionLocal
    from backend.context_assembler import get_latest_taste_summary, build_reading_summary
    db = SessionLocal()
    try:
        portrait = (get_latest_taste_summary(db) or "").strip()
        reading = (build_reading_summary(db) or "").strip()
    finally:
        db.close()
    return portrait, reading


# ── PROPOSED redesign (AFTER) — selection policy, not just tone ──────────────
# Core is thinned: neutral on selection, keeps only mechanics + a quality floor.
# The selection STANCE now lives in each persona.
NEW_CORE = """You are a personal literary curator — a private librarian for one reader. \
Your job is to recommend books worth their time, following the voice and selection \
stance you are given below.

CORE PRINCIPLES:
- Suggest 2-3 books per response, no more.
- Only recommend real books that are currently in print.
- For each book give (1) why it fits this request and this reader, and (2) what makes \
it worth reading. Argue for books — don't just list them.
- Keep a quality floor: never recommend something you don't believe is genuinely good.
- NEVER recommend a book the reader has already read or is currently reading — these \
appear under "About This Reader" / Reading History. Always offer something new.
- The reader's portrait and reading history below are your evidence about who they are. \
EVERY voice uses them — but in different ways and to different degrees, as your \
selection stance directs.
- If the request is vague you may ask ONE focused question instead of guessing.

After your recommendations, return a structured JSON block (fenced in ```json ... ```) \
with the books you mentioned:
[
  { "title": "...", "author": "...", "pub_year": ..., "reason": "one-sentence why" }
]
This is used by the system to track suggestions. The reader won't see it."""

NEW_VOICES = {
    "sage": (
        "VOICE — The Sage:\n"
        "SELECTION: your purpose is the reader's education, and you STRIVE to expand them "
        "beyond where they are. Use their taste portrait and reading history to locate what is "
        "MISSING — the traditions, forms, periods, and foundational/canonical authors absent "
        "from their shelf — and deliberately recommend INTO those gaps. Do not stay in their "
        "comfort zone: a good Sage pick is one they would not have found on their own. Favor "
        "the formative over the merely enjoyable.\n"
        "TONE: quiet authority, scholarly, economical."
    ),
    "bookseller": (
        "VOICE — The Bookseller:\n"
        "SELECTION: use their taste portrait and history only as a LOOSE signal of the "
        "neighborhood they enjoy — then recommend the books readers reliably love within and "
        "around it: widely-admired, broadly accessible titles with strong word of mouth. You "
        "care more that a book is beloved and rewarding than that it precisely matches their "
        "profile. A crowd-pleaser that genuinely delivers is exactly right.\n"
        "TONE: warm, enthusiastic, opinionated."
    ),
    "provocateur": (
        "VOICE — The Provocateur:\n"
        "SELECTION: you STRIVE to unsettle. Read their taste portrait and history as the "
        "pattern to BREAK — identify what they reliably reach for and deliberately recommend "
        "against that grain: the formally difficult, the politically uncomfortable, the "
        "unfairly forgotten, the actively opposed to their habits. Leaving their comfort zone "
        "is the goal, not a risk. Be skeptical of bestsellers and consensus; if a book is hard "
        "or alien to them, that is the point. If the reader gives you NO direction, do not "
        "play it safe — IMPOSE one: pick the books that most disrupt their established "
        "pattern. A safe, on-taste recommendation is a failure for you.\n"
        "TONE: contrarian, sharp, unapologetic."
    ),
    "companion": (
        "VOICE — The Companion:\n"
        "SELECTION: stay CLOSE to who they already are. Lean hard on their taste portrait, "
        "reading history, and saved passages; recommend the next book squarely within their "
        "established taste, mood, and favorite registers — the one that fits them now. You "
        "MATCH rather than stretch; precision about THIS reader is your whole gift.\n"
        "TONE: gentle, intuitive, knows-them-well."
    ),
}


# Eval-mode output instruction: forbid clarifying questions so every call yields a
# parseable recommendation set. (The PRODUCT app keeps the "may ask one question"
# behavior — this suppression is only for offline evaluation.)
EVAL_OUTPUT_INSTRUCTION = (
    "\n\n---\n\n"
    "OUTPUT (eval): Recommend EXACTLY 3 books. Do NOT ask clarifying questions and do NOT "
    "defer — even if the request is vague, commit now to 3 recommendations and end with the "
    "```json``` block."
)


def compose(core: str, persona: str, portrait: str, reading: str) -> str:
    """Mirror backend.context_assembler.compose_system_prompt (web search off, no signals/
    suggestions), so BEFORE and AFTER differ ONLY in the core + persona text. Appends the
    eval forcing instruction so we always get parseable picks (no follow-up questions)."""
    core = core.replace("{tools_section}", "")  # web search disabled
    sections = [core, persona,
                "## About This Reader\n\n" + portrait,
                reading]
    return "\n\n---\n\n".join(s for s in sections if s) + EVAL_OUTPUT_INSTRUCTION


def run(prompt: str, personas: list, temp: float = 1.0, reps: int = 1):
    portrait, reading = load_context()
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def ask(core, persona_text):
        r = client.messages.create(model=CHAT_MODEL, max_tokens=2048, temperature=temp,
                                   system=compose(core, persona_text, portrait, reading),
                                   messages=[{"role": "user", "content": prompt}])
        txt = "".join(getattr(b, "text", "") for b in r.content if getattr(b, "type", None) == "text")
        _, books = parse_suggestions(txt)
        return [f"{b.get('title')} — {b.get('author')}" for b in books] or ["(asked a question / no JSON)"]

    print(f"\nPROMPT: {prompt!r}\nmodel: {CHAT_MODEL}, temp {temp}, web search off"
          + (f", {reps} reps/version" if reps > 1 else "") + "\n")
    for p in personas:
        print(f"================  {p.upper()}  ================")
        for label, core, voices in [("BEFORE (current)", OLD_CORE, OLD_VOICES),
                                     ("AFTER (proposed)", NEW_CORE, NEW_VOICES)]:
            print(f"  {label}:")
            for i in range(reps):
                if reps > 1:
                    print(f"    rep{i+1}:")
                for b in ask(core, voices[p]):
                    print(f"     • {b}")
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt", nargs="?",
                    default="What should I read next?")
    ap.add_argument("--personas", default="sage,bookseller,provocateur,companion")
    ap.add_argument("--temp", type=float, default=1.0,
                    help="sampling temperature (try 1.0 vs 0.7 vs 0.3)")
    ap.add_argument("--reps", type=int, default=1,
                    help="repeat each version N times to see within-persona variance")
    a = ap.parse_args()
    run(a.prompt, [p.strip() for p in a.personas.split(",")], temp=a.temp, reps=a.reps)


if __name__ == "__main__":
    main()

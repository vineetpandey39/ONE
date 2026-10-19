"""Ask for a finished cover, not a photograph of the book's subject.

The factory wrote cover_prompt.txt as a scene - "Arvind Mehta stands in
silhouette against the glass wall of the MG Road data center" - and the
workflow then told the image model, in capitals, that this was "a standalone
illustration, NOT a book cover" with "no text, letters, numbers, typography or
lettering of any kind". A separate step painted the title over the top. Ten
books came out of that: dark cinematic photographs with a long title laid
across them, indistinguishable from each other in a shelf of thumbnails.

The covers that sell in this catalogue do none of that. They are flat and
bright, the title is enormous, one phrase is boxed out in a contrasting
colour, a badge carries a number you can check, and three or four benefit
lines sit under it. No photograph, no person, nothing cinematic.

This builds that brief from what the commission already decided - the title it
chose, its thumbnail promise, its lead magnet - instead of from the plot of
chapter one. Pair it with kdp_cover_qc: asking a model for type is what buys
the variety, and it is also what makes checking the spelling non-optional.
"""
from __future__ import annotations

import re

MAX_BADGE_WORDS = 4


def _clean(text: str) -> str:
    return " ".join(str(text or "").replace("‑", "-").split())


# A benefit line is read in a glance or not at all. The sellers' covers top
# out around here; "PowerShell Command Sheet for Agentic Workflow
# Orchestration" is a lead magnet, not a bullet.
MAX_BULLET_CHARS = 28


def _bullets(promise: str, lead_magnet: str, keywords: list[str] | None) -> list[str]:
    """Three or four short benefit lines, in the buyer's words."""
    out: list[str] = []
    seen: set[str] = set()

    def offer(text: str) -> None:
        phrase = _clean(text)
        if (not phrase or len(phrase) > MAX_BULLET_CHARS
                or phrase.upper() in seen or len(out) >= 4):
            return
        seen.add(phrase.upper())
        out.append(phrase)

    # Keywords first: they are already the short concrete nouns a buyer
    # searches for, which is what belongs on a cover.
    for word in (keywords or []):
        offer(word)
    for source in (promise, lead_magnet):
        offer(source)
        if len(out) >= 4:
            break
        # A phrase too long to fit still contains a usable one.
        words = _clean(source).split()
        for size in (3, 2):
            if len(out) >= 4:
                break
            if len(words) >= size:
                offer(" ".join(words[:size]))
    return out[:4]


def _badge(promise: str, lead_magnet: str) -> str:
    """A short proof cue. Prefers something countable, as the sellers do."""
    for source in (promise, lead_magnet):
        # No trailing word boundary: it refuses to match after a "+", so
        # "90+ worked examples" came back as "90 INSIDE" and quietly
        # dropped the part of the claim that does the work.
        number = re.search(r"\b\d{2,4}\+?", _clean(source))
        if number:
            return f"{number.group(0)} INSIDE"
    # No number to claim, so name the thing the reader actually gets. A badge
    # that just repeats the title's first four words proves nothing.
    for source in (lead_magnet, promise):
        plain = _clean(source).upper()
        for noun in ("COMMAND SHEET", "CHECKLIST", "TEMPLATE", "WORKBOOK",
                     "PLAYBOOK", "CHEAT SHEET", "SCRIPTS", "WORKSHEETS"):
            if noun in plain:
                return f"{noun} INSIDE"
    return "COMPLETE GUIDE"


def cover_prompt(*, title: str, subtitle: str = "", author: str,
                 thumbnail_promise: str = "", lead_magnet: str = "",
                 series: str = "", keywords: list[str] | None = None) -> str:
    """The brief handed to the image model, as one paragraph it will follow."""
    title = _clean(title)
    if not title:
        raise ValueError("A cover needs the book's title.")
    author = _clean(author)
    bullets = _bullets(thumbnail_promise, lead_magnet, keywords)
    badge = _badge(thumbnail_promise, lead_magnet)
    sub = _clean(subtitle)
    series_line = _clean(series)

    parts = [
        "Design a complete, finished ebook cover, ready to publish. Portrait, "
        "vertical, aspect ratio exactly 1600 by 2560 - do not produce a square "
        "or landscape image.",
        "Style: flat graphic design. A single smooth colour gradient fills the "
        "whole cover, bright and highly saturated. No photograph, no "
        "photorealism, no people, no faces, no silhouettes, no landscapes, no "
        "rooms, no server racks, no cityscapes, no mockup of a physical book, "
        "no 3D, no drop shadows, no texture.",
        f"Render this title in very large, heavy, condensed sans-serif capitals "
        f"across the upper half, broken over two or three lines, white: "
        f"“{title}”.",
        "Box out the most concrete noun phrase of that title in a solid dark "
        "rectangle with the text inside it in bright yellow, so one phrase "
        "reads first from across a room.",
        f"Place a small circular badge near a top corner reading "
        f"“{badge}” in dark text on bright yellow.",
    ]
    if sub:
        parts.append(f"Under the title, one line of medium-weight text: “{sub}”.")
    if bullets:
        listed = "; ".join(f"“{b}”" for b in bullets)
        parts.append(
            f"Below that, {len(bullets)} short benefit lines in bold capitals, "
            f"each with a small check mark: {listed}.")
    parts.append(
        f"Across the very bottom, a solid dark horizontal bar containing the "
        f"author name “{author}” in large bright capitals"
        + (f", with “{series_line}” in smaller capitals beneath it."
           if series_line else "."))
    parts.append(
        "Every word above must be spelled exactly as written and must be fully "
        "inside the image with margin around it - nothing cropped at an edge, "
        "no letters cut off, no invented words, no placeholder or lorem text, "
        "no extra headings, no publisher logo, no barcode, no price. The title "
        "must stay legible when the whole cover is shrunk to 120 pixels wide.")
    return " ".join(parts)

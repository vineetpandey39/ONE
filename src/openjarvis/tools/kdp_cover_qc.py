"""Check that a generated cover says what the book is called.

Asking an image model for a finished cover - type and all - buys variety and
costs spelling. The model renders letters as shapes, so it drops words, invents
them, and runs two together, and none of that is visible to the pipeline that
uploaded the file. This reads the cover back with the OCR engine Windows
already ships, and refuses a cover whose own title it cannot find.

Deliberately fuzzy. Run against the live cover of Agentic Automation on
2026-10-15, Windows OCR returned "GOVERNING Al WORKFLOWS" for "GOVERNING AI
WORKFLOWS" and "ENDOR-FREE" for "A Vendor-Free" - the cover was correct and the
reader was not. A gate strict enough to catch those would refuse good covers
every time, so this scores how much of the title survived rather than demanding
it back verbatim.
"""
from __future__ import annotations

import re
import subprocess
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# Shapes Windows OCR genuinely confuses, folded before comparing so a cover is
# not refused for the reader's eyesight.
# I, l, L, 1 and a bare pipe are one shape to an OCR reader and are folded to
# a single letter on BOTH sides of the comparison. Mapping only lowercase l was
# worse than not folding at all: it rewrote the expected "PowerShell" into
# "POWERSHEII" while the reader had correctly returned "POWERSHELL", and the
# gate then reported the one word on the cover it had got right as missing.
_FOLD = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B",
                       "|": "I", "l": "I", "L": "I", "I": "I"})
_OCR_SCRIPT = Path(__file__).with_name("kdp_cover_ocr.ps1")

# Short words OCR drops or merges often enough that their absence says nothing.
_IGNORABLE = frozenset({"A", "AN", "THE", "AND", "OR", "OF", "TO", "FOR",
                        "WITH", "IN", "ON", "BY", "YOUR", "IS"})


def read_text(image: str | Path, *, timeout: int = 120) -> str:
    """Whatever Windows can read off the image, or '' when it cannot run."""
    if not _OCR_SCRIPT.is_file():
        raise FileNotFoundError(f"OCR helper missing at {_OCR_SCRIPT}")
    done = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(_OCR_SCRIPT), str(image)],
        capture_output=True, text=True, timeout=timeout)
    if done.returncode != 0:
        raise RuntimeError(
            f"Windows OCR failed: {(done.stderr or done.stdout).strip()[:300]}")
    return done.stdout.strip()


def _words(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text or "")
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    # Folded before the uppercase, not after: lowercase l is the shape OCR
    # hands back for a capital I, and "Al" for "AI" was the first thing it got
    # wrong on a real cover. Uppercasing first turns that l into an L, which no
    # fold can undo without breaking every word that genuinely has one.
    plain = plain.translate(_FOLD).upper()
    return [w for w in re.findall(r"[A-Z]+", plain) if len(w) > 1]


def _word_pairs(text: str) -> list[tuple[str, str]]:
    """Each word twice: folded for comparing, as written for reporting.

    Folding is per character and never moves a word boundary, so the two
    tokenisations line up. Without this a note told the reader that
    "POWERSHEII" and "WORKFIOWS" were on the cover, which is the comparison
    form and not anything a person could look for.
    """
    plain = unicodedata.normalize("NFKD", text or "")
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch)).upper()
    raw = [w for w in re.findall(r"[A-Z]+", plain) if len(w) > 1]
    return list(zip(_words(text), raw))


def _close(a: str, b: str) -> bool:
    """One missing or swapped letter is still the same word to a reader."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1 or min(len(a), len(b)) < 4:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    long, short = (a, b) if len(a) > len(b) else (b, a)
    return any(long[:i] + long[i + 1:] == short for i in range(len(long)))


def _coverage(expected: str, found: list[str]) -> tuple[float, list[str]]:
    wanted = [w for w in _words(expected) if w not in _IGNORABLE]
    if not wanted:
        return 1.0, []
    missing = [w for w in wanted if not any(_close(w, f) for f in found)]
    return (len(wanted) - len(missing)) / len(wanted), missing


@dataclass
class CoverCheck:
    ok: bool
    title_coverage: float
    author_found: bool
    ocr_text: str
    missing_title_words: list[str] = field(default_factory=list)
    foreign_words: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "title_coverage": round(self.title_coverage, 3),
                "author_found": self.author_found,
                "missing_title_words": self.missing_title_words,
                "foreign_words": self.foreign_words,
                "notes": self.notes, "ocr_text": self.ocr_text[:1000]}


def check_cover(image: str | Path, *, title: str, author: str = "",
                forbid: list[str] | None = None,
                minimum_title_coverage: float = 0.75) -> CoverCheck:
    """Refuse a cover whose title the OCR cannot mostly find on it.

    Coverage, not equality: see the module docstring for why. The author is
    reported but never the sole reason to refuse - it is often set in a
    stylised face OCR reads poorly, and a cover with the right title and an
    unreadable byline is a cover worth looking at, not one worth discarding.
    """
    text = read_text(image)
    found = _words(text)
    coverage, missing = _coverage(title, found)
    author_ok = bool(author) and _coverage(author, found)[0] >= 0.5
    notes: list[str] = []
    if not found:
        notes.append("Windows OCR read no text at all on this cover.")
    if author and not author_ok:
        notes.append("The author name could not be read; check it by eye.")
    # A cover can carry its title and still be ruined by carrying something
    # else as well. The first house-style cover came back with the model's own
    # typography intact and the factory's 86-character title painted across
    # the benefit list, plus a second author line stamped over the author bar.
    # It passed, because the title really was on it.
    #
    # Repeated words are not the signal - a real cover says WINDOWS in the
    # title, in the boxed phrase and in a bullet, and the clean version of
    # this very cover repeats four words quite correctly. What gives a
    # painted-over cover away is wording that belongs to a different string:
    # here, words from the long title that are not in the short one.
    intruders: list[str] = []
    own = set(_words(title))
    for other in (forbid or []):
        extra = [(folded, raw) for folded, raw in _word_pairs(other)
                 if folded not in _IGNORABLE and folded not in own]
        hits = [raw for folded, raw in extra
                if any(_close(folded, f) for f in found)]
        if len(hits) >= 2:
            intruders.extend(hits)
    intruders = sorted(set(intruders))
    if intruders:
        notes.append(
            "Words that belong to a different title are on this cover, which "
            "means something was painted over the finished art: "
            f"{', '.join(intruders[:6])}.")
    ok = bool(found) and coverage >= minimum_title_coverage and not intruders
    if not ok and found:
        notes.append(
            f"Only {coverage:.0%} of the title was readable on the cover; "
            f"missing: {', '.join(missing[:8]) or 'none'}.")
    return CoverCheck(ok=ok, title_coverage=coverage, author_found=author_ok,
                      ocr_text=text, missing_title_words=missing,
                      foreign_words=intruders, notes=notes)

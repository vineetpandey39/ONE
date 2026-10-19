"""Turn the factory's A4 manuscript into a KDP print interior.

Why this exists
---------------
The KDP Book Factory emits `KDP_Book_Professional.docx` at A4 (8.27 x 11.69
inches). A4 is a document size, not a trade book: KDP's paperback trims start
at 5 x 8 and the common one is 6 x 9. Uploading A4 as a paperback interior
gets a book with the wrong proportions and margins that fail review, so the
print formats could never be automated no matter how good the browser
automation was. This is the missing half.

Every number here was read from KDP's own help pages on 2026-09-24
(Set Trim Size, Bleed, and Margins; Hardcover), not assumed:

* Paperback: 24-828 pages on black ink / white paper. Common trim 6 x 9.
* Hardcover: the same print options "with a few exceptions" - five trim sizes
  and a page count of 75-550. A book under 75 pages cannot be a hardcover at
  all, which is a content decision, not a formatting one.
* Outside margins without bleed: at least 0.25 in. With bleed: 0.375 in.
* The inside margin (gutter) grows with page count, because a thicker book
  needs more room at the spine.

No third-party dependency: a .docx is a zip of XML, and the page setup lives
in one `<w:sectPr>` element per section. python-docx is not installed here and
this does not need it.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Word measures in twips: 1 inch = 1440.
TWIPS_PER_INCH = 1440


@dataclass(frozen=True)
class Trim:
    name: str
    width_in: float
    height_in: float
    large: bool = False


# The five trims KDP offers for hardcover are a subset of the paperback list,
# so one table serves both and `HARDCOVER_TRIMS` names the subset.
TRIMS: dict[str, Trim] = {
    "5x8": Trim("5 x 8", 5.0, 8.0),
    "5.25x8": Trim("5.25 x 8", 5.25, 8.0),
    "5.5x8.5": Trim("5.5 x 8.5", 5.5, 8.5),
    "6x9": Trim("6 x 9", 6.0, 9.0),
    "6.14x9.21": Trim("6.14 x 9.21", 6.14, 9.21, large=True),
    "7x10": Trim("7 x 10", 7.0, 10.0, large=True),
}
DEFAULT_TRIM = "6x9"
HARDCOVER_TRIMS = ("5.5x8.5", "6x9", "6.14x9.21", "7x10")

PAPERBACK_PAGES = (24, 828)
HARDCOVER_PAGES = (75, 550)

# Inside (gutter) margin by page count, without bleed. Straight from KDP's
# "Minimum margin size by page count" table.
GUTTER_BY_PAGES: tuple[tuple[int, float], ...] = (
    (150, 0.375),
    (300, 0.5),
    (500, 0.625),
    (700, 0.75),
    (828, 0.875),
)
OUTSIDE_MARGIN_IN = 0.375          # KDP's floor is 0.25; this reads better
OUTSIDE_MARGIN_BLEED_IN = 0.375
TOP_BOTTOM_MARGIN_IN = 0.75

# A 6 x 9 page of body text at 11pt holds roughly this much. Only used to
# predict the page count before KDP has told us the real one, which is why the
# gutter it picks is checked again after upload rather than trusted blindly.
WORDS_PER_PRINT_PAGE = 300


def gutter_for(page_count: int) -> float:
    """The inside margin KDP requires for a book this thick."""
    for limit, inches in GUTTER_BY_PAGES:
        if page_count <= limit:
            return inches
    return GUTTER_BY_PAGES[-1][1]


def estimate_pages(word_count: int, *, words_per_page: int = WORDS_PER_PRINT_PAGE) -> int:
    """Rough page count before KDP computes the real one. Front and back matter
    add a handful of pages, so this rounds up rather than down."""
    if word_count <= 0:
        return 0
    return max(1, -(-word_count // max(1, words_per_page)) + 6)


def eligible_formats(page_count: int) -> dict[str, Any]:
    """Which print formats this length can actually be sold as.

    Returned rather than raised: a book that is too short for hardcover is a
    perfectly good paperback, and the caller should publish what it can.
    """
    paperback = PAPERBACK_PAGES[0] <= page_count <= PAPERBACK_PAGES[1]
    hardcover = HARDCOVER_PAGES[0] <= page_count <= HARDCOVER_PAGES[1]
    reasons: dict[str, str] = {}
    if not paperback:
        reasons["paperback"] = (
            f"{page_count} pages is outside KDP's paperback range "
            f"{PAPERBACK_PAGES[0]}-{PAPERBACK_PAGES[1]}")
    if not hardcover:
        reasons["hardcover"] = (
            f"{page_count} pages is outside KDP's hardcover range "
            f"{HARDCOVER_PAGES[0]}-{HARDCOVER_PAGES[1]}")
    return {"page_count": page_count, "paperback": paperback,
            "hardcover": hardcover, "reasons": reasons}


def _sect_pr_replacement(trim: Trim, gutter_in: float, *, bleed: bool) -> tuple[str, str]:
    """The page-size and page-margin elements for this trim, as Word XML."""
    width = int(round(trim.width_in * TWIPS_PER_INCH))
    height = int(round(trim.height_in * TWIPS_PER_INCH))
    outside = OUTSIDE_MARGIN_BLEED_IN if bleed else OUTSIDE_MARGIN_IN
    page_size = f'<w:pgSz w:w="{width}" w:h="{height}"/>'
    margins = (
        '<w:pgMar '
        f'w:top="{int(round(TOP_BOTTOM_MARGIN_IN * TWIPS_PER_INCH))}" '
        f'w:right="{int(round(outside * TWIPS_PER_INCH))}" '
        f'w:bottom="{int(round(TOP_BOTTOM_MARGIN_IN * TWIPS_PER_INCH))}" '
        f'w:left="{int(round(outside * TWIPS_PER_INCH))}" '
        f'w:header="720" w:footer="720" '
        f'w:gutter="{int(round(gutter_in * TWIPS_PER_INCH))}"/>'
    )
    return page_size, margins


def make_print_interior(source_docx: str | Path, target_docx: str | Path, *,
                        trim_key: str = DEFAULT_TRIM, page_count: int = 0,
                        word_count: int = 0, bleed: bool = False) -> dict[str, Any]:
    """Write a copy of the manuscript laid out for print.

    Only the section properties are rewritten; the text, images and styles are
    left exactly as the factory produced them. Word and KDP re-flow the content
    onto the new page size when the file is opened or converted, which is why
    this does not attempt to repaginate anything itself.
    """
    trim = TRIMS.get(trim_key)
    if trim is None:
        raise ValueError(f"Unknown KDP trim {trim_key!r}; known: {', '.join(TRIMS)}")
    source, target = Path(source_docx), Path(target_docx)
    if not source.is_file():
        raise FileNotFoundError(f"No manuscript at {source}")

    pages = page_count or estimate_pages(word_count)
    gutter = gutter_for(pages or PAPERBACK_PAGES[0])
    page_size, margins = _sect_pr_replacement(trim, gutter, bleed=bleed)

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)

    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        parts = {name: archive.read(name) for name in names}

    document = parts["word/document.xml"].decode("utf-8")
    sizes = len(re.findall(r"<w:pgSz\b[^/]*/>", document))
    document = re.sub(r"<w:pgSz\b[^/]*/>", page_size, document)
    document = re.sub(r"<w:pgMar\b[^/]*/>", margins, document)
    document, shrunk = _fit_images(document, trim, gutter, bleed=bleed)
    parts["word/document.xml"] = document.encode("utf-8")

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
        for name in names:
            out.writestr(name, parts[name])

    return {"path": str(target), "trim": trim.name, "trim_key": trim_key,
            "sections_rewritten": sizes, "gutter_in": gutter,
            "outside_margin_in": OUTSIDE_MARGIN_BLEED_IN if bleed else OUTSIDE_MARGIN_IN,
            "images_resized": shrunk,
            "page_count_used": pages, **eligible_formats(pages)}


EMU_PER_INCH = 914400


def text_width_in(trim: Trim, gutter_in: float, *, bleed: bool = False) -> float:
    """How wide the text column actually is once the margins are taken out."""
    outside = OUTSIDE_MARGIN_BLEED_IN if bleed else OUTSIDE_MARGIN_IN
    return trim.width_in - gutter_in - outside - outside


def _fit_images(document: str, trim: Trim, gutter_in: float,
                *, bleed: bool = False) -> tuple[str, int]:
    """Shrink any image wider than the text column, keeping its proportions.

    Rewriting the section properties re-flows the text onto the new page and
    does nothing at all to the pictures, which keep the size they were given
    for A4. On the 2026-09-24 book that left four of five images between 5.1
    and 5.7 inches wide on a column 4.875 inches across, and KDP's own print
    previewer refused the paperback: image outside the margins on pages 11, 27
    and 35, object outside the margins on thirteen more, and an insufficient
    gutter where the overflow ran into the binding edge.

    Both extents are rewritten. wp:extent is what the layout reserves and a:ext
    is what the picture is drawn at; changing one and not the other scales the
    frame without the image inside it, or the reverse.
    """
    limit = int(text_width_in(trim, gutter_in, bleed=bleed) * EMU_PER_INCH)
    resized = 0

    def scale(match: re.Match[str]) -> str:
        nonlocal resized
        tag, cx, cy = match.group(1), int(match.group(2)), int(match.group(3))
        if cx <= limit:
            return match.group(0)
        resized += 1
        return f'<{tag} cx="{limit}" cy="{round(cy * limit / cx)}"/>'

    # Applied to both tags in one pass so a drawing cannot end up half scaled.
    return re.sub(r'<(wp:extent|a:ext) cx="(\d+)" cy="(\d+)"\s*/>', scale, document), resized

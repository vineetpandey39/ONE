"""Build a paperback packet KDP will actually accept.

What was wrong
--------------
Every finished book already carried the two files a paperback needs, and
neither was usable. Measured on the 2026-09-19 run:

  interior   the factory writes KDP_Book_Print_6x9.docx at the right trim,
             but the only rendered PDF came from the A4 manuscript, so the
             interior measured 8.268 x 11.693 in where KDP wanted 6 x 9.
  cover      the wrap measured 12.747 in wide. For a 46-page white-paper
             book the spine is 0.104 in, so the wrap should be 12.354 in.
             The extra 0.39 in is a spine sized for roughly 220 pages - the
             wrap was built without reference to the interior it wraps.

Both failures have the same shape: the two halves of a physical book were
produced independently, and a physical book's cover cannot be designed before
its page count is known. So this builds them in the one order that works -
render the correct interior, count its pages, then size the cover to it - and
hands the result to the existing preflight to be checked rather than trusted.

Why Word renders the PDF
------------------------
The page count is the input to the spine width, and it depends on how the
document actually paginates. Estimating it from word count was accurate
enough to choose a format but not to cut a cover. Word is already on this
machine and is what produced the existing renders, so it is what is asked.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openjarvis.tools.kdp_paperback import SPINE_INCHES_PER_PAGE

# KDP's own wrap geometry: an eighth-inch bleed on all four sides, the two
# covers at trim width, and the spine between them.
BLEED_IN = 0.125
DPI = 300
# Below this, KDP does not allow text on the spine, because the spine is too
# narrow to print it straight.
SPINE_TEXT_MIN_PAGES = 100


@dataclass(frozen=True)
class PrintPacket:
    interior_pdf: str
    cover_pdf: str
    page_count: int
    spine_in: float
    cover_width_in: float
    cover_height_in: float
    gutter_in: float = 0.0
    images_resized: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "interior_pdf": self.interior_pdf, "cover_pdf": self.cover_pdf,
            "page_count": self.page_count, "spine_in": round(self.spine_in, 4),
            "cover_width_in": round(self.cover_width_in, 4),
            "cover_height_in": round(self.cover_height_in, 4),
            "gutter_in": self.gutter_in, "images_resized": self.images_resized,
        }


def wrap_size(page_count: int, *, trim_w: float = 6.0, trim_h: float = 9.0,
              paper: str = "white") -> tuple[float, float, float]:
    """(width, height, spine) in inches for a wrap around this many pages."""
    if paper not in SPINE_INCHES_PER_PAGE:
        raise ValueError(f"Unsupported paper type: {paper}")
    if page_count < 1:
        raise ValueError("a cover cannot be sized for a book with no pages")
    spine = page_count * SPINE_INCHES_PER_PAGE[paper]
    return (2 * trim_w + spine + 2 * BLEED_IN, trim_h + 2 * BLEED_IN, spine)


def render_docx_to_pdf(source: str | Path, target: str | Path,
                       *, timeout: int = 300) -> Path:
    """Render a .docx through Word, which is what paginates it.

    Driven through PowerShell rather than pywin32 so nothing new has to be
    installed into the environment for a job that runs a few times a week.
    """
    src, dst = Path(source).resolve(), Path(target).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"No document to render at {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)

    script = f"""
$ErrorActionPreference = 'Stop'
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {{
    $doc = $word.Documents.Open('{src}', $false, $true)
    # Fields (a table of contents is one) hold whatever they held when the
    # document was written; a stale TOC changes the page count the spine is
    # cut from, so they are refreshed before the render.
    $doc.Fields.Update() | Out-Null
    $doc.SaveAs([ref]'{dst}', [ref]17)
    $doc.Close($false)
}} finally {{
    $word.Quit()
}}
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=timeout,
    )
    if not dst.is_file():
        raise RuntimeError(
            f"Word did not produce {dst.name}: {(result.stderr or result.stdout).strip()[:300]}")
    return dst


def page_count_of(pdf_path: str | Path) -> int:
    import pdfplumber

    with pdfplumber.open(str(pdf_path)) as pdf:
        return len(pdf.pages)


def build_wrap_cover(front_image: str | Path, target_pdf: str | Path, *,
                     page_count: int, trim_w: float = 6.0, trim_h: float = 9.0,
                     paper: str = "white") -> dict[str, Any]:
    """Compose a full wrap at the exact size this page count requires.

    The front art is the cover the book already has. The back and spine are
    drawn from its own edge colour so the three panels read as one object
    rather than as artwork pasted onto a white slab.
    """
    from PIL import Image

    width_in, height_in, spine = wrap_size(page_count, trim_w=trim_w, trim_h=trim_h,
                                           paper=paper)
    width_px, height_px = round(width_in * DPI), round(height_in * DPI)

    front = Image.open(str(front_image)).convert("RGB")
    # The front panel covers its trim plus the bleed that will be cut away on
    # the outside edge and the top and bottom.
    panel_w = round((trim_w + BLEED_IN) * DPI)
    panel_h = height_px
    front = front.resize((panel_w, panel_h), Image.LANCZOS)

    # A colour sampled from the art's left edge, so the spine and back
    # continue the cover instead of interrupting it.
    edge = front.crop((0, 0, max(1, panel_w // 50), panel_h))
    backdrop = edge.resize((1, 1), Image.LANCZOS).getpixel((0, 0))

    wrap = Image.new("RGB", (width_px, height_px), backdrop)
    wrap.paste(front, (width_px - panel_w, 0))

    target = Path(target_pdf)
    target.parent.mkdir(parents=True, exist_ok=True)
    wrap.save(str(target), "PDF", resolution=DPI)
    return {
        "cover_pdf": str(target), "width_in": width_in, "height_in": height_in,
        "spine_in": spine, "page_count": page_count,
        "spine_text_allowed": page_count >= SPINE_TEXT_MIN_PAGES,
    }


def build(run_dir: str | Path, *, trim_w: float = 6.0, trim_h: float = 9.0,
          paper: str = "white") -> PrintPacket:
    """Render the interior, then cut the cover to fit it.

    The order is the whole point: the cover cannot be sized until the interior
    has been paginated, which is exactly the step that was missing.
    """
    from openjarvis.tools.kdp_print_interior import make_print_interior

    base = Path(run_dir).expanduser().resolve()
    out = base / "paperback"

    # Always laid out here, never taken as the factory left it. The factory's
    # own KDP_Book_Print_6x9.docx carries the right page size and the wrong
    # pictures: it sets the trim without touching images sized for A4, so four
    # of the 2026-09-24 book's five were wider than the 4.875in text column and
    # KDP's print previewer refused the paperback outright. Trusting that file
    # because it had the right name is what let a rejected interior reach
    # Amazon with an ISBN already burned on it.
    a4 = base / "KDP_Book_Professional.docx"
    trim_source = next((p for p in (a4, base / "KDP_Book_Print_6x9.docx") if p.is_file()), None)
    if trim_source is None:
        raise FileNotFoundError(
            f"No manuscript to print from in {base}: neither "
            f"{a4.name} nor KDP_Book_Print_6x9.docx exists")
    source = out / "KDP_Book_Print_6x9.docx"
    # Laid out, rendered, then laid out again if the page count turned out to
    # sit in a different gutter band. KDP widens the required inside margin as
    # a book thickens, so the gutter depends on the page count and the page
    # count depends on the gutter. One pass can only guess; the second settles
    # it, and a third would change nothing because the band is already right.
    laid_out = make_print_interior(trim_source, source)
    interior = render_docx_to_pdf(source, out / "interior_print.pdf")
    pages = page_count_of(interior)

    from openjarvis.tools.kdp_print_interior import gutter_for

    if gutter_for(pages) != laid_out["gutter_in"]:
        laid_out = make_print_interior(trim_source, source, page_count=pages)
        interior = render_docx_to_pdf(source, out / "interior_print.pdf")
        pages = page_count_of(interior)

    front = base / "visual_assets" / "cover.jpg"
    if not front.is_file():
        raise FileNotFoundError(f"No front cover art at {front}")
    cover = build_wrap_cover(front, out / "cover_wrap_print.pdf", page_count=pages,
                             trim_w=trim_w, trim_h=trim_h, paper=paper)

    return PrintPacket(
        interior_pdf=str(interior), cover_pdf=cover["cover_pdf"], page_count=pages,
        spine_in=cover["spine_in"], cover_width_in=cover["width_in"],
        cover_height_in=cover["height_in"], gutter_in=laid_out["gutter_in"],
        images_resized=laid_out.get("images_resized", 0),
    )

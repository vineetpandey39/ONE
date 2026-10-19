"""Build-time validation for KDP paperback artifacts.

The book factory historically emitted files named ``cover_wrap_print.pdf``
and an interior PDF, but their existence did not prove that they belonged to
the same physical edition.  This module derives the required cover geometry
from the *actual* interior page count and refuses mismatched packets.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pdfplumber


SPINE_INCHES_PER_PAGE = {
    "white": 0.002252,
    "cream": 0.0025,
    "color": 0.002347,
}


@dataclass(frozen=True)
class PaperbackPreflight:
    ready: bool
    interior_path: str
    cover_path: str
    page_count: int
    trim_width_in: float
    trim_height_in: float
    bleed: bool
    paper: str
    spine_width_in: float
    expected_cover_width_in: float
    expected_cover_height_in: float
    actual_interior_width_in: float
    actual_interior_height_in: float
    actual_cover_width_in: float
    actual_cover_height_in: float
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _page_size(pdf: pdfplumber.PDF, label: str) -> tuple[float, float]:
    if not pdf.pages:
        raise ValueError(f"{label} PDF has no pages")
    first = pdf.pages[0]
    size = (float(first.width) / 72.0, float(first.height) / 72.0)
    for number, page in enumerate(pdf.pages[1:], start=2):
        candidate = (float(page.width) / 72.0, float(page.height) / 72.0)
        if abs(candidate[0] - size[0]) > 0.01 or abs(candidate[1] - size[1]) > 0.01:
            raise ValueError(f"{label} PDF page {number} has inconsistent dimensions")
    return size


def preflight_paperback(
    run_dir: str | Path,
    *,
    trim_width_in: float = 6.0,
    trim_height_in: float = 9.0,
    bleed: bool = False,
    paper: str = "white",
    tolerance_in: float = 0.03,
) -> PaperbackPreflight:
    base = Path(run_dir).expanduser().resolve()
    interiors = (
        base / "paperback" / "interior_print.pdf",
        base / "toc-render" / "KDP_Book_Professional-v2.pdf",
        base / "toc-render" / "KDP_Book_Professional.pdf",
    )
    covers = (
        base / "paperback" / "cover_wrap_print.pdf",
        base / "visual_assets" / "cover_wrap_print.pdf",
    )
    interior = next((path for path in interiors if path.is_file()), None)
    cover = next((path for path in covers if path.is_file()), None)
    if interior is None or cover is None:
        missing = []
        if interior is None:
            missing.append("print interior PDF")
        if cover is None:
            missing.append("full-wrap cover PDF")
        raise ValueError("Incomplete paperback packet: missing " + ", ".join(missing))
    if paper not in SPINE_INCHES_PER_PAGE:
        raise ValueError(f"Unsupported paperback paper type: {paper}")

    with pdfplumber.open(interior) as interior_pdf:
        page_count = len(interior_pdf.pages)
        interior_width, interior_height = _page_size(interior_pdf, "Interior")
    with pdfplumber.open(cover) as cover_pdf:
        if len(cover_pdf.pages) != 1:
            raise ValueError("Full-wrap cover PDF must contain exactly one page")
        cover_width, cover_height = _page_size(cover_pdf, "Cover")

    spine = page_count * SPINE_INCHES_PER_PAGE[paper]
    expected_interior = (
        trim_width_in + (0.125 if bleed else 0.0),
        trim_height_in + (0.25 if bleed else 0.0),
    )
    expected_cover = (2 * trim_width_in + spine + 0.25, trim_height_in + 0.25)
    errors: list[str] = []
    if page_count < 24:
        errors.append(f"Interior has {page_count} pages; paperback requires at least 24")
    if abs(interior_width - expected_interior[0]) > tolerance_in or abs(interior_height - expected_interior[1]) > tolerance_in:
        errors.append(
            f"Interior is {interior_width:.3f} x {interior_height:.3f} in; "
            f"expected {expected_interior[0]:.3f} x {expected_interior[1]:.3f} in"
        )
    if abs(cover_width - expected_cover[0]) > tolerance_in or abs(cover_height - expected_cover[1]) > tolerance_in:
        errors.append(
            f"Cover is {cover_width:.3f} x {cover_height:.3f} in; expected "
            f"{expected_cover[0]:.3f} x {expected_cover[1]:.3f} in for "
            f"{page_count} {paper}-paper pages (spine {spine:.3f} in)"
        )

    result = PaperbackPreflight(
        ready=not errors,
        interior_path=str(interior), cover_path=str(cover), page_count=page_count,
        trim_width_in=trim_width_in, trim_height_in=trim_height_in,
        bleed=bleed, paper=paper, spine_width_in=round(spine, 4),
        expected_cover_width_in=round(expected_cover[0], 4),
        expected_cover_height_in=round(expected_cover[1], 4),
        actual_interior_width_in=round(interior_width, 4),
        actual_interior_height_in=round(interior_height, 4),
        actual_cover_width_in=round(cover_width, 4),
        actual_cover_height_in=round(cover_height, 4), errors=errors,
    )
    report_dir = base / "paperback"
    report_dir.mkdir(exist_ok=True)
    (report_dir / "preflight.json").write_text(
        json.dumps(result.to_dict(), indent=2), encoding="utf-8"
    )
    return result


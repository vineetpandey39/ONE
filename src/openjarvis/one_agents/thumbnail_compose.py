"""Final step of the Sonia thumbnail: fit the generated background to 1280x720 and set the hook text.

The image model is told to render no text, so the words are exact and mobile-legible. They are drawn here, on the
side opposite Sonia (left or right), with a heavy outline, a soft shadow and a contrast gradient behind them.
Returns a QC dict the gate can read.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SIZE = (1280, 720)
# Noto Sans Bold includes the Indian rupee glyph used by travel-price hooks.
# Impact/Arial Black render it as a missing-glyph box on common Windows hosts.
FONT_CANDIDATES = (r"C:\Windows\Fonts\NotoSans-Bold.ttf", r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\impact.ttf")
TEXT_ZONE = 0.62          # the hook may use at most this share of the width, on its own side
MARGIN = 48
LEFT_MARGIN = MARGIN       # kept for callers that read it
MAX_TEXT_WIDTH = int(SIZE[0] * TEXT_ZONE) - MARGIN
MIN_FONT = 96
MAX_BYTES = 2 * 1024 * 1024
WHITE, ACCENT, OUTLINE = (255, 255, 255), (255, 214, 0), (0, 0, 0)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    raise RuntimeError("No bold font available for thumbnail text")


def _cover(img: Image.Image) -> Image.Image:
    scale = max(SIZE[0] / img.width, SIZE[1] / img.height)
    resized = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left, top = (resized.width - SIZE[0]) // 2, (resized.height - SIZE[1]) // 2
    return resized.crop((left, top, left + SIZE[0], top + SIZE[1]))


def _line_width(line: str, font: ImageFont.FreeTypeFont, draw: ImageDraw.ImageDraw) -> int:
    """Width exactly as the line is drawn (token by token), so the fit check and the drawing agree.

    The fit used to measure the line as one string while drawing it word by word; "NEW FLIGHTS" (Air France,
    2026-10-09) passed the fit and was drawn 14 px past its zone, failing QC on a thumbnail that was uploaded."""
    tokens = line.split(" ")
    return int(sum(draw.textlength(t + " ", font=font) for t in tokens) - draw.textlength(" ", font=font))


def _wrap(words: list[str], font: ImageFont.FreeTypeFont, draw: ImageDraw.ImageDraw, stroke: int) -> list[str] | None:
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if _line_width(trial, font, draw) + 2 * stroke <= MAX_TEXT_WIDTH:
            current = trial
        else:
            if not current:
                return None  # a single word is wider than the allowed block
            lines.append(current)
            current = word
            # A word moved to a new line was never measured on its own: "FLIGHTS" then ran past the zone.
            if _line_width(current, font, draw) + 2 * stroke > MAX_TEXT_WIDTH:
                return None
    lines.append(current)
    return lines


def _contrast_gradient(img: Image.Image, side: str) -> Image.Image:
    """Darken the text side softly, so the hook reads over any sky or street without a hard box."""
    shade = Image.new("L", SIZE, 0)
    draw = ImageDraw.Draw(shade)
    reach = int(SIZE[0] * TEXT_ZONE)  # never darken Sonia's side
    for i in range(reach):
        alpha = int(150 * (1 - i / reach) ** 1.6)
        x = i if side == "left" else SIZE[0] - 1 - i
        draw.line((x, 0, x, SIZE[1]), fill=alpha)
    dark = Image.new("RGB", SIZE, (0, 0, 0))
    return Image.composite(dark, img, shade)


def compose(base: Path, text: str, out: Path, *, primary: tuple[int, int, int] = WHITE,
            accent: tuple[int, int, int] = ACCENT, side: str = "left") -> dict[str, Any]:
    """Set the hook on `side` ('left' when Sonia is on the right, 'right' when she is on the left)."""
    if side not in ("left", "right"):
        raise ValueError("side must be 'left' or 'right'")
    words = text.upper().split()
    if not 1 <= len(words) <= 4:
        raise ValueError("thumbnail text must be 1 to 4 words")
    img = _contrast_gradient(_cover(Image.open(base).convert("RGB")), side)
    draw = ImageDraw.Draw(img)
    chosen = None
    for size in range(190, MIN_FONT - 1, -6):
        font, stroke = _font(size), max(6, size // 12)
        lines = _wrap(words, font, draw, stroke)
        if not lines or len(lines) > 3:
            continue
        line_h = draw.textbbox((0, 0), "HG", font=font, stroke_width=stroke)[3]
        block_h = line_h * len(lines) + int(size * 0.08) * (len(lines) - 1)
        if block_h <= SIZE[1] * 0.62:
            chosen = (size, font, stroke, lines, line_h, block_h)
            break
    if not chosen:
        raise ValueError("thumbnail text cannot be set at a readable size; shorten it")
    size, font, stroke, lines, line_h, block_h = chosen
    # Two-tone punch: a number (price, days) is the accent; with no number, the last word is.
    has_digit = any(any(c.isdigit() for c in w) for w in words)
    last = words[-1]

    def colour_for(token: str) -> tuple[int, int, int]:
        if has_digit:
            return accent if any(c.isdigit() for c in token) else primary
        return accent if token == last else primary

    # Keep the lower-middle clear for a host's pointing hand/gesture.
    y0 = max(70, (SIZE[1] - block_h) // 2 - 90)
    placements, y = [], y0
    for line in lines:
        width = _line_width(line, font, draw)
        x = MARGIN if side == "left" else SIZE[0] - MARGIN - width
        placements.append((line, x, y, width))
        y += line_h + int(size * 0.08)

    shadow = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for line, x, y, _ in placements:
        sd.text((x + 8, y + 10), line, font=font, fill=(0, 0, 0, 170), stroke_width=stroke, stroke_fill=(0, 0, 0, 170))
    img = Image.alpha_composite(img.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(9))).convert("RGB")
    draw = ImageDraw.Draw(img)
    left_edge, right_edge = SIZE[0], 0
    for line, x, y, width in placements:
        cursor = x
        for token in line.split(" "):
            draw.text((cursor, y), token, font=font, fill=colour_for(token), stroke_width=stroke, stroke_fill=OUTLINE)
            cursor += int(draw.textlength(token + " ", font=font))
        left_edge, right_edge = min(left_edge, x - stroke), max(right_edge, x + width + stroke)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    final = out
    if out.stat().st_size > MAX_BYTES:
        final = out.with_suffix(".jpg")
        img.save(final, "JPEG", quality=90, optimize=True)
    inside = (right_edge <= SIZE[0] * TEXT_ZONE) if side == "left" else (left_edge >= SIZE[0] * (1 - TEXT_ZONE))
    qc = {"size": list(SIZE), "font_size": size, "lines": lines, "side": side,
          "text_left_edge": left_edge, "text_right_edge": right_edge,
          "inside_text_zone": inside, "inside_left_zone": inside,  # old name, read by older receipts and scoring
          "readable": size >= MIN_FONT,
          "bytes": final.stat().st_size, "under_2mb": final.stat().st_size <= MAX_BYTES}
    qc["ok"] = bool(qc["inside_text_zone"] and qc["readable"] and qc["under_2mb"])
    return {"path": str(final), "qc": qc}

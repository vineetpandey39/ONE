"""Final step of the Sonia thumbnail: fit the generated background to 1280x720 and set the hook text.

The image model is told to render no text, so the words are exact and mobile-legible. They are drawn here, on the
side opposite Sonia (left or right), with a heavy outline, a soft shadow and a contrast gradient behind them.
Returns a QC dict the gate can read.
"""
from __future__ import annotations

import colorsys
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

SIZE = (1280, 720)
# Noto Sans Bold includes the Indian rupee glyph used by travel-price hooks.
# Impact/Arial Black render it as a missing-glyph box on common Windows hosts.
FONT_CANDIDATES = (r"C:\Windows\Fonts\NotoSans-Bold.ttf", r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\impact.ttf")
# MrBeast-style hierarchy: a short hook gets its own narrow lane, the story's
# hero object stays visible in the middle, and Sonia owns the right.  The old
# 62% lane put giant type directly over the plane/landmark it was meant to sell.
TEXT_ZONE = 0.38
USP_ZONE = (0.38, 0.66)   # protected from the deterministic text overlay
MARGIN = 48
LEFT_MARGIN = MARGIN       # kept for callers that read it
MAX_TEXT_WIDTH = int(SIZE[0] * TEXT_ZONE) - MARGIN
MIN_FONT = 96
MAX_BYTES = 2 * 1024 * 1024
WHITE, ACCENT, OUTLINE = (255, 255, 255), (255, 214, 0), (0, 0, 0)
PLANEXIUM_ACCENTS = (
    (70, 220, 255),   # electric cyan
    (255, 92, 184),   # cosmic magenta
    (152, 255, 112),  # aurora green
    (255, 148, 70),   # solar orange
    (190, 150, 255),  # ultraviolet
    ACCENT,
)


def adaptive_science_accent(base: Path, recent: list[tuple[int, int, int]] | None = None) -> tuple[int, int, int]:
    """Choose a vivid complementary accent and avoid repeating recent channel colours."""
    image = Image.open(base).convert("RGB").resize((160, 90), Image.Resampling.LANCZOS)
    x = y = weight_sum = 0.0
    for red, green, blue in image.getdata():
        hue, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
        weight = saturation * (0.25 + value)
        if weight < 0.12:
            continue
        angle = hue * 2 * math.pi
        x += math.cos(angle) * weight
        y += math.sin(angle) * weight
        weight_sum += weight
    dominant = ((math.atan2(y, x) / (2 * math.pi)) % 1.0) if weight_sum else 0.58
    recent = recent or []

    def circular_distance(a: float, b: float) -> float:
        delta = abs(a - b)
        return min(delta, 1.0 - delta)

    def score(candidate: tuple[int, int, int]) -> float:
        hue, saturation, value = colorsys.rgb_to_hsv(*(channel / 255 for channel in candidate))
        complementary = circular_distance(hue, dominant)
        repeated = sum(1 for old in recent[-6:] if sum((old[i] - candidate[i]) ** 2 for i in range(3)) ** 0.5 < 75)
        return complementary * 3.0 + saturation * 0.5 + value * 0.2 - repeated * 1.25

    return max(PLANEXIUM_ACCENTS, key=score)


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


def _wrap(words: list[str], font: ImageFont.FreeTypeFont, draw: ImageDraw.ImageDraw, stroke: int,
          max_text_width: int = MAX_TEXT_WIDTH) -> list[str] | None:
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if _line_width(trial, font, draw) + 2 * stroke <= max_text_width:
            current = trial
        else:
            if not current:
                return None  # a single word is wider than the allowed block
            lines.append(current)
            current = word
            # A word moved to a new line was never measured on its own: "FLIGHTS" then ran past the zone.
            if _line_width(current, font, draw) + 2 * stroke > max_text_width:
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


def _low_detail_y(img: Image.Image, block_h: int, side: str,
                  text_zone: float = TEXT_ZONE) -> tuple[int, int]:
    """Choose the quietest top/middle/bottom slot inside the text lane.

    This is deliberately based on the actual generated pixels. A fixed vertical
    placement covered aircraft, landmarks and documents even when their prompt
    asked the image model to reserve a text lane. Edge energy is a conservative
    proxy for visual detail: the hook goes where it hides the least information.
    """
    pad = 38
    maximum = max(pad, SIZE[1] - block_h - pad)
    candidates = sorted({pad, max(pad, (SIZE[1] - block_h) // 2), maximum})
    lane = int(SIZE[0] * text_zone)
    x0, x1 = ((0, lane) if side == "left" else (SIZE[0] - lane, SIZE[0]))
    edges = img.convert("L").filter(ImageFilter.FIND_EDGES)
    scored = []
    for order, y in enumerate(candidates):
        crop = edges.crop((x0, y, x1, min(SIZE[1], y + block_h)))
        energy = float(ImageStat.Stat(crop).mean[0]) if crop.size[0] and crop.size[1] else 255.0
        scored.append((energy, order, y))
    energy, _order, y = min(scored)
    return y, round(energy)


def compose(base: Path, text: str, out: Path, *, primary: tuple[int, int, int] = WHITE,
            accent: tuple[int, int, int] = ACCENT, side: str = "left",
            vertical_anchor: str = "bottom", text_zone: float = TEXT_ZONE,
            min_font: int = MIN_FONT, max_words: int = 3) -> dict[str, Any]:
    """Set the hook on `side` ('left' when Sonia is on the right, 'right' when she is on the left)."""
    if side not in ("left", "right"):
        raise ValueError("side must be 'left' or 'right'")
    if vertical_anchor not in ("top", "middle", "bottom", "adaptive"):
        raise ValueError("vertical_anchor must be top, middle, bottom or adaptive")
    if not 0.30 <= text_zone <= 0.52:
        raise ValueError("text_zone must be between 0.30 and 0.52")
    if not 84 <= min_font <= MIN_FONT:
        raise ValueError("minimum thumbnail font must remain between 84 and 96 pixels")
    max_text_width = int(SIZE[0] * text_zone) - MARGIN
    words = text.upper().split()
    if max_words not in (3, 4):
        raise ValueError("thumbnail max_words must be 3 or 4")
    if not 1 <= len(words) <= max_words:
        raise ValueError(f"thumbnail text must be 1 to {max_words} words")
    # Preserve the story pixels. Readability comes from the heavy outline and
    # local shadow, not from darkening the entire side (which used to hide the
    # very aircraft/landmark the thumbnail was selling).
    img = _cover(Image.open(base).convert("RGB"))
    draw = ImageDraw.Draw(img)
    chosen = None
    sizes = list(range(190, min_font - 1, -6))
    if min_font not in sizes:
        sizes.append(min_font)
    for size in sizes:
        font, stroke = _font(size), max(6, size // 12)
        lines = _wrap(words, font, draw, stroke, max_text_width)
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

    adaptive_y, detail_energy = _low_detail_y(img, block_h, side, text_zone)
    anchors = {"top": 38, "middle": max(38, (SIZE[1] - block_h) // 2),
               "bottom": max(38, SIZE[1] - block_h - 38)}
    y0 = adaptive_y if vertical_anchor == "adaptive" else anchors[vertical_anchor]
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
    inside = (right_edge <= SIZE[0] * text_zone) if side == "left" else (left_edge >= SIZE[0] * (1 - text_zone))
    qc = {"size": list(SIZE), "font_size": size, "lines": lines, "side": side,
          "primary_colour": list(primary), "accent_colour": list(accent),
          "text_left_edge": left_edge, "text_right_edge": right_edge,
          "inside_text_zone": inside, "inside_left_zone": inside,  # old name, read by older receipts and scoring
          "readable": size >= min_font,
          "minimum_font_size": min_font,
          "protected_usp_zone": [round(SIZE[0] * USP_ZONE[0]), round(SIZE[0] * USP_ZONE[1])],
          "text_clear_of_usp": inside,
          "text_zone": text_zone,
          "vertical_anchor": vertical_anchor,
          "adaptive_low_detail_anchor": vertical_anchor == "adaptive",
          "text_y": y0,
          "text_lane_edge_energy": detail_energy,
          "bytes": final.stat().st_size, "under_2mb": final.stat().st_size <= MAX_BYTES}
    qc["ok"] = bool(qc["inside_text_zone"] and qc["text_clear_of_usp"]
                    and qc["readable"] and qc["under_2mb"])
    return {"path": str(final), "qc": qc}

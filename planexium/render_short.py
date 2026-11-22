#!/usr/bin/env python3
"""Planexium short renderer.

Burns the hook text, the live meter, the sublabels and the end reveal onto a
9:16 background clip (e.g. a Seedance / Kling generation) and adds a rising
drone with an impact at the reveal.

    python3 render_short.py mars --bg mars_clip.mp4 -o out/mars.mp4
    python3 render_short.py mars --demo -o out/mars_demo.mp4   # procedural planet, no clip needed

AI video models cannot draw a counter that changes accurately, so the numbers
are always added here, in post.
"""
import argparse, json, math, os, re, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS = 1080, 1920, 30
HERE = os.path.dirname(os.path.abspath(__file__))
GREEN = (126, 217, 87)
WHITE = (255, 255, 255)

WINF = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts")
MACF = "/System/Library/Fonts/Supplemental"
FONT_HOOK = ["/usr/share/fonts/opentype/inter/InterDisplay-Black.otf", os.path.join(WINF, "ariblk.ttf"),
             os.path.join(MACF, "Arial Black.ttf"), "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
FONT_NUM = FONT_HOOK
FONT_TXT = ["/usr/share/fonts/opentype/inter/Inter-SemiBold.otf", os.path.join(WINF, "seguisb.ttf"), os.path.join(WINF, "arialbd.ttf"),
            os.path.join(MACF, "Arial Bold.ttf"), "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
try:
    from PIL import features as _pf
    TNUM = {"features": ["tnum"]} if _pf.check("raqm") else {}
except Exception:
    TNUM = {}


def font(cands, size, override=None):
    for p in ([override] if override else []) + cands:
        if p and os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def ease(x):
    return x * x * (3 - 2 * x)


def interp(keys, t):
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t0 <= t <= t1:
            k = ease((t - t0) / (t1 - t0)) if t1 > t0 else 1
            # log-ish interpolation for values spanning orders of magnitude
            if v0 > 0 and v1 > 0 and max(v0, v1) / min(v0, v1) > 50:
                return math.exp(math.log(v0) + (math.log(v1) - math.log(v0)) * k)
            return v0 + (v1 - v0) * k
    return keys[-1][1]


def tokens(text):
    """'A *B C* D' -> [(word, is_green)]"""
    out, green = [], False
    for part in re.split(r"(\*)", text):
        if part == "*":
            green = not green
            continue
        for chunk in re.split(r"(\|)", part):
            out += [("\n", False)] if chunk == "|" else [(w, green) for w in chunk.split()]
    return out


def fit(d, text, f, maxw, min_size):
    """Shrink f until every forced (|) line fits maxw, but not below min_size."""
    longest = max(text.replace("*", "").split("|"), key=lambda s: d.textlength(s, font=f))
    while d.textlength(longest, font=f) > maxw and f.size > min_size:
        f = f.font_variant(size=f.size - 2)
    return f


def draw_rich(d, text, f, cx, y, maxw, alpha=255, line_gap=1.08, min_size=None):
    if min_size:
        f = fit(d, text, f, maxw, min_size)
    words, lines, cur = tokens(text), [], []
    space = d.textlength(" ", font=f)
    for w in words:
        if w[0] == "\n":
            lines.append(cur); cur = []
            continue
        trial = cur + [w]
        if cur and sum(d.textlength(x, font=f) for x, _ in trial) + space * (len(trial) - 1) > maxw:
            lines.append(cur)
            cur = [w]
        else:
            cur = trial
    if cur:
        lines.append(cur)
    lh = int(f.size * line_gap)
    for ln in lines:
        lw = sum(d.textlength(x, font=f) for x, _ in ln) + space * (len(ln) - 1)
        x = cx - lw / 2
        for w, g in ln:
            col = (GREEN if g else WHITE) + (alpha,)
            d.text((x, y), w, font=f, fill=col, stroke_width=3, stroke_fill=(0, 0, 0, int(alpha * 0.85)))
            x += d.textlength(w, font=f) + space
        y += lh
    return y


def fade(t, start, dur=0.4):
    return max(0.0, min(1.0, (t - start) / dur))


class Overlay:
    def __init__(self, cfg, brand, total, hook_font=None):
        self.c, self.brand, self.total = cfg, brand, total
        self.f_hook = font(FONT_HOOK, 82, hook_font)
        self.f_reveal = font(FONT_HOOK, 96, hook_font)
        self.f_brand = font(FONT_TXT, 34)
        self.f_tease = font(FONT_TXT, 40)
        self.f_num = font(FONT_NUM, 120)
        self.f_lbl = font(FONT_TXT, 30)
        self.f_sub = font(FONT_TXT, 38)
        self.f_m2 = font(FONT_NUM, 50)
        # static top gradient
        g = np.zeros((H, W, 4), np.uint8)
        a = np.clip(1 - np.arange(H) / 760, 0, 1) ** 1.3 * 235
        g[..., 3] = a[:, None].astype(np.uint8)
        self.top_grad = Image.fromarray(g, "RGBA")

    def frame(self, t):
        c = self.c
        im = self.top_grad.copy()
        d = ImageDraw.Draw(im)
        rev = c["reveal_at"]
        # brand line
        bl = f"PLANEXIUM  ·  DAY {c['day']}/7"
        bw = d.textlength(bl, font=self.f_brand)
        y0 = 150
        d.line([(80, y0 + 20), (W / 2 - bw / 2 - 24, y0 + 20)], fill=WHITE + (200,), width=3)
        d.line([(W / 2 + bw / 2 + 24, y0 + 20), (W - 80, y0 + 20)], fill=WHITE + (200,), width=3)
        d.text((W / 2 - bw / 2, y0), bl, font=self.f_brand, fill=GREEN + (255,))
        # hook (whole video until reveal, then the "next" teaser)
        if t < rev:
            ya = draw_rich(d, c["hook"], self.f_hook, W / 2, 225, 990, min_size=62)
            if 0.6 < t < 7:
                a = int(255 * min(fade(t, 0.6), 1 - fade(t, 6.6)))
                draw_rich(d, c["tease"], self.f_tease, W / 2, ya + 18, 900, alpha=a)
        elif t > self.total - 3.2:
            draw_rich(d, c["next"], self.f_tease, W / 2, 240, 960, min_size=30, alpha=int(255 * fade(t, self.total - 3.2)))

        # meter (until shortly after the reveal)
        m_alpha = int(255 * (1 - fade(t, rev - 0.2, 0.5)))
        if m_alpha > 0:
            self.draw_meter(d, t, m_alpha)

        # reveal
        if t >= rev:
            k = fade(t, rev, 0.35)
            veil = Image.new("RGBA", (W, H), (0, 0, 0, int(150 * k)))
            im = Image.alpha_composite(im, veil)
            d = ImageDraw.Draw(im)
            draw_rich(d, c["reveal"], self.f_reveal, W / 2, 760 - 30 * (1 - k), 960, alpha=int(255 * k), min_size=70)
        return im

    def draw_meter(self, d, t, a):
        m = self.c["meter"]
        x, ytop, ybot = 470, 860, 1290
        # measuring line with end ticks (like the reference)
        d.line([(x, ytop), (x, ybot)], fill=WHITE + (int(a * 0.9),), width=3)
        for yy in (ytop, ybot):
            d.line([(x - 14, yy), (x + 14, yy)], fill=WHITE + (int(a * 0.9),), width=3)
        tx = x + 34
        d.text((tx, 905), m["label"], font=self.f_lbl, fill=(220, 220, 220, a))
        val = m["format"].format(interp(m["keys"], t))
        d.text((tx, 945), val, font=self.f_num, **TNUM, fill=WHITE + (a,), stroke_width=3, stroke_fill=(0, 0, 0, a))
        if m.get("unit"):
            nx = tx + d.textlength(val, font=self.f_num, **TNUM) + 14
            d.text((nx, 1010), m["unit"], font=self.f_sub, fill=WHITE + (a,), stroke_width=2, stroke_fill=(0, 0, 0, a))
        # sublabel (cross-fade between entries)
        subs = self.c.get("sublabels", [])
        cur = [s for s in subs if s[0] <= t]
        if cur:
            st, txt = cur[-1]
            sa = int(a * fade(t, st, 0.35))
            fs = self.f_sub
            while d.textlength(txt, font=fs) > W - tx - 40 and fs.size > 24:
                fs = fs.font_variant(size=fs.size - 2)
            d.text((tx, 1085), txt, font=fs, fill=GREEN + (sa,), stroke_width=2, stroke_fill=(0, 0, 0, sa))
        m2 = self.c.get("meter2")
        if m2:
            d.text((tx, 1165), m2["label"], font=self.f_lbl, fill=(200, 200, 200, a))
            d.text((tx, 1200), m2["format"].format(interp(m2["keys"], t)), font=self.f_m2, **TNUM, fill=WHITE + (a,), stroke_width=2, stroke_fill=(0, 0, 0, a))


# ---------- backgrounds ----------
def video_frames(path, total):
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-vf",
           f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}",
           "-t", str(total), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    last = None
    for _ in range(int(total * FPS)):
        buf = p.stdout.read(W * H * 3)
        if len(buf) == W * H * 3:
            last = Image.frombytes("RGB", (W, H), buf)
        yield last if last else Image.new("RGB", (W, H))
    p.stdout.close(); p.wait()


DEMO_PALETTES = {  # (start surface, end surface, start halo, end halo)
    "mars": ((40, 95, 170), (178, 82, 42), (120, 180, 255), (0, 0, 0)),
    "venus": ((50, 110, 170), (230, 170, 80), (150, 200, 255), (255, 190, 90)),
}


def demo_frames(name, total, cfg):
    rng = np.random.default_rng(7)
    stars = np.zeros((H, W, 3), np.float32)
    ys, xs = rng.integers(0, H, 900), rng.integers(0, W, 900)
    stars[ys, xs] = rng.uniform(80, 255, (900, 1))
    cx, cy, R = W / 2, 1080, 420
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    nx, ny = (xx - cx) / R, (yy - cy) / R
    r2 = nx ** 2 + ny ** 2
    inside = r2 <= 1
    nz = np.sqrt(np.clip(1 - r2, 0, 1))
    light = np.clip(nx * -0.55 + ny * -0.35 + nz * 0.75, 0, 1) ** 0.9
    lon0 = np.arctan2(nx, nz)
    lat = np.arcsin(np.clip(ny, -1, 1))
    s0, s1, h0, h1 = DEMO_PALETTES.get(name, DEMO_PALETTES["mars"])
    keys = cfg["meter"]["keys"]
    t_a, t_b = keys[1][0], keys[-2][0]
    rim = np.clip(1 - np.abs(np.sqrt(r2) - 1) / 0.08, 0, 1) * (np.sqrt(r2) > 0.97)
    for i in range(int(total * FPS)):
        t = i / FPS
        k = ease(min(1, max(0, (t - t_a) / (t_b - t_a))))
        lon = lon0 + t * 0.05
        noise = (np.sin(lon * 6 + np.sin(lat * 5) * 2) * np.cos(lat * 7 + lon * 2)) * 0.5 + 0.5
        ocean = (noise < 0.55 - 0.55 * k)  # water retreats
        base = np.array(s0) * (1 - k) + np.array(s1) * k
        land = np.array([150, 110, 70]) * (1 - k) + np.array(s1) * 1.1 * k
        col = np.where(ocean[..., None], base, land * (0.75 + 0.35 * noise[..., None]))
        img = stars.copy()
        img[inside] = (col * light[..., None])[inside]
        halo_c = np.array(h0) * (1 - k) + np.array(h1) * k
        img += rim[..., None] * halo_c * (1 - 0.9 * k) * 0.9
        # slow push-in
        im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
        z = 1 + 0.06 * t / total
        cw, ch = int(W / z), int(H / z)
        im = im.crop(((W - cw) // 2, (H - ch) // 2 + 40, (W + cw) // 2, (H + ch) // 2 + 40)).resize((W, H), Image.BILINEAR)
        yield im


# ---------- audio ----------
def make_audio(path, total, rev):
    """Rising sub drone that builds to the reveal, then a low impact."""
    import wave
    sr = 48000
    t = np.arange(int(sr * total)) / sr
    pre = (t < rev).astype(np.float32)
    post = 1 - pre
    sig = 0.22 * np.sin(2 * np.pi * (42 * t + 0.9 * t * t)) * np.minimum(1, t / 2) * pre
    sig += 0.10 * np.sin(2 * np.pi * (84.5 * t + 1.8 * t * t)) * pre * np.minimum(1, t / rev)
    sig += 0.04 * np.random.default_rng(1).standard_normal(t.size) * (t / rev) * pre
    tp = np.clip(t - rev, 0, None)
    sig += 0.7 * np.sin(2 * np.pi * (38 * tp - 6 * tp * tp)) * np.exp(-2.5 * tp) * post
    sig += 0.08 * np.sin(2 * np.pi * 55 * t) * post * np.minimum(1, tp)
    k = np.ones(48) / 48  # crude low-pass
    sig = np.convolve(sig, k, mode="same")
    sig *= np.clip((total - t) / 1.5, 0, 1)
    pcm = (np.clip(sig, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("short")
    ap.add_argument("--bg", help="background clip (any aspect; center-cropped to 9:16)")
    ap.add_argument("--demo", action="store_true", help="procedural placeholder planet")
    ap.add_argument("-o", "--out")
    ap.add_argument("--duration", type=float, default=30)
    ap.add_argument("--hook-font", help="path to a condensed display font, e.g. Anton-Regular.ttf")
    ap.add_argument("--no-audio", action="store_true")
    a = ap.parse_args()
    conf = json.load(open(os.path.join(HERE, "shorts.json")))
    cfg = conf["shorts"][a.short]
    out = a.out or os.path.join(HERE, "out", f"{a.short}.mp4")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    total = a.duration
    if not a.bg and not a.demo:
        sys.exit("pass --bg CLIP or --demo")
    frames = video_frames(a.bg, total) if a.bg else demo_frames(a.short, total, cfg)
    ov = Overlay(cfg, conf["brand"], total, a.hook_font)
    silent = out + ".video.mp4"
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264",
                            "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", silent],
                           stdin=subprocess.PIPE)
    for i, bg in enumerate(frames):
        fr = Image.alpha_composite(bg.convert("RGBA"), ov.frame(i / FPS)).convert("RGB")
        enc.stdin.write(fr.tobytes())
    enc.stdin.close(); enc.wait()
    if a.no_audio:
        os.replace(silent, out)
    else:
        wav = out + ".wav"
        make_audio(wav, total, cfg["reveal_at"])
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", silent, "-i", wav, "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "192k", "-shortest", out], check=True)
        os.remove(silent); os.remove(wav)
    print(out)


if __name__ == "__main__":
    main()

"""On-screen graphics - PIL se banate hain (ffmpeg drawtext is build me nahi hai).

Sab overlays transparent RGBA PNG hote hain; editor.py inhe ffmpeg `overlay`
se video ke upar lagata hai.
"""
import glob
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import env

_FONT_CACHE = {}

FONT_CANDIDATES = [
    os.environ.get("FONT_PATH") or "",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def find_font(size=48, bold=True):
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    cands = list(FONT_CANDIDATES)
    if not bold:
        cands.insert(1, "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    # matplotlib bundled DejaVu (always present)
    cands.append(str(Path(__file__).resolve().parent.parent / "assets" / "DejaVuSans-Bold.ttf"))
    for c in cands:
        if c and Path(c).exists():
            try:
                f = ImageFont.truetype(c, size)
                _FONT_CACHE[key] = f
                return f
            except Exception:  # noqa: BLE001
                continue
    # glob fallback
    for pat in ("/usr/share/fonts/**/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/**/*Sans*Bold*.ttf",
                "/usr/share/fonts/**/DejaVu*.ttf",
                "/usr/**/matplotlib/**/DejaVuSans-Bold.ttf"):
        hits = sorted(glob.glob(pat, recursive=True))
        if hits:
            f = ImageFont.truetype(hits[0], size)
            _FONT_CACHE[key] = f
            return f
    _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def banner(text, width, height=96, bg=(200, 16, 46), fg=(255, 255, 255), size=44):
    """Top headline bar (red accent + white bold text). RGBA PNG path."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, width, height], fill=(*bg, 235))
    d.rectangle([0, height - 6, width, height], fill=(*_hex("#ffd400"), 255))
    f = find_font(size)
    txt = " ".join(str(text).split())[:90]
    while d.textlength(txt, font=f) > width - 60 and len(txt) > 8:
        txt = txt[:-2]
    bbox = d.textbbox((0, 0), txt, font=f)
    ty = (height - (bbox[3] - bbox[1])) // 2 - bbox[1]
    d.text((30, ty), txt, font=f, fill=(*fg, 255))
    return img


def caption(text, width, size=46, max_w_ratio=0.86, pad=22):
    """Bottom caption strip (semi-transparent black + white text). RGBA PNG."""
    f = find_font(size)
    probe = Image.new("RGBA", (10, 10))
    d0 = ImageDraw.Draw(probe)
    lines = _wrap(d0, " ".join(str(text).split()), f, int(width * max_w_ratio))
    line_h = size + 20
    h = pad * 2 + line_h * len(lines)
    img = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # caption background bar (full width, semi transparent)
    d.rectangle([0, 0, width, h], fill=(0, 0, 0, 150))
    d.rectangle([0, 0, width, 5], fill=(255, 212, 0, 255))
    for i, ln in enumerate(lines):
        tw = d.textlength(ln, font=f)
        x = (width - tw) / 2
        y = pad + i * line_h
        # outline for readability
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                d.text((x + dx, y + dy), ln, font=f, fill=(0, 0, 0, 220))
        d.text((x, y), ln, font=f, fill=(255, 255, 255, 255))
    return img


def lower_third(channel, handle, width, height=74):
    """Bottom-left channel branding strip. RGBA PNG."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = find_font(38)
    fs = find_font(26)
    box_w = 620
    d.rectangle([0, 0, box_w, height], fill=(10, 10, 12, 190))
    d.rectangle([0, 0, 10, height], fill=(200, 16, 46, 255))
    d.text((30, 14), channel, font=f, fill=(255, 255, 255, 255))
    hw = d.textlength(channel, font=f)
    d.text((36 + hw, 24), handle, font=fs, fill=(255, 212, 0, 255))
    return img


def title_card(headline, channel, handle, w, h, bg_image=None):
    """Intro card: dark gradient + big headline + channel. RGB image."""
    if bg_image and Path(bg_image).exists():
        base = Image.open(bg_image).convert("RGB").resize((w, h), Image.LANCZOS)
        dark = Image.new("RGB", (w, h), (0, 0, 0))
        base = Image.blend(base, dark, 0.62)
    else:
        base = Image.new("RGB", (w, h), (12, 14, 20))
    img = base.convert("RGBA")
    d = ImageDraw.Draw(img)
    # top red band
    d.rectangle([0, 0, w, 14], fill=(200, 16, 46, 255))
    # channel tag
    cf = find_font(40)
    d.rectangle([80, 120, 80 + 560, 200], fill=(200, 16, 46, 255))
    d.text((110, 132), f"{channel}  {handle}", font=cf, fill=(255, 255, 255, 255))
    # big headline (centered, wrapped)
    hf = find_font(104)
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    lines = _wrap(probe, " ".join(str(headline).split())[:120], hf, int(w * 0.82))
    lines = lines[:4]
    line_h = 130
    total = line_h * len(lines)
    y = (h - total) // 2 + 40
    for ln in lines:
        tw = d.textlength(ln, font=hf)
        x = (w - tw) / 2
        for dx in (-3, -2, -1, 0, 1, 2, 3):
            for dy in (-3, -2, -1, 0, 1, 2, 3):
                d.text((x + dx, y + dy), ln, font=hf, fill=(0, 0, 0, 230))
        d.text((x, y), ln, font=hf, fill=(255, 255, 255, 255))
        y += line_h
    # bottom bar
    d.rectangle([0, h - 90, w, h], fill=(0, 0, 0, 170))
    bf = find_font(34)
    d.text((80, h - 66), "Breaking News", font=bf, fill=(255, 212, 0, 255))
    return img.convert("RGB")

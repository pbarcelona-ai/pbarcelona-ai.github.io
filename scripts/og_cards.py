#!/usr/bin/env python3
"""Draws 1200x630 social-preview cards (og:image) in the site's colours.

Used by build_digital_ip_docs.py (one card per IP page) and finalize_site.py
(home, demo and design-notes pages). Needs Pillow.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
BG = "#0a192f"
SURFACE = "#112240"
BORDER = "#233554"
ACCENT = "#64ffda"
HEADING = "#ccd6f6"
TEXT = "#8892b0"

FONT_CANDIDATES = {
    True: ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
           "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
           "/Library/Fonts/Arial Bold.ttf"],
    False: ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf"],
}
MONO_CANDIDATES = ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
                   "/System/Library/Fonts/Menlo.ttc",
                   "/System/Library/Fonts/Monaco.ttf"]


def _font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    for path in (MONO_CANDIDATES if mono else FONT_CANDIDATES[bold]):
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width_px: int, max_lines: int) -> list[str]:
    avg = max(1, draw.textlength("abcdefghijklmnopqrstuvwxyz", font=font) / 26)
    lines = textwrap.wrap(text, max(10, int(width_px / avg)))
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,;: ") + "…"
    return lines


def make_card(out: Path, title: str, kicker: str, subtitle: str = "", stats: str = "") -> None:
    """kicker: small uppercase line above the title; stats: monospace footer line."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 10], fill=ACCENT)
    d.rounded_rectangle([60, 60, W - 60, H - 60], radius=18, fill=SURFACE, outline=BORDER, width=2)

    x, y = 110, 105
    d.text((x, y), kicker.upper(), font=_font(26, mono=True), fill=ACCENT)
    y += 58

    size = 72 if len(title) <= 22 else 60 if len(title) <= 32 else 50
    tfont = _font(size, bold=True)
    for line in _wrap(d, title, tfont, W - 220, 2):
        d.text((x, y), line, font=tfont, fill=HEADING)
        y += int(size * 1.18)
    y += 14

    if subtitle:
        sfont = _font(30)
        for line in _wrap(d, subtitle, sfont, W - 220, 3 if y < 330 else 2):
            d.text((x, y), line, font=sfont, fill=TEXT)
            y += 42

    foot_y = H - 60 - 70
    d.line([x, foot_y - 18, W - 110, foot_y - 18], fill=BORDER, width=2)
    d.text((x, foot_y), "FPGA Cores 4U", font=_font(30, bold=True), fill=HEADING)
    if stats:
        mfont = _font(24, mono=True)
        d.text((W - 110 - d.textlength(stats, font=mfont), foot_y + 4), stats, font=mfont, fill=ACCENT)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, optimize=True)

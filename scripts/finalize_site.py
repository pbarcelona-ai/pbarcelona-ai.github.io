#!/usr/bin/env python3
"""Site-wide finishing steps, run after build_digital_ip_docs.py and before Pagefind.

- Draws og:image cards for the hand-written pages (home, demos, design notes).
- Writes sitemap.xml from every canonical page, with lastmod dates.
- Adds the GoatCounter analytics tag to every published page when
  GOATCOUNTER_CODE is set.

Usage: python3 scripts/finalize_site.py
"""
from __future__ import annotations

import html
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from og_cards import make_card  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://pbarcelona-ai.github.io"

# GoatCounter site code (the "xxx" in https://xxx.goatcounter.com); empty disables analytics.
GOATCOUNTER_CODE = ""

# Hand-written pages that get their own card: page -> (card name, kicker).
STATIC_CARDS = {
    "index.html": ("home", "FPGA Cores 4U"),
    "lens-distortion-correction.html": ("lens-distortion-correction", "SystemVerilog demo"),
    "demo/index.html": ("demos", "Hardware demos"),
}

# Canonical pages that are not generated under /ip/.
STATIC_PAGES = [
    "index.html",
    "demo/index.html",
    "lens-distortion-correction.html",
    "digital_ip/ip/tools/docs/index.html",
    "digital_ip/image_processing/vision_system/docs/site/index.html",
    "digital_ip/image_processing/vision_system/docs/site/architecture.html",
    "digital_ip/image_processing/vision_system/docs/site/registers.html",
    "digital_ip/image_processing/vision_system/docs/site/synthesis.html",
]

SKIP_DIRS = {".git", "pagefind", "node_modules"}


def page_url(rel: str) -> str:
    if rel == "index.html":
        return f"{BASE_URL}/"
    if rel.endswith("/index.html") and rel.startswith("ip/"):
        return f"{BASE_URL}/{rel[:-len('index.html')]}"
    return f"{BASE_URL}/{rel}"


def git_date(path: Path) -> str | None:
    """Last commit date of a file, asking the repo (or submodule) that owns it."""
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%cs", "--", path.name],
                             cwd=path.parent, capture_output=True, text=True, check=True).stdout.strip()
        return out or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def lastmod(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'"dateModified":\s*"(\d{4}-\d{2}-\d{2})"', text)
    return (m.group(1) if m else None) or git_date(path) or date.today().isoformat()


def meta(text: str, name: str) -> str:
    m = re.search(rf'<meta name="{name}" content="([^"]*)"', text)
    return html.unescape(m.group(1)) if m else ""


def draw_static_cards() -> int:
    n_cores = len(list((REPO_ROOT / "ip").glob("*/index.html")))
    cards = dict(STATIC_CARDS)
    for note in sorted((REPO_ROOT / "design-notes").glob("*.html")):
        cards[f"design-notes/{note.name}"] = (f"notes-{note.stem}", "Design notes")
    for rel, (name, kicker) in cards.items():
        page = REPO_ROOT / rel
        if not page.is_file():
            continue
        text = page.read_text(encoding="utf-8")
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S)
        title = html.unescape(re.sub(r"<[^>]+>", "", h1.group(1))).strip() if h1 else name
        subtitle = meta(text, "description")
        stats = f"{n_cores} IP cores · MIT" if rel == "index.html" and n_cores else ""
        make_card(REPO_ROOT / "og" / f"{name}.png", title, kicker, subtitle, stats)
    return len(cards)


def write_sitemap() -> int:
    pages = [p for p in STATIC_PAGES if (REPO_ROOT / p).is_file()]
    pages += sorted(f"design-notes/{p.name}" for p in (REPO_ROOT / "design-notes").glob("*.html"))
    pages += ["ip/index.html"] if (REPO_ROOT / "ip" / "index.html").is_file() else []
    pages += sorted(p.relative_to(REPO_ROOT).as_posix() for p in (REPO_ROOT / "ip").glob("*/index.html"))
    rows = "".join(f"  <url>\n    <loc>{page_url(p)}</loc>\n    <lastmod>{lastmod(REPO_ROOT / p)}</lastmod>\n  </url>\n"
                   for p in pages)
    (REPO_ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + rows + "</urlset>\n",
        encoding="utf-8")
    return len(pages)


def add_analytics() -> int:
    if not GOATCOUNTER_CODE:
        return 0
    tag = (f'<script data-goatcounter="https://{GOATCOUNTER_CODE}.goatcounter.com/count" '
           'async src="//gc.zgo.at/count.js"></script>')
    count = 0
    for page in REPO_ROOT.rglob("*.html"):
        if SKIP_DIRS & set(page.relative_to(REPO_ROOT).parts) or page.name.startswith("google"):
            continue
        text = page.read_text(encoding="utf-8", errors="replace")
        if "goatcounter" in text or 'http-equiv="refresh"' in text or "</head>" not in text:
            continue
        page.write_text(text.replace("</head>", tag + "</head>", 1), encoding="utf-8")
        count += 1
    return count


def main() -> None:
    cards = draw_static_cards()
    urls = write_sitemap()
    tagged = add_analytics()
    print(f"[finalize] {cards} static cards, {urls} sitemap URLs, analytics on {tagged} pages")


if __name__ == "__main__":
    main()

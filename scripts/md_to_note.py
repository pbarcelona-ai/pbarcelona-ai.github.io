#!/usr/bin/env python3
"""Convert a Markdown file into a design-notes page for the site.

Usage:
    python3 scripts/md_to_note.py INPUT.md --slug NAME [--title T] [--description D]
                                  [--date YYYY-MM-DD] [--about A] [--out PATH]
                                  [--link OLD=NEW ...]

Writes design-notes/<slug>.html (or --out) in the same page template as the
hand-written notes: SEO and social meta tags, TechArticle and breadcrumb
JSON-LD, site.css, the "Design notes" eyebrow, the published date and the
back link. finalize_site.py draws its social card (og/notes-<slug>.png) and
lists it in sitemap.xml on the next full build.

Title, description and date come from the options, else from an optional
front-matter block at the top of the Markdown file:

    ---
    title: ...
    description: ...
    date: 2026-10-08
    ---

else from the first "# " heading, the first paragraph and today's date. The
first "# " heading becomes the page <h1> and is not repeated in the body.

--link rewrites link targets (e.g. a sibling .md file to its published page);
it may be given several times.

Supported Markdown (no third-party packages needed): ATX headings (with
anchor ids), paragraphs, **bold**, *italic* / _italic_, `code`, [links](url),
![images](url), fenced code blocks (``` with an optional language), bullet and
numbered lists (nested by indentation), block quotes, GitHub tables (with
:--: alignment) and horizontal rules. HTML in the source is escaped.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://pbarcelona-ai.github.io"
SITE_NAME = "FPGA Cores 4U"


# ---------------------------------------------------------------- inline

def slugify(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text).lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    return re.sub(r"[\s-]+", "-", text).strip("-")


LINK_MAP: dict[str, str] = {}


def inline(text: str) -> str:
    """Escape HTML, then apply code spans, images, links, bold and italics."""
    spans: list[str] = []

    def stash(fragment: str) -> str:
        spans.append(fragment)
        return f"\x00{len(spans) - 1}\x00"

    # Code spans first, so nothing inside them is formatted
    text = re.sub(r"`([^`]+)`", lambda m: stash(f"<code>{html.escape(m.group(1), quote=False)}</code>"), text)
    text = html.escape(text, quote=False)
    text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)",
                  lambda m: stash(f'<img src="{html.escape(m.group(2))}" alt="{m.group(1)}">'), text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                  lambda m: stash(f'<a href="{html.escape(LINK_MAP.get(m.group(2), m.group(2)))}">{m.group(1)}</a>'), text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
    text = re.sub(r"(?<![\w])_(?!\s)(.+?)(?<!\s)_(?![\w])", r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], text)


# ---------------------------------------------------------------- blocks

LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    cells, cur, in_code = [], "", False
    for i, ch in enumerate(line):                           # a | inside `code` or escaped is not a separator
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code and (i == 0 or line[i - 1] != "\\"):
            cells.append(cur)
            cur = ""
        else:
            cur += ch
    cells.append(cur)
    return [c.strip().replace("\\|", "|") for c in cells]


def render_table(lines: list[str]) -> str:
    head = split_row(lines[0])
    aligns = []
    for cell in split_row(lines[1]):
        left, right = cell.startswith(":"), cell.endswith(":")
        aligns.append("center" if left and right else "right" if right else "left" if left else "")

    def cell(tag: str, text: str, i: int) -> str:
        a = aligns[i] if i < len(aligns) and aligns[i] else ""
        style = f' style="text-align: {a}"' if a else ""
        return f"<{tag}{style}>{inline(text)}</{tag}>"

    out = ["<div class=\"table-wrap\"><table>", "<thead><tr>" + "".join(cell("th", c, i) for i, c in enumerate(head)) + "</tr></thead>", "<tbody>"]
    for row in lines[2:]:
        out.append("<tr>" + "".join(cell("td", c, i) for i, c in enumerate(split_row(row))) + "</tr>")
    out.append("</tbody></table></div>")
    return "\n".join(out)


def render_list(lines: list[str]) -> str:
    """Nested ul / ol from list lines (continuation lines are appended to the item)."""
    items: list[tuple[int, bool, str, int]] = []            # (indent, ordered, text, number)
    for line in lines:
        m = LIST_RE.match(line)
        if m:
            num = int(m.group(2)[:-1]) if m.group(2)[0].isdigit() else 0
            items.append((len(m.group(1).expandtabs(4)), m.group(2)[0].isdigit(), m.group(3), num))
        elif items:
            items[-1] = (items[-1][0], items[-1][1], items[-1][2] + " " + line.strip(), items[-1][3])

    out: list[str] = []
    stack: list[tuple[int, str]] = []                       # (indent, tag)
    for indent, ordered, text, num in items:
        tag = "ol" if ordered else "ul"
        while stack and indent < stack[-1][0]:
            out.append(f"</li></{stack.pop()[1]}>")
        if stack and indent == stack[-1][0] and tag != stack[-1][1]:    # bullet <-> numbered: new list
            out.append(f"</li></{stack.pop()[1]}>")
        if not stack or indent > stack[-1][0]:
            stack.append((indent, tag))
            start = f' start="{num}"' if ordered and num != 1 else ""        # keep the source numbering
            out.append(f"<{tag}{start}>")
        else:
            out.append("</li>")
        out.append(f"<li>{inline(text)}")
    while stack:
        out.append(f"</li></{stack.pop()[1]}>")
    return "".join(out)


def convert(md: str) -> tuple[str, str | None, str | None]:
    """Markdown -> (body HTML, first H1 text, first paragraph text)."""
    lines = md.splitlines()
    out: list[str] = []
    h1 = first_para = None
    used_ids: set[str] = set()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # fenced code
        m = re.match(r"^(`{3,}|~{3,})\s*([\w+-]*)\s*$", stripped)
        if m:
            fence, lang = m.group(1), m.group(2)
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(fence):
                body.append(lines[i])
                i += 1
            i += 1
            cls = f' class="language-{lang}"' if lang else ""
            out.append(f"<pre><code{cls}>{html.escape(chr(10).join(body), quote=False)}</code></pre>")
            continue

        # heading
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", stripped)
        if m:
            level, text = len(m.group(1)), m.group(2)
            if level == 1 and h1 is None:
                h1 = re.sub(r"[*_`]", "", text)
                i += 1
                continue
            hid = base = slugify(text) or f"section-{len(used_ids) + 1}"
            n = 2
            while hid in used_ids:
                hid, n = f"{base}-{n}", n + 1
            used_ids.add(hid)
            out.append(f'<h{level} id="{hid}">{inline(text)}</h{level}>')
            i += 1
            continue

        # horizontal rule
        if re.match(r"^([-*_])(\s*\1){2,}$", stripped):
            out.append("<hr>")
            i += 1
            continue

        # table
        if "|" in stripped and i + 1 < len(lines) and TABLE_SEP_RE.match(lines[i + 1]):
            block = [line, lines[i + 1]]
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                block.append(lines[i])
                i += 1
            out.append(render_table(block))
            continue

        # block quote
        if stripped.startswith(">"):
            block = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                block.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            inner, _, _ = convert("\n".join(block))
            out.append(f"<blockquote>{inner}</blockquote>")
            continue

        # list
        if LIST_RE.match(line):
            block = []
            while i < len(lines) and lines[i].strip() and (LIST_RE.match(lines[i]) or lines[i].startswith((" ", "\t"))):
                block.append(lines[i])
                i += 1
            out.append(render_list(block))
            continue

        # paragraph
        block = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,6}\s|`{3,}|~{3,}|>)", lines[i].strip()) \
                and not LIST_RE.match(lines[i]):
            block.append(lines[i].strip())
            i += 1
        text = " ".join(block)
        if first_para is None:
            first_para = re.sub(r"[*_`]|\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1) or "", text)
        out.append(f"<p>{inline(text)}</p>")

    return "\n".join(out), h1, first_para


# ---------------------------------------------------------------- page

def front_matter(md: str) -> tuple[dict[str, str], str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", md, re.S)
    if not m:
        return {}, md
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip().strip('"')
    return meta, md[m.end():]


def page(slug: str, title: str, description: str, published: str, about: str, body: str) -> str:
    url = f"{BASE_URL}/design-notes/{slug}.html"
    image = f"{BASE_URL}/og/notes-{slug}.png"
    esc = lambda s: html.escape(s, quote=True)
    article = {"@context": "https://schema.org", "@type": "TechArticle", "headline": title, "url": url,
               "datePublished": published, "dateModified": published,
               "author": {"@type": "Organization", "name": SITE_NAME}, "image": image,
               "about": about, "proficiencyLevel": "Expert"}
    crumbs = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{BASE_URL}/"},
        {"@type": "ListItem", "position": 2, "name": f"Design Notes: {title}", "item": url}]}
    # The body is not re-indented: that would add spaces inside <pre> blocks
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="theme-color" content="#0a192f">
    <link rel="icon" href="/favicon.svg" type="image/svg+xml">
    <title>{esc(title)} | {SITE_NAME}</title>
    <meta name="description" content="{esc(description)}">
    <link rel="canonical" href="{url}">
    <meta property="og:type" content="article">
    <meta property="og:site_name" content="{SITE_NAME}">
    <meta property="og:title" content="{esc(title)}">
    <meta property="og:description" content="{esc(description)}">
    <meta property="og:url" content="{url}">
    <meta property="og:image" content="{image}">
    <meta name="twitter:image" content="{image}">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{esc(title)}">
    <meta name="twitter:description" content="{esc(description)}">
    <script type="application/ld+json">{json.dumps(article)}</script>
    <script type="application/ld+json">{json.dumps(crumbs)}</script>
    <link rel="stylesheet" href="../site.css">
    <style>
        main {{ max-width: 760px; margin: 0 auto; padding: 60px 20px 100px; }}
        h1 {{ font-size: 2.1rem; }}
        .eyebrow {{ color: var(--accent); font-family: monospace; font-size: 0.85rem; text-transform: uppercase; }}
        article h2 {{ margin-top: 40px; }}
        article p, article li {{ color: var(--text); }}
        code {{ background: var(--code-bg); padding: 2px 6px; border-radius: 4px; }}
        pre {{ background: var(--code-bg); padding: 14px 16px; border-radius: 6px; overflow-x: auto; }}
        pre code {{ background: none; padding: 0; }}
        table {{ width: 100%; border-collapse: collapse; margin: 12px 0 20px; font-size: 0.92rem; }}
        th, td {{ padding: 8px 10px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }}
        th {{ color: var(--heading); }}
        .table-wrap {{ overflow-x: auto; }}
        blockquote {{ border-left: 3px solid var(--accent); margin: 16px 0; padding: 2px 16px; }}
        hr {{ border: none; border-top: 1px solid var(--border); margin: 36px 0; }}
        .updated {{ font-size: 0.85rem; margin-top: -6px; }}
        .back {{ display: inline-block; margin-top: 40px; }}
    </style>
</head>
<body>
    <main data-pagefind-body>
        <p class="eyebrow">Design notes</p>
        <h1>{esc(title)}</h1>
        <p class="updated">Published <time datetime="{published}">{published}</time></p>
        <article>
{body}
        </article>
        <a class="back" href="../index.html">&larr; Back to homepage</a>
    </main>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("input", type=Path)
    ap.add_argument("--slug", required=True, help="page name: design-notes/<slug>.html")
    ap.add_argument("--title")
    ap.add_argument("--description")
    ap.add_argument("--date", help="publication date, YYYY-MM-DD (default: today)")
    ap.add_argument("--about", help="schema.org 'about' text (default: the title)")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--link", action="append", default=[], metavar="OLD=NEW", help="rewrite a link target")
    args = ap.parse_args()
    for pair in args.link:
        old, _, new = pair.partition("=")
        LINK_MAP[old] = new

    meta, md = front_matter(args.input.read_text(encoding="utf-8"))
    body, h1, first_para = convert(md)
    title = args.title or meta.get("title") or h1 or args.slug
    description = args.description or meta.get("description") or (first_para or title)[:300]
    published = args.date or meta.get("date") or date.today().isoformat()
    about = args.about or meta.get("about") or title
    out = args.out or REPO_ROOT / "design-notes" / f"{args.slug}.html"
    out.write_text(page(args.slug, title, description, published, about, body), encoding="utf-8")
    print(f"wrote {out.relative_to(REPO_ROOT) if out.is_relative_to(REPO_ROOT) else out}")


if __name__ == "__main__":
    main()

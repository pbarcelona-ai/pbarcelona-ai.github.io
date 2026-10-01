#!/usr/bin/env python3
"""Enhance the digital_ip/ submodule's generated catalog pages in place.

Regenerates the catalog with the submodule's own generators (writing into
digital_ip/ip/docs/ and digital_ip/ip/tools/docs/, as that project already
does), strips links to full RTL source (replacing them with header+port-list
snippets and shared-module snippets extracted from the submodule), and
layers on this site's SEO/navigation conventions (canonical/OG/Twitter tags,
favicon, breadcrumbs, per-category "typical applications" + related-module
links).

digital_ip/ is a git submodule (see .gitmodules); this script never commits
to it, it only rewrites the working tree so the GitHub Pages build can
publish it directly.

Usage: python3 scripts/build_digital_ip_docs.py
"""
from __future__ import annotations

import html
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SUBMODULE_ROOT = REPO_ROOT / "digital_ip"
SUBMODULE_IP = SUBMODULE_ROOT / "ip"
OUT_ROOT = SUBMODULE_IP
BASE_URL = "https://pbarcelona-ai.github.io"

CATEGORY_BLURBS = {
    "Bus": "Bus-fabric IP like this is commonly used to connect AXI4 and AXI4-Lite masters and slaves inside an SoC or FPGA shell &mdash; decoding addresses, multiplexing ports, adapting stream widths, or moving frames over DMA between memory and streaming peripherals.",
    "CDC": "Clock-domain-crossing IP like this is used anywhere two clock domains need to exchange signals or data safely &mdash; for example bridging a sensor's native clock to a processing clock, or synchronizing resets and control pulses across domains without metastability risk.",
    "Common": "General-purpose DSP building blocks like this show up in signal-conditioning front ends, decimation/interpolation chains, sample-rate converters, and control-loop math across audio, RF, and sensor pipelines.",
    "FIFO": "FIFOs like this buffer bursty or rate-mismatched traffic between producer and consumer logic &mdash; typical uses include streaming video lines, packet queues, and decoupling a fast core from a slower bus.",
    "Integrity": "Data-integrity IP like this protects against corruption in storage and communication links &mdash; typical uses include memory ECC, packet checksums/CRCs, and parity checking on buses or serial links.",
    "Math": "Arithmetic IP like this accelerates compute-heavy datapaths &mdash; typical uses include DSP filters, neural-network accumulation, and fixed/floating-point signal processing pipelines.",
    "Memory": "Memory IP like this provides on-chip storage building blocks &mdash; typical uses include register files, lookup tables, and single/dual-port RAM wrappers for FPGA block RAM or ASIC memory compilers.",
    "Peripherals": "Peripheral IP like this implements standard off-chip interfaces &mdash; typical uses include sensor and storage buses (I2C, SPI, SDIO), communication links (UART, USB, Ethernet, PCIe), and general-purpose I/O and interrupt control.",
    "Scalers": "Scaler and video-pipeline IP like this is used in image and video processing datapaths &mdash; typical uses include resolution conversion, sharpening, frame buffering, and control-plane register access in camera or display pipelines.",
    "Timing": "Timing IP like this generates or measures time-based signals &mdash; typical uses include baud-rate and PWM generation, frequency/interval measurement, watchdogs, and numerically controlled oscillators for communication and control systems.",
}

SHARED_REF_RE = re.compile(r'shared/(?:src|tb)/[A-Za-z0-9_/]*?([A-Za-z0-9_]+\.sv)')


def run(cmd, cwd):
    print(f"[build] running: {' '.join(cmd)} (cwd={cwd})")
    subprocess.run(cmd, cwd=cwd, check=True)


def run_generators():
    # Drop any previously generated/enhanced pages so removed modules don't
    # leave stale output, and so every run starts from the raw generator output.
    run(["git", "clean", "-fdx", "--", "ip/docs", "ip/tools/docs"], cwd=SUBMODULE_ROOT)
    run(["python3", "scripts/gen_docs.py"], cwd=SUBMODULE_IP)
    run(["python3", "tools/generate_docs.py"], cwd=SUBMODULE_IP)


def parse_categories(catalog_html: str) -> dict[str, list[str]]:
    groups = re.findall(
        r'<div class="section-head"><h2>([^<]+)</h2><span>(\d+) IPs</span></div>'
        r'<div class="table-wrap">(.*?)</table>',
        catalog_html, re.S,
    )
    categories: dict[str, list[str]] = {}
    for name, _count, table in groups:
        mods = re.findall(r'href="([a-zA-Z0-9_]+)/index\.html"', table)
        categories[name] = mods
    return categories


def resolve_primary_source(category_dir: str, module: str) -> Path | None:
    src_dir = SUBMODULE_IP / category_dir / module / "src"
    if not src_dir.is_dir():
        return None
    files = sorted(f.name for f in src_dir.glob("*.sv"))
    if not files:
        return None
    exact = f"{module}.sv"
    if exact in files:
        return src_dir / exact
    tops = [f for f in files if "_top" in f]
    if len(tops) == 1:
        return src_dir / tops[0]
    if len(files) == 1:
        return src_dir / files[0]
    return None


def extract_header_port_snippet(path: Path) -> str | None:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = []
    i = 0
    while i < len(lines) and lines[i].lstrip().startswith("//"):
        header.append(lines[i])
        i += 1
    mod_start = next((j for j, l in enumerate(lines) if re.match(r"^\s*module\s+\w+", l)), None)
    if mod_start is None:
        return None
    mod_end = next((j for j in range(mod_start, len(lines)) if lines[j].strip() == ");"), None)
    if mod_end is None:
        return None
    body = header + [""] + lines[mod_start:mod_end + 1]
    return "\n".join(body) + "\n"


def generate_module_snippets(categories: dict[str, list[str]]) -> dict[str, str]:
    """Writes digital_ip/ip/docs/<module>/<module>.sv; returns module -> resolved basename."""
    resolved: dict[str, str] = {}
    for category, modules in categories.items():
        category_dir = category.lower()
        for module in modules:
            src_path = resolve_primary_source(category_dir, module)
            if not src_path:
                continue
            snippet = extract_header_port_snippet(src_path)
            if not snippet:
                continue
            out_dir = OUT_ROOT / "docs" / module
            if not out_dir.is_dir():
                continue
            (out_dir / f"{module}.sv").write_text(snippet, encoding="utf-8")
            resolved[module] = src_path.name
    return resolved


def find_shared_refs() -> set[str]:
    names: set[str] = set()
    for html_path in (OUT_ROOT / "docs").glob("*/index.html"):
        text = html_path.read_text(encoding="utf-8")
        names.update(m.group(1) for m in SHARED_REF_RE.finditer(text))
    return names


def generate_shared_snippets(shared_names: set[str]) -> set[str]:
    out_dir = OUT_ROOT / "docs" / "shared"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = set()
    for name in shared_names:
        matches = list((SUBMODULE_IP / "shared").rglob(name))
        if not matches:
            continue
        snippet = extract_header_port_snippet(matches[0])
        if not snippet:
            continue
        (out_dir / name).write_text(snippet, encoding="utf-8")
        written.add(name)
    return written


LI_SV_RE = re.compile(r'<li><a href="([^"]+\.sv)">([^<]+)</a></li>')


def rewrite_rtl_and_verification(content: str, module: str, own_basename: str | None, shared_names: set[str]) -> str:
    def li_sub(m: re.Match) -> str:
        href, text = m.group(1), m.group(2)
        base = href.rsplit("/", 1)[-1]
        if base in shared_names:
            return f'<li><a href="../shared/{base}">{base}</a></li>'
        if own_basename and base == own_basename:
            # dropped here; the module.sv snippet link is inserted separately
            return ""
        return f'<li><span class="sv-ref">{html.escape(text)}</span></li>'

    return LI_SV_RE.sub(li_sub, content)


def strip_verification_paths(content: str) -> str:
    def verif_sub(m: re.Match) -> str:
        head, ul_open, body, ul_close = m.group(1), m.group(2), m.group(3), m.group(4)

        def li_sub(lm: re.Match) -> str:
            inner = lm.group(0)
            am = re.search(r'<a href="([^"]+)">', inner)
            sm = re.search(r'<span class="sv-ref">([^<]+)</span>', inner)
            if am:
                base = am.group(1).rsplit("/", 1)[-1]
                return f'<li><a href="../shared/{base}">{base}</a></li>'
            if sm:
                base = sm.group(1).rsplit("/", 1)[-1]
                return f'<li><span class="sv-ref">{base}</span></li>'
            return inner

        new_body = re.sub(r"<li>.*?</li>", li_sub, body)
        return head + ul_open + new_body + ul_close

    pattern = re.compile(r'(<h2>Verification</h2>)(<ul class="file-list">)(.*?)(</ul>)', re.S)
    return pattern.sub(verif_sub, content)


def add_module_decl_link(content: str, module: str) -> str:
    link = f'<p class="module-decl-link"><a href="{module}.sv">{module}.sv</a></p>'
    pattern = re.compile(r'(<h2>(?:RTL sources|Implementation)</h2>\s*<ul class="file-list">.*?</ul>)', re.S)
    new_content, n = pattern.subn(lambda m: m.group(1) + link, content, count=1)
    return new_content if n else content


def add_seo_tags(content: str, canonical_url: str) -> str:
    if "og:title" in content:
        return content
    tm = re.search(r"<title>(.*?)</title>", content, re.S)
    title = html.unescape(tm.group(1)).strip() if tm else canonical_url
    dm = re.search(r'<meta name="description" content="([^"]*)"', content)
    desc = html.unescape(dm.group(1)).strip() if dm else title

    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace('"', "&quot;")

    snippet = (
        f'<link rel="canonical" href="{canonical_url}">'
        '<meta property="og:type" content="website">'
        '<meta property="og:site_name" content="FPGA Cores 4U">'
        f'<meta property="og:title" content="{esc(title)}">'
        f'<meta property="og:description" content="{esc(desc)}">'
        f'<meta property="og:url" content="{canonical_url}">'
        f'<meta property="og:image" content="{BASE_URL}/og-image.png">'
        f'<meta name="twitter:image" content="{BASE_URL}/og-image.png">'
        '<meta name="twitter:card" content="summary_large_image">'
        f'<meta name="twitter:title" content="{esc(title)}">'
        f'<meta name="twitter:description" content="{esc(desc)}">'
    )
    if "</title>" not in content:
        return content
    return content.replace("</title>", "</title>" + snippet, 1)


def add_favicon_and_theme(content: str) -> str:
    if 'rel="icon"' in content:
        return content
    marker = '<meta name="theme-color" content="#0a192f">'
    if marker not in content:
        return content
    return content.replace(marker, marker + '<link rel="icon" href="/favicon.svg" type="image/svg+xml">', 1)


def add_breadcrumbs(content: str, module: str | None, canonical_url: str) -> str:
    if "BreadcrumbList" in content:
        return content
    items = [{"@type": "ListItem", "position": 1, "name": "Home", "item": f"{BASE_URL}/"}]
    catalog_url = f"{BASE_URL}/digital_ip/ip/docs/index.html"
    if module is None:
        items.append({"@type": "ListItem", "position": 2, "name": "Digital IP Catalog", "item": canonical_url})
    else:
        items.append({"@type": "ListItem", "position": 2, "name": "Digital IP Catalog", "item": catalog_url})
        items.append({"@type": "ListItem", "position": 3, "name": module, "item": canonical_url})
    data = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items}
    snippet = f'<script type="application/ld+json">{json.dumps(data)}</script>'
    if "</head>" not in content:
        return content
    return content.replace("</head>", snippet + "</head>", 1)


def add_typical_applications(content: str, category: str, module: str, siblings: list[str], titles: dict[str, str]) -> str:
    if "Typical applications" in content or not siblings:
        return content
    links = "".join(f'<li><a href="../{s}/index.html">{titles.get(s, s)}</a></li>' for s in siblings[:5])
    section = (
        '<section class="content"><article>'
        f'<p class="eyebrow">{category}</p><h2>Typical applications</h2>'
        f'<p>{CATEGORY_BLURBS.get(category, "")}</p>'
        '<h2>Related modules</h2>'
        f'<ul class="file-list">{links}</ul>'
        '</article></section>'
    )
    if "<footer" not in content:
        return content
    return re.sub(r"(<footer)", section + r"\1", content, count=1)


def main() -> None:
    run_generators()

    catalog_path = OUT_ROOT / "docs" / "index.html"
    catalog_html = catalog_path.read_text(encoding="utf-8")
    categories = parse_categories(catalog_html)
    module_to_category = {m: cat for cat, mods in categories.items() for m in mods}

    resolved = generate_module_snippets(categories)
    shared_names = find_shared_refs()
    shared_written = generate_shared_snippets(shared_names)

    titles: dict[str, str] = {}
    for module in module_to_category:
        page = OUT_ROOT / "docs" / module / "index.html"
        if not page.is_file():
            continue
        tm = re.search(r"<title>(.*?)</title>", page.read_text(encoding="utf-8"), re.S)
        titles[module] = html.unescape(tm.group(1)).split("|")[0].strip() if tm else module

    for module, category in module_to_category.items():
        page = OUT_ROOT / "docs" / module / "index.html"
        if not page.is_file():
            continue
        content = page.read_text(encoding="utf-8")
        own_basename = resolved.get(module)
        content = rewrite_rtl_and_verification(content, module, own_basename, shared_written)
        content = strip_verification_paths(content)
        if own_basename:
            content = add_module_decl_link(content, module)
        canonical = f"{BASE_URL}/digital_ip/ip/docs/{module}/index.html"
        content = add_seo_tags(content, canonical)
        content = add_favicon_and_theme(content)
        content = add_breadcrumbs(content, titles.get(module, module), canonical)
        siblings = [m for m in categories.get(category, []) if m != module]
        content = add_typical_applications(content, category, module, siblings, titles)
        page.write_text(content, encoding="utf-8")

    # Catalog + scaler catalog pages: SEO tags, favicon, breadcrumbs only.
    for page, canonical in (
        (OUT_ROOT / "docs" / "index.html", f"{BASE_URL}/digital_ip/ip/docs/index.html"),
        (OUT_ROOT / "tools" / "docs" / "index.html", f"{BASE_URL}/digital_ip/ip/tools/docs/index.html"),
    ):
        if not page.is_file():
            continue
        content = page.read_text(encoding="utf-8")
        content = add_seo_tags(content, canonical)
        content = add_favicon_and_theme(content)
        content = add_breadcrumbs(content, None, canonical)
        page.write_text(content, encoding="utf-8")

    print(f"[build] done: {len(module_to_category)} module pages, "
          f"{len(resolved)} module snippets, {len(shared_written)} shared snippets")


if __name__ == "__main__":
    sys.exit(main())

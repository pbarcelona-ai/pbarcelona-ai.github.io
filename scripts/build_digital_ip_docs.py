#!/usr/bin/env python3
"""Builds the site's IP pages from the digital_ip/ submodule's generated catalog.

Regenerates the catalog with the submodule's own generators (writing into
digital_ip/ip/docs/ and digital_ip/ip/tools/docs/, as that project already
does), strips links to full RTL source (replacing them with header+port-list
snippets and shared-module snippets extracted from the submodule), and
layers on this site's SEO/navigation conventions:

- each module page is published at a short URL, /ip/<module-name>/, with a
  <base> pointing back at its generated folder so relative assets resolve;
  the old digital_ip/ip/docs/... pages become redirect stubs, and the
  per-module copies under ip/<category>/<module>/docs/ get a canonical link;
- search-friendly titles and short descriptions, canonical/OG/Twitter tags,
  a social card per core (og/<name>.png), SoftwareSourceCode and breadcrumb
  JSON-LD, favicon;
- a datasheet section (clocking/reset/latency from the RTL header, Yosys
  utilization from docs/STATUS.md, parameters), the RTL hierarchy diagram, the
  block / state diagrams (*_block_diagram.svg, *_fsm.svg) and data-flow diagram
  (<module>_dataflow.svg) from each core's docs folder,
  version and last-updated date, "typical applications" + related modules;
- the catalog is published at /ip/, and the site's index.html IP index
  (between the IP-INDEX markers) is regenerated from it.

digital_ip/ is a git submodule (see .gitmodules); this script never commits
to it, it only rewrites the working tree so the GitHub Pages build can
publish it directly. Generated output (ip/, og/) is gitignored.

Usage: python3 scripts/build_digital_ip_docs.py
"""
from __future__ import annotations

import html
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from og_cards import make_card  # noqa: E402

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

# Home-page section headings and intros, one per catalog category.
HOME_CATEGORIES = {
    "Bus": ("AXI &amp; bus interconnect IP", "AXI4-Lite decoders, muxes and register blocks, AXI4-Stream FIFOs, arbiters and width converters, DMA engines, and packet formatters/parsers for building SoC and FPGA shell fabrics."),
    "CDC": ("Clock-domain crossing (CDC) IP", "Bit, pulse and toggle synchronizers, reset synchronizers, and AXI4-Lite / AXI4-Stream bridges for moving control and data safely between unrelated clocks."),
    "Common": ("DSP building blocks", "FIR and CIC filters, CORDIC, DDS, edge detection, and encoders for signal-conditioning, sample-rate conversion and control-loop datapaths."),
    "FIFO": ("FIFOs", "Synchronous, asynchronous (dual-clock), first-word-fall-through and packet FIFOs for buffering bursty or rate-mismatched traffic."),
    "Integrity": ("CRC, ECC &amp; data integrity IP", "CRC-8/16/32, checksums, parity, LFSRs and an ECC memory controller for protecting storage and communication links."),
    "Math": ("Arithmetic IP", "Pipelined multiply-accumulate for filters, correlators and neural-network style accumulation."),
    "Memory": ("Memory IP", "Single-port, simple dual-port and true dual-port RAMs, ROMs, register files and a memory arbiter, written to infer FPGA block RAM."),
    "Peripherals": ("Peripheral interface IP", "UART, I2C, SPI, I2S, SDIO, SPI flash, GPIO, interrupt controller, Ethernet MAC interface, USB full-speed SIE and a PCIe transaction-layer endpoint."),
    "Scalers": ("Video scaler &amp; image pipeline IP", "Nearest, bilinear, bicubic, Lanczos, polyphase, edge-directed and anisotropic scalers, sharpening, frame buffers and the AXI control plane around them."),
    "Timing": ("Timers, counters &amp; clock generation", "Baud generators, NCOs, PWM, pulse generators, frequency counters, interval/timeout timers, timestamps and a watchdog."),
}

# Long-form design notes, linked from the matching module pages.
_NOTE_ASYNC = ("/design-notes/async-fifo-gray-code-cdc.html", "Design notes: async FIFO and Gray-code CDC")
_NOTE_CRC = ("/design-notes/crc-32-systemverilog.html", "Design notes: CRC-32 parameters, reflection and parallel bytes")
_NOTE_RESET = ("/design-notes/reset-synchronizer.html", "Design notes: asynchronous assert, synchronous release")
_NOTE_UART = ("/design-notes/uart-fractional-baud-generator.html", "Design notes: UART fractional baud generator")
_NOTE_SCALER = ("/design-notes/fpga-image-scaler-comparison.html", "Design notes: nearest vs bilinear vs bicubic vs Lanczos")
DESIGN_NOTES = {
    "async_fifo": _NOTE_ASYNC,
    "axis_async_bridge": _NOTE_ASYNC,
    "axi_stream_width_converter": ("/design-notes/axi-stream-width-converter.html", "Design notes: AXI-Stream width converter"),
    "crc32": _NOTE_CRC, "crc16": _NOTE_CRC, "crc8": _NOTE_CRC,
    "reset_sync": _NOTE_RESET, "reset_ctrl": _NOTE_RESET,
    "uart": _NOTE_UART, "uart_rx": _NOTE_UART, "uart_tx": _NOTE_UART, "baud_nco": _NOTE_UART,
    **{m: _NOTE_SCALER for m in ("scaler_nearest", "scaler_bilinear", "scaler_bicubic", "scaler_lanczos",
                                 "scaler_polyphase", "scaler_dda", "banked_framebuf", "scaler_ctrl")},
}

# Tokens in module directory names that need special casing in titles.
NAME_TOKENS = {
    "axi": "AXI", "axi4": "AXI4", "axis": "AXI-Stream", "axil": "AXI4-Lite", "cdc": "CDC",
    "fifo": "FIFO", "crc8": "CRC-8", "crc16": "CRC-16", "crc32": "CRC-32", "ecc": "ECC",
    "lfsr": "LFSR", "mac": "MAC", "rom": "ROM", "ram": "RAM", "dma": "DMA", "i2c": "I2C",
    "i2s": "I2S", "spi": "SPI", "uart": "UART", "rx": "RX", "tx": "TX", "usb": "USB",
    "fs": "Full-Speed", "sie": "SIE", "eth": "Ethernet", "pcie": "PCIe", "tl": "Transaction-Layer",
    "ep": "Endpoint", "sdio": "SDIO", "gpio": "GPIO", "intc": "Interrupt Controller",
    "pwm": "PWM", "nco": "NCO", "dds": "DDS", "fir": "FIR", "cic": "CIC", "cordic": "CORDIC",
    "mip": "MIP", "dda": "DDA", "cas": "CAS", "if": "Interface", "ctrl": "Controller",
    "regs": "Registers", "regbus": "Register Bus", "framebuf": "Frame Buffer", "onehot": "One-Hot",
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


def pretty_name(module: str) -> str:
    """axi4_lite_mux -> AXI4-Lite Mux, axi_stream_fifo -> AXI-Stream FIFO."""
    name = re.sub(r"(^|_)axi4_lite(?=_|$)", r"\1AXI4-Lite", module)
    name = re.sub(r"(^|_)axi_stream(?=_|$)", r"\1AXI-Stream", name)
    name = name.replace("dual_port", "Dual-Port").replace("single_port", "Single-Port")
    name = name.replace("edge_directed", "Edge-Directed")
    words = " ".join(NAME_TOKENS.get(t, t if not t.islower() else t.capitalize()) for t in name.split("_"))
    # scaler_bicubic -> Bicubic Scaler
    if words.startswith("Scaler ") and words != "Scaler Controller":
        return words[len("Scaler "):] + " Scaler"
    return words


def top_level_clauses(sentence: str) -> list[str]:
    """Splits after commas/semicolons that are not inside parentheses."""
    clauses, depth, start = [], 0, 0
    for i, ch in enumerate(sentence):
        depth += (ch == "(") - (ch == ")")
        if ch in ",;" and depth == 0:
            clauses.append(sentence[start:i + 1].strip())
            start = i + 1
    clauses.append(sentence[start:].strip())
    return [c for c in clauses if c]


def short_description(desc: str, limit: int = 160) -> str:
    """First sentence(s) of a long generator description, sized for search snippets."""
    text = re.sub(r"([a-z])- ([a-z])", r"\1-\2", " ".join(desc.split()))   # undo comment line-wrap hyphens
    sentences = [s for s in re.split(r"(?<=\.)\s+", text) if s and not re.match(r"Version \d|\w+ - ", s)]   # drop "Version x", "Clocks - ..." boilerplate
    out = sentences[0] if sentences else text
    for s in sentences[1:]:
        if len(out) >= 90:
            break
        if len(out) + 1 + len(s) > limit:
            # take the longest leading clause of the next sentence that still fits
            clauses = top_level_clauses(s)
            part = ""
            for c in clauses:
                if len(out) + 1 + len(part) + len(c) + 1 > limit:
                    break
                part = f"{part} {c}".strip()
            if part:
                out += " " + part.rstrip(",;") + "."
            break
        out += " " + s
    if len(out) > limit:
        out = out[:limit - 1].rsplit(" ", 1)[0].rstrip(",;:-") + "…"
    tail = " Synthesizable SystemVerilog for FPGA and ASIC."
    if "SystemVerilog" not in out and len(out) + len(tail) <= limit:
        out += tail
    return out


def apply_module_title(content: str, pretty: str, desc: str) -> str:
    title = f"{pretty} – SystemVerilog IP Core | FPGA Cores 4U"
    content = re.sub(r"<title>.*?</title>", lambda _: f"<title>{html.escape(title, quote=False)}</title>", content, count=1, flags=re.S)
    content = re.sub(r'<meta name="description" content="[^"]*">',
                     lambda _: f'<meta name="description" content="{html.escape(desc, quote=True)}">', content, count=1)
    return re.sub(r"<h1>.*?</h1>", lambda _: f"<h1>{html.escape(pretty, quote=False)}</h1>", content, count=1, flags=re.S)


def add_software_jsonld(content: str, pretty: str, desc: str, canonical_url: str, category: str,
                        version: str | None = None, date: str | None = None, image: str | None = None) -> str:
    if "SoftwareSourceCode" in content or "</head>" not in content:
        return content
    data = {
        "@context": "https://schema.org",
        "@type": "SoftwareSourceCode",
        "name": f"{pretty} SystemVerilog IP core",
        "description": desc,
        "url": canonical_url,
        "programmingLanguage": "SystemVerilog",
        "codeRepository": "https://github.com/pbarcelona-ai/digital_ip",
        "keywords": f"{category}, SystemVerilog, Verilog, FPGA, ASIC, RTL, IP core",
        "license": "https://opensource.org/licenses/MIT",
        "author": {"@type": "Organization", "name": "FPGA Cores 4U", "url": f"{BASE_URL}/"},
    }
    if version:
        data["version"] = version
    if date:
        data["dateModified"] = date
    if image:
        data["image"] = image
    snippet = f'<script type="application/ld+json">{json.dumps(data)}</script>'
    return content.replace("</head>", snippet + "</head>", 1)


def slug(module: str) -> str:
    return module.replace("_", "-")


def ip_path(module: str) -> str:
    """Short public URL path of a module page: /ip/async-fifo/."""
    return f"/ip/{slug(module)}/"


CATALOG_PATH = "/ip/"
CATALOG_URL = f"{BASE_URL}{CATALOG_PATH}"
OG_DIR = REPO_ROOT / "og"

HEADER_FIELD_RE = re.compile(r"\b(Clocks?|Reset|Latency|Throughput|Timing|Errors)\s+-\s+")
FIELD_LABELS = {"Clock": "Clocking", "Reset": "Reset", "Latency": "Latency",
                "Throughput": "Throughput", "Timing": "Timing constraints", "Errors": "Error handling"}

PAGE_STYLE = (
    "<style>"
    ".spec-table{width:100%;border-collapse:collapse;margin:8px 0 24px;font-size:13px}"
    ".spec-table th,.spec-table td{padding:8px 10px;border-bottom:1px solid var(--border);text-align:left;vertical-align:top}"
    ".spec-table th{color:var(--heading);font-weight:600;white-space:nowrap;width:1%}"
    ".spec-table code{background:var(--code-bg);padding:1px 5px;border-radius:3px}"
    ".diagram{margin:8px 0 24px;padding:16px;background:#fff;border-radius:6px;overflow-x:auto}"
    ".diagram img{display:block;max-width:100%;height:auto;margin:0 auto}"
    ".diagram figcaption{margin-top:8px;font-size:12px;text-align:center}"
    ".topnav{display:flex;gap:16px}"
    ".updated{margin:12px 0 0;font-size:12px}"
    "</style>"
)


def split_header(desc: str) -> tuple[str, str | None, dict[str, str]]:
    """RTL header description -> (narrative, version, {Clock/Reset/Latency/...: text})."""
    text = re.sub(r"([a-z])- ([a-z])", r"\1-\2", " ".join(desc.split()))
    vm = re.search(r"\bVersion (\d+\.\d+\.\d+)", text)
    text = re.sub(r"\s*\bVersion \d+\.\d+\.\d+\.?", "", text)
    parts = HEADER_FIELD_RE.split(text)
    fields: dict[str, str] = {}
    for key, value in zip(parts[1::2], parts[2::2]):
        key = "Clock" if key.startswith("Clock") else key
        value = value.strip()
        value = value[:1].upper() + value[1:]
        fields[key] = f"{fields[key]} {value}" if key in fields else value
    return parts[0].strip(), (vm.group(1) if vm else None), fields


def load_status() -> dict[str, dict[str, str]]:
    """Per-IP simulation/synthesis results from the submodule's STATUS.md table."""
    path = OUT_ROOT / "docs" / "STATUS.md"
    rows: dict[str, dict[str, str]] = {}
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 8 and re.fullmatch(r"[a-z0-9_]+", cells[0]):
            rows[cells[0]] = dict(zip(("sim", "yosys", "lut", "ff", "bram", "dsp"), cells[2:8]))
    # scaler family: results table in SCALER_README.md
    # | Module | Parameters | LUT | LUT RAM | FF | CARRY4 | BRAM36 | DSP48E1 | Time (s) |
    scaler_readme = OUT_ROOT / "SCALER_README.md"
    if scaler_readme.is_file():
        for line in scaler_readme.read_text(encoding="utf-8").splitlines():
            cells = [c.strip().replace(",", "") for c in line.strip().strip("|").split("|")]
            m = re.fullmatch(r"([a-z0-9_]+)\s*(?:\((.*)\))?", cells[0]) if len(cells) == 9 else None
            if m and cells[2].isdigit() and m.group(1) not in rows:
                config = ", ".join(c for c in (cells[1].replace("\u00d7", "x"), m.group(2)) if c)
                rows[m.group(1)] = {"lut": cells[2], "ff": cells[4], "bram": f"0/{cells[6]}", "dsp": cells[7],
                                    "config": config}
    return rows


def utilization_text(row: dict[str, str] | None, sep: str = " · ") -> str:
    if not row or not row.get("lut", "").isdigit():
        return ""
    parts = [f"{row['lut']} LUT", f"{row['ff']} FF"]
    b18, _, b36 = row.get("bram", "0/0").partition("/")
    if b18.strip() not in ("", "0"):
        parts.append(f"{b18.strip()} BRAM18")
    if b36.strip() not in ("", "0"):
        parts.append(f"{b36.strip()} BRAM36")
    if row.get("dsp", "0") not in ("", "0"):
        parts.append(f"{row['dsp']} DSP")
    return sep.join(parts)


def parse_parameters(snippet: Path) -> list[tuple[str, str, str]]:
    """(name, default, comment) for each parameter in the module header snippet."""
    if not snippet.is_file():
        return []
    out = []
    for line in snippet.read_text(encoding="utf-8").splitlines():
        code, _, comment = line.partition("//")
        m = re.match(r"\s*parameter\s+(?:(?:int|integer|logic|bit|real|string)\b\s*(?:(?:un)?signed\s*)?(?:\[[^\]]*\]\s*)?)?(\w+)\s*=\s*(.+?)\s*,?\s*$", code)
        if m:
            value = m.group(2).rstrip(",").strip()
            out.append((m.group(1), value if len(value) <= 48 else value[:45] + "…", comment.strip()))
    return out


def header_date(src: Path | None) -> str | None:
    if not src or not src.is_file():
        return None
    m = re.search(r"^// Date:\s*(\d{4}-\d{2}-\d{2})", src.read_text(encoding="utf-8", errors="replace"), re.M)
    return m.group(1) if m else None


def diagram_section(category_dir: str, module: str, pretty: str) -> str:
    """Embeds the RTL hierarchy SVG when the core has submodules worth showing."""
    docs = SUBMODULE_IP / category_dir / module / "docs"
    svg, dot = docs / "block_diagram.svg", docs / "block_diagram.dot"
    if not svg.is_file() or not dot.is_file():
        return ""
    nodes = re.findall(r'label="([^"\\]+)\\n\(([^)]+)\)"', dot.read_text(encoding="utf-8"))
    if len(nodes) < 2:
        return ""
    top = nodes[0][0]
    children = ", ".join(f"{name} ({inst})" for name, inst in nodes[1:])
    alt = f"RTL hierarchy of the {pretty} SystemVerilog IP core: {top} instantiates {children}."
    head = svg.read_text(encoding="utf-8")[:2000]
    wm, hm = re.search(r'width="([\d.]+)pt"', head), re.search(r'height="([\d.]+)pt"', head)
    size = f' width="{round(float(wm.group(1)) * 4 / 3)}" height="{round(float(hm.group(1)) * 4 / 3)}"' if wm and hm else ""
    src = f"/digital_ip/ip/{category_dir}/{module}/docs/block_diagram.svg"
    return (
        '<section class="content"><article>'
        '<p class="eyebrow">Architecture</p><h2>RTL hierarchy</h2>'
        f'<figure class="diagram"><img src="{src}" alt="{html.escape(alt, quote=True)}"{size} loading="lazy"></figure>'
        '</article></section>'
    )


def svg_size(svg: Path) -> str:
    """width / height attributes (px) from a Graphviz SVG's pt size, so the page reserves the space."""
    head = svg.read_text(encoding="utf-8", errors="replace")[:2000]
    wm, hm = re.search(r'width="([\d.]+)pt"', head), re.search(r'height="([\d.]+)pt"', head)
    return f' width="{round(float(wm.group(1)) * 4 / 3)}" height="{round(float(hm.group(1)) * 4 / 3)}"' if wm and hm else ""


def figure(src: str, alt: str, size: str, caption: str) -> str:
    """A diagram that scales to the page; the image links to the full-size SVG for zooming."""
    return (f'<figure class="diagram"><a href="{src}" target="_blank" rel="noopener">'
            f'<img src="{src}" alt="{html.escape(alt, quote=True)}"{size} loading="lazy"></a>'
            f'<figcaption class="quiet">{caption} <a href="{src}" target="_blank" rel="noopener">Open full size</a></figcaption>'
            '</figure>')


def architecture_diagrams_section(category_dir: str, module: str, pretty: str) -> str:
    """Hand-drawn block diagrams (<module>_block_diagram.svg, <module>_fsm.svg) and the generated
    data-flow diagram (<module>_dataflow.svg, ip/scripts/make_dataflow_diagrams.py) of a core."""
    docs = SUBMODULE_IP / category_dir / module / "docs"
    base = f"/digital_ip/ip/{category_dir}/{module}/docs"
    parts = []
    for svg in sorted(docs.glob("*_block_diagram.svg")) + sorted(docs.glob("*_fsm.svg")):
        kind = "state machine" if svg.stem.endswith("_fsm") else "block diagram"
        parts.append(f"<h2>{pretty} {kind}</h2>" + figure(
            f"{base}/{svg.name}", f"{kind.capitalize()} of the {pretty} SystemVerilog IP core.", svg_size(svg),
            f"Architecture {kind}, with module, instance and signal names from the RTL."))
    flow = docs / f"{module}_dataflow.svg"
    if flow.is_file():
        parts.append("<h2>Data flow</h2>" + figure(
            f"{base}/{flow.name}",
            f"Data-flow diagram of the {pretty} SystemVerilog IP core: ports, registers, combinational "
            "signals and sub-module instances with the signal names from the RTL.",
            svg_size(flow),
            "Generated from the RTL: inputs on the left, outputs on the right, every register (double border) and "
            "combinational signal with its source always block, sub-modules in yellow, AXI buses as one teal line."))
    if not parts:
        return ""
    return ('<section class="content"><article><p class="eyebrow">Architecture</p>'
            + "".join(parts) + "</article></section>")


def spec_section(fields: dict[str, str], version: str | None, date: str | None,
                 status: dict[str, str] | None, params: list[tuple[str, str, str]]) -> str:
    rows = [("Language", "Synthesizable SystemVerilog (IEEE 1800-2017)")]
    if version:
        rows.append(("Version", f"{version} (updated {date})" if date else version))
    elif date:
        rows.append(("Last updated", date))
    for key, label in FIELD_LABELS.items():
        if key in fields:
            rows.append((label, html.escape(fields[key], quote=False)))
    util = utilization_text(status, " / ")
    if util:
        cfg = status.get("config", "") if status else ""
        cfg = "default parameters" if cfg in ("", "(defaults)") else html.escape(cfg)
        rows.append(("Utilization", f'{util} <span class="quiet">(Yosys 0.33 synth_xilinx, 7-series, {cfg})</span>'))
    if status and status.get("sim") == "PASS":
        rows.append(("Verification", "Self-checking testbench, passing on Icarus Verilog 12"))
    rows.append(("License", "MIT"))
    body = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows)
    out = ('<section class="content"><article>'
           '<p class="eyebrow">Datasheet</p><h2>Key specifications</h2>'
           f'<table class="spec-table"><tbody>{body}</tbody></table>')
    if params:
        prow = "".join(f"<tr><td><code>{html.escape(n)}</code></td><td><code>{html.escape(v)}</code></td>"
                       f"<td>{html.escape(c)}</td></tr>" for n, v, c in params)
        out += ('<h2>Parameters</h2><table class="spec-table"><thead><tr><th>Parameter</th><th>Default</th>'
                f'<th>Notes</th></tr></thead><tbody>{prow}</tbody></table>')
    return out + "</article></section>"


def enhance_module_body(content: str, narrative: str, version: str | None, date: str | None,
                        extra_sections: str) -> str:
    """Shorter lede, visible version/date, spec + diagram sections after the hero, site navigation."""
    lede = html.escape(narrative, quote=False)
    content = re.sub(r'<p class="lede">.*?</p>', lambda _: f'<p class="lede">{lede}</p>', content, count=1, flags=re.S)
    if date:
        stamp = (f'<p class="quiet updated">{"Version " + version + " &middot; " if version else ""}'
                 f'Last updated <time datetime="{date}">{date}</time></p>')
        content = re.sub(r'(<p class="lede">.*?</p>)', lambda m: m.group(1) + stamp, content, count=1, flags=re.S)
    content = re.sub(r'(<section class="hero">.*?</section>)', lambda m: m.group(1) + extra_sections, content, count=1, flags=re.S)
    content = content.replace('href="../digital_ip_catalog.html"', f'href="{CATALOG_PATH}"')
    return add_site_nav(content).replace("</head>", PAGE_STYLE + "</head>", 1)


def add_site_nav(content: str) -> str:
    """Adds a Search link next to the topbar's existing right-hand link."""
    return re.sub(r'(<header class="topbar">\s*<a class="brand"[^>]*>.*?</a>)\s*(<a [^>]*>[^<]*</a>)\s*(</header>)',
                  lambda m: f'{m.group(1)}<span class="topnav"><a href="/search.html">Search</a>{m.group(2)}</span>{m.group(3)}',
                  content, count=1, flags=re.S)


def redirect_stub(target_path: str, title: str) -> str:
    url = f"{BASE_URL}{target_path}"
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        f'<title>{html.escape(title)} | FPGA Cores 4U</title>'
        f'<link rel="canonical" href="{url}">'
        f'<meta http-equiv="refresh" content="0; url={target_path}">'
        '</head><body>'
        f'<p>This page has moved to <a href="{target_path}">{url}</a>.</p>'
        '</body></html>\n'
    )


def publish_short_url(content: str, source_dir: str, target_path: str) -> None:
    """Writes the page at its short URL. <base> keeps its relative asset links resolving to source_dir."""
    content = content.replace("<head>", f'<head><base href="{source_dir}">', 1)
    content = re.sub(r'<main class="((?:page-)?shell)">', r'<main class="\1" data-pagefind-body>', content, count=1)
    out = REPO_ROOT / target_path.strip("/") / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")


def set_og_image(content: str, image_url: str) -> str:
    content = re.sub(r'(<meta property="og:image" content=")[^"]*', lambda m: m.group(1) + image_url, content, count=1)
    return re.sub(r'(<meta name="twitter:image" content=")[^"]*', lambda m: m.group(1) + image_url, content, count=1)


def add_canonical_only(content: str, canonical_url: str) -> str:
    if 'rel="canonical"' in content or "</title>" not in content:
        return content
    return content.replace("</title>", f'</title><link rel="canonical" href="{canonical_url}">', 1)


def canonicalize_per_module_copies() -> int:
    """ip/<category>/<module>/docs/index.html duplicates the module page; point it at the short URL."""
    count = 0
    for page in SUBMODULE_IP.glob("*/*/docs/index.html"):
        module = page.parent.parent.name
        if not (OUT_ROOT / "docs" / module / "index.html").is_file():
            continue
        content = page.read_text(encoding="utf-8")
        new = add_canonical_only(content, f"{BASE_URL}{ip_path(module)}")
        if new != content:
            page.write_text(new, encoding="utf-8")
            count += 1
    return count


def update_home_page(categories: dict[str, list[str]], titles: dict[str, str]) -> None:
    """Fills the IP index between the markers in the site's index.html."""
    start, end = "<!-- IP-INDEX:START -->", "<!-- IP-INDEX:END -->"
    page = REPO_ROOT / "index.html"
    content = page.read_text(encoding="utf-8")
    if start not in content or end not in content:
        return
    parts = []
    for category, modules in categories.items():
        mods = [m for m in modules if (OUT_ROOT / "docs" / m / "index.html").is_file()]
        if not mods:
            continue
        heading, intro = HOME_CATEGORIES.get(category, (category, ""))
        links = "".join(f'<li><a href="{ip_path(m).lstrip("/")}">{titles.get(m, m)}</a></li>' for m in mods)
        parts.append(f'<section class="ip-category"><h3>{heading}</h3><p>{intro}</p><ul class="ip-list">{links}</ul></section>')
    block = start + "\n" + "\n".join(parts) + "\n" + end
    content = re.sub(re.escape(start) + r".*?" + re.escape(end), lambda _: block, content, count=1, flags=re.S)
    page.write_text(content, encoding="utf-8")


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
    if module is None:
        items.append({"@type": "ListItem", "position": 2, "name": "SystemVerilog IP Catalog", "item": canonical_url})
    else:
        items.append({"@type": "ListItem", "position": 2, "name": "SystemVerilog IP Catalog", "item": CATALOG_URL})
        items.append({"@type": "ListItem", "position": 3, "name": module, "item": canonical_url})
    data = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items}
    snippet = f'<script type="application/ld+json">{json.dumps(data)}</script>'
    if "</head>" not in content:
        return content
    return content.replace("</head>", snippet + "</head>", 1)


def add_typical_applications(content: str, category: str, module: str, siblings: list[str], titles: dict[str, str]) -> str:
    if "Typical applications" in content or not siblings:
        return content
    links = "".join(f'<li><a href="{ip_path(s)}">{titles.get(s, s)}</a></li>' for s in siblings[:5])
    note = DESIGN_NOTES.get(module)
    notes = f'<h2>Design notes</h2><p><a href="{note[0]}">{note[1]}</a></p>' if note else ""
    section = (
        '<section class="content"><article>'
        f'<p class="eyebrow">{category}</p><h2>Typical applications</h2>'
        f'<p>{CATEGORY_BLURBS.get(category, "")}</p>'
        '<h2>Related modules</h2>'
        f'<ul class="file-list">{links}</ul>'
        f'{notes}'
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

    titles = {module: pretty_name(module) for module in module_to_category}
    status = load_status()

    published = 0
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

        pretty, cat_dir = titles[module], category.lower()
        canonical = f"{BASE_URL}{ip_path(module)}"
        dm = re.search(r'<meta name="description" content="([^"]*)"', content)
        full = html.unescape(dm.group(1)) if dm else f"{pretty} IP core."
        narrative, version, fields = split_header(full)
        desc = short_description(full)
        date = header_date(resolve_primary_source(cat_dir, module))
        card = f"{BASE_URL}/og/{slug(module)}.png"
        make_card(OG_DIR / f"{slug(module)}.png", pretty, f"SystemVerilog IP core \u00b7 {category}",
                  desc, utilization_text(status.get(module)))

        content = apply_module_title(content, pretty, desc)
        content = add_seo_tags(content, canonical)
        content = set_og_image(content, card)
        content = add_software_jsonld(content, pretty, desc, canonical, category, version, date, card)
        content = add_favicon_and_theme(content)
        content = add_breadcrumbs(content, pretty, canonical)
        siblings = [m for m in categories.get(category, []) if m != module]
        content = add_typical_applications(content, category, module, siblings, titles)
        extra = (spec_section(fields, version, date, status.get(module),
                              parse_parameters(OUT_ROOT / "docs" / module / f"{module}.sv"))
                 + diagram_section(cat_dir, module, pretty)
                 + architecture_diagrams_section(cat_dir, module, pretty))
        content = enhance_module_body(content, narrative or desc, version, date, extra)

        publish_short_url(content, f"/digital_ip/ip/docs/{module}/", ip_path(module))
        page.write_text(redirect_stub(ip_path(module), pretty), encoding="utf-8")
        published += 1

    # Catalog: published at /ip/, old locations redirect there.
    n = len(module_to_category)
    content = re.sub(r'href="([a-z0-9_]+)/index\.html">([^<]*)</a>',
                     lambda m: f'href="{ip_path(m.group(1))}">{titles[m.group(1)]}</a>' if m.group(1) in module_to_category else m.group(0),
                     catalog_html)
    title = f"SystemVerilog IP Core Catalog \u2013 {n} FPGA/ASIC Cores | FPGA Cores 4U"
    desc = (f"Catalog of {n} synthesizable SystemVerilog IP cores for FPGA and ASIC: AXI interconnect, CDC, "
            "FIFOs, DSP, CRC/ECC, memories, peripherals, timers and video scalers. MIT licensed.")
    content = re.sub(r"<title>.*?</title>", lambda _: f"<title>{html.escape(title, quote=False)}</title>", content, count=1, flags=re.S)
    content = re.sub(r'<meta name="description" content="[^"]*">',
                     lambda _: f'<meta name="description" content="{html.escape(desc)}">', content, count=1)
    content = re.sub(r"<h1>.*?</h1>", "<h1>SystemVerilog IP cores</h1>", content, count=1, flags=re.S)
    content = re.sub(r"<link rel=\"canonical\"[^>]*>", "", content)   # replaced by add_seo_tags below
    content = re.sub(r'<meta (?:property|name)="(?:og|twitter):[^"]*" content="[^"]*">', "", content)
    content = add_seo_tags(content, CATALOG_URL)
    make_card(OG_DIR / "catalog.png", "SystemVerilog IP Core Catalog", "FPGA Cores 4U \u00b7 MIT licensed",
              f"{n} synthesizable cores for FPGA and ASIC: AXI interconnect, CDC, FIFOs, DSP, CRC/ECC, peripherals, timers and video scalers.")
    content = set_og_image(content, f"{BASE_URL}/og/catalog.png")
    content = add_favicon_and_theme(content)
    content = add_breadcrumbs(content, None, CATALOG_URL)
    content = content.replace('<a class="brand" href="index.html">', f'<a class="brand" href="{CATALOG_PATH}">', 1)
    content = add_site_nav(content)
    content = content.replace('<div class="actions">', '<div class="actions"><a href="/search.html">Search all cores</a>', 1)
    publish_short_url(content.replace("</head>", PAGE_STYLE + "</head>", 1), "/digital_ip/ip/docs/", CATALOG_PATH)
    catalog_path.write_text(redirect_stub(CATALOG_PATH, "SystemVerilog IP catalog"), encoding="utf-8")
    hosted_copy = OUT_ROOT / "docs" / "digital_ip_catalog.html"
    if hosted_copy.is_file():
        hosted_copy.write_text(redirect_stub(CATALOG_PATH, "SystemVerilog IP catalog"), encoding="utf-8")

    # Scaler atlas: stays at its URL; module links go straight to the short URLs.
    atlas = OUT_ROOT / "tools" / "docs" / "index.html"
    if atlas.is_file():
        canonical = f"{BASE_URL}/digital_ip/ip/tools/docs/index.html"
        content = atlas.read_text(encoding="utf-8")
        content = re.sub(r'href="\.\./\.\./docs/([a-z0-9_]+)/index\.html"', lambda m: f'href="{ip_path(m.group(1))}"', content)
        content = add_seo_tags(content, canonical)
        content = add_favicon_and_theme(content)
        content = add_breadcrumbs(content, None, canonical)
        content = content.replace("<body", "<body data-pagefind-body", 1)
        atlas.write_text(content, encoding="utf-8")

    # Vision-system microsite: self-canonical + OG tags.
    for page in sorted((SUBMODULE_ROOT / "image_processing" / "vision_system" / "docs" / "site").glob("*.html")):
        rel = page.relative_to(REPO_ROOT).as_posix()
        content = page.read_text(encoding="utf-8")
        content = add_seo_tags(content, f"{BASE_URL}/{rel}")
        content = content.replace("<body", "<body data-pagefind-body", 1)
        page.write_text(content, encoding="utf-8")

    copies = canonicalize_per_module_copies()
    update_home_page(categories, titles)

    print(f"[build] done: {published} module pages published under /ip/, "
          f"{len(resolved)} module snippets, {len(shared_written)} shared snippets, "
          f"{copies} per-module copies canonicalized")


if __name__ == "__main__":
    sys.exit(main())

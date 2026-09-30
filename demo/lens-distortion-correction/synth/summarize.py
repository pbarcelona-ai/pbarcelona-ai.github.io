#!/usr/bin/env python3
# ***************
# Filename: summarize.py
# Author: Paul Barcelona
# Description: Parses a Yosys utilization_hier.rpt and prints a compact
# resource line (LUT, FF, DSP48, BRAM, SRL, CARRY4, total cells). Uses the
# rolled-up "design hierarchy" block when present (multi-module designs),
# otherwise the module's own block. Used by run_yosys.sh and
# run_all_yosys.sh.
#
# The cell-line regex is deliberately loose (any amount of leading
# whitespace, not a fixed 4+ spaces) because Yosys's `stat` indentation
# has been observed to vary by version/build. If this ever prints all
# zeros despite a nonzero total cell count, that is NOT this script
# silently failing -- see the warning it prints to stderr in that case,
# and check yosys.log: yosys_common.ys's post-synth_xilinx `select
# -assert-any`/`-assert-none` check (added after exactly this symptom
# was reported on a macOS/Homebrew Yosys install) should have already
# caught a design that didn't actually map to Xilinx primitives and
# made the run fail loudly instead of reaching this point at all.
# Date: September 28, 2026
# ***************
"""Usage: summarize.py <utilization_hier.rpt>   -> one-line resource summary"""
import re, sys

def parse(path):
    text = open(path).read()
    blocks = re.split(r"\n=== (.+?) ===\n", text)
    # blocks: [pre, name1, body1, name2, body2, ...]
    named = {blocks[i]: blocks[i + 1] for i in range(1, len(blocks) - 1, 2)}
    body = named.get("design hierarchy")
    if body is None:                       # single-module design: last block
        body = blocks[-1] if len(blocks) > 1 else text
    cells = {}
    # Loose on leading whitespace (>=1 space/tab) -- some Yosys builds
    # indent `stat`'s per-cell-type lines differently than others.
    for m in re.finditer(r"^[ \t]+([A-Za-z_$][A-Za-z0-9_$.\\]*)\s+(\d+)\s*$", body, re.M):
        cells[m.group(1)] = cells.get(m.group(1), 0) + int(m.group(2))
    m = re.search(r"Number of cells:\s+(\d+)", body)
    total = int(m.group(1)) if m else sum(cells.values())
    return cells, total

def summary(path):
    c, total = parse(path)
    lut = sum(v for k, v in c.items() if re.fullmatch(r"LUT[1-6]", k))
    ff = sum(v for k, v in c.items() if k.startswith("FD"))
    dsp = c.get("DSP48E1", 0)
    bram36, bram18 = c.get("RAMB36E1", 0), c.get("RAMB18E1", 0)
    srl = c.get("SRL16E", 0) + c.get("SRLC32E", 0)
    carry4 = c.get("CARRY4", 0)
    if total > 0 and lut == ff == dsp == bram36 == bram18 == srl == carry4 == 0:
        print(
            f"WARNING [summarize.py]: {path} lists {total} cells but none matched "
            "any recognized Xilinx primitive name (LUT*, FD*, DSP48E1, RAMB36E1/"
            "RAMB18E1, SRL16E/SRLC32E, CARRY4). This almost always means "
            "synth_xilinx did not actually map to Xilinx primitives on this "
            "Yosys install (missing techlib data files or a broken ABC "
            "integration are common causes, e.g. with some Homebrew installs on "
            "macOS) -- inspect the cell names actually present in this report, "
            "and check yosys.log in the same directory for errors/warnings "
            "around the synth_xilinx step. `yosys -V` and confirming `yosys "
            "-p 'help synth_xilinx'` runs are a good first check.",
            file=sys.stderr,
        )
    return dict(lut=lut, ff=ff, dsp=dsp, bram36=bram36, bram18=bram18,
                srl=srl, carry4=carry4, cells=total)

def line(s):
    return (f"LUT={s['lut']}  FF={s['ff']}  DSP48E1={s['dsp']}  "
            f"RAMB36={s['bram36']}  RAMB18={s['bram18']}  SRL={s['srl']}  "
            f"CARRY4={s['carry4']}  cells={s['cells']}")

if __name__ == "__main__":
    print(line(summary(sys.argv[1])))

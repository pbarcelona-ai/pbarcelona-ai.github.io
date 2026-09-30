#!/usr/bin/env bash
# Fast smoke test: drives coord_gen.sv directly against an independent
# golden model for identity, radial (barrel), tangential distortion, and
# camera calibration. Runs in seconds -- use this for a quick sanity
# check; use run.sh for the full image-streaming regression.
#
# Usage:
#   ./run_smoke.sh
set -e
cd "$(dirname "$0")"

DEFS=""
[ "${VCD:-0}" = "1" ] && DEFS="-DDUMP_VCD"

iverilog -g2012 $DEFS -o smoke.vvp \
  ppm_io_pkg.sv golden_model_pkg.sv \
  ../rtl/barrel_pkg.sv ../rtl/distortion_model_pkg.sv \
  ../ip/mulq/mulq_s.sv ../ip/coord_gen/coord_gen.sv \
  tb_smoke.sv

vvp smoke.vvp

# Optional waveform viewing: VCD=1 dumps waves.vcd; SURFER=1 opens it.
if [ "${VCD:-0}" = "1" ] && [ "${SURFER:-0}" = "1" ]; then
  ../synth/view_waves.sh waves.vcd
fi

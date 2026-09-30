#!/usr/bin/env bash
# Builds and runs coord_gen's self-checking testbench.
# Depends on barrel_pkg.sv and distortion_model_pkg.sv, in ../../rtl/,
# this project's shared package location, plus mulq_s.sv (the pipelined
# multiplier every multiply goes through), in the sibling ip/mulq/
# directory.
#
# Usage:
#   ./run.sh
set -e
cd "$(dirname "$0")"

DEFS=""
[ "${VCD:-0}" = "1" ] && DEFS="-DDUMP_VCD"

iverilog -g2012 $DEFS -o tb_coord_gen.vvp \
  ../../rtl/barrel_pkg.sv ../../rtl/distortion_model_pkg.sv \
  ../mulq/mulq_s.sv \
  coord_gen.sv tb_coord_gen.sv
vvp tb_coord_gen.vvp

# Optional waveform viewing (see ../../synth/view_waves.sh): VCD=1 dumps
# waves.vcd; add SURFER=1 to open it in Surfer afterwards.
if [ "${VCD:-0}" = "1" ] && [ "${SURFER:-0}" = "1" ]; then
  ../../synth/view_waves.sh waves.vcd
fi

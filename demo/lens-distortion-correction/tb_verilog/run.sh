#!/usr/bin/env bash
# ***************
# Filename: run.sh
# Author: Paul Barcelona
# Description: Builds and runs the pure-Verilog (no Python) self-checking
# top-level testbench under Icarus Verilog. This demo always uses
# short-edge-64 frames. VCD=1 dumps waves.vcd (view with
# ../synth/view_waves.sh, i.e. Surfer).
# Date: September 28, 2026
# ***************
# Usage:
#   ./run.sh              square 64x64, portrait 64x96, landscape 96x64
#   VCD=1 ./run.sh         ... and write work/waves.vcd
set -e
cd "$(dirname "$0")"
mkdir -p work

DEFS=""
[ "${VCD:-0}" = "1" ] && DEFS="-DDUMP_VCD"

iverilog -g2012 $DEFS -o sim.vvp \
  ppm_io_pkg.sv golden_model_pkg.sv \
  ../rtl/barrel_pkg.sv ../rtl/distortion_model_pkg.sv \
  ../ip/fixed_recip/fixed_recip.sv ../ip/mulq/mulq_s.sv ../ip/coord_gen/coord_gen.sv \
  ../ip/bilinear/bilinear.sv ../ip/frame_buffer/frame_buffer.sv \
  ../rtl/axis_in_ctrl.sv ../rtl/axis_out_ctrl.sv ../rtl/axi_lite_regs.sv \
  ../rtl/image_system_demo.sv \
  tb_image_system_demo.sv

vvp sim.vvp

if [ "${VCD:-0}" = "1" ] && [ "${SURFER:-0}" = "1" ]; then
  ../synth/view_waves.sh work/waves.vcd
fi

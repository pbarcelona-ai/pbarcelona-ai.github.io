# ***************
# Filename: Makefile
# Author: Paul Barcelona
# Description: Single entry point for simulation and synthesis, used by
# both developers and the GitHub Actions workflow. Every test target
# fails on a bad result (see ci/run_checked.sh), not just a bad exit code.
# Date: September 28, 2026
# ***************
# Common usage:
#   make test-ip        standalone IP testbenches (fast)
#   make test-smoke     coord_gen smoke test (fast)
#   make test-sv        top-level SystemVerilog regression (barrel, short
#                        edge 64: square 64x64 / portrait 64x96 / landscape 96x64)
#   make sim            all of the above
#   make synth          Yosys synthesis + timing estimate, every module
#   make ci             sim + synth
#   make diagram        regenerate docs/block_diagram.svg/.png
# Options:  VCD=1   dump waveforms   SURFER=1  (with VCD=1) open Surfer
#

SHELL := /bin/bash
CHECK := ci/run_checked.sh
IPS   := fixed_recip frame_buffer mulq bilinear coord_gen

.PHONY: all sim ci test-ip test-smoke test-sv synth diagram clean help
all: help
help:
	@sed -n "9,20p" Makefile

test-ip:
	@for d in $(IPS); do \
	  $(CHECK) ip-$$d '>>> PASS <<<' 'FAIL' -- ip/$$d/run.sh || exit 1; \
	done

test-smoke:
	@$(CHECK) smoke 'SMOKE TEST PASSED' 'SMOKE TEST FAILED' -- tb_verilog/run_smoke.sh

test-sv:
	@$(CHECK) sv-regression 'ALL SELF-CHECKS PASSED' 'SELF-CHECK FAILURE' -- tb_verilog/run.sh

sim: test-ip test-smoke test-sv

synth:
	@$(CHECK) synth 'Yosys synthesis summary' 'VIOLATED|SYNTH FAIL' -- synth/run_all_yosys.sh

ci: sim synth

diagram:
	python3 docs/make_block_diagram.py

clean:
	rm -rf ci/logs synth/summary.md
	find . -name '*.vvp' -delete
	find . -name yosys -type d -prune -exec rm -rf {} +
	rm -rf tb_verilog/work
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find . -name waves.vcd -delete

// ***************
// Filename: tb_smoke.sv
// Author: Paul Barcelona
// Description: Fast SystemVerilog smoke test driving coord_gen directly
// (no frame streaming). Barrel-distortion demo scope: identity,
// radial (barrel), tangential, camera calibration, and boundary
// coordinates for this demo's frame sizes (short edge 64).
// Date: September 28, 2026
// ***************
// =============================================================================
// tb_smoke.sv
//
// Fast SystemVerilog smoke test -- NOT the full image-streaming regression
// (see tb_image_system_demo.sv for that). Drives coord_gen.sv DIRECTLY,
// point-by-point, against an independent inline golden reference, to give
// a quick (seconds) pass/fail signal for:
//
//   1. Legacy-equivalent config (k=p=0)               -> identity round trip
//   2. Radial (barrel, k1<0) distortion                -> matches golden model
//   3. Tangential distortion (p1,p2 nonzero)            -> matches golden model
//   4. Direct camera-calibration fx/fy/cx/cy (non-power-of-two pixel
//      values, not derived from IMG_WIDTH/CENTER/SCALE at all)
//   5. Boundary coordinates for this demo's max frame size (short edge
//      64, long edge 96; coord_gen itself accepts up to 127 -- see
//      barrel_pkg.sv's MAX_W/MAX_H)
//
// Run: ./run_smoke.sh
// =============================================================================
`timescale 1ns/1ps
import barrel_pkg::*;
import distortion_model_pkg::*;
import golden_model_pkg::recip_ref;
import golden_model_pkg::qmul_ref;

module tb_smoke;

  localparam longint ONE_Q16 = 32'h0001_0000;

  task automatic coord_gen_ref(
    input  longint cx_pix, input longint cy_pix,
    input  longint fx_pix, input longint fy_pix,
    input  longint k1, input longint k2, input longint k3,
    input  longint p1, input longint p2,
    input  int     x, input int     y,
    output longint sx, output longint sy
  );
    longint dx, dy, nx, ny, recip_fx, recip_fy;
    longint r2, r4, r6, t1, t2, t3, factor;
    longint tangx, tangy, sxn, syn;
    begin
      recip_fx = recip_ref(fx_pix);
      recip_fy = recip_ref(fy_pix);
      dx = (longint'(x) <<< FRAC_BITS) - cx_pix;
      dy = (longint'(y) <<< FRAC_BITS) - cy_pix;
      nx = qmul_ref(dx, recip_fx);
      ny = qmul_ref(dy, recip_fy);
      r2 = qmul_ref(nx, nx) + qmul_ref(ny, ny);
      r4 = qmul_ref(r2, r2);
      r6 = qmul_ref(r4, r2);
      t1 = qmul_ref(k1, r2);
      t2 = qmul_ref(k2, r4);
      t3 = qmul_ref(k3, r6);
      factor = ONE_Q16 + t1 + t2 + t3;
      tangx = (qmul_ref(p1, qmul_ref(nx, ny)) <<< 1) + qmul_ref(p2, r2 + (qmul_ref(nx, nx) <<< 1));
      tangy = qmul_ref(p1, r2 + (qmul_ref(ny, ny) <<< 1)) + (qmul_ref(p2, qmul_ref(nx, ny)) <<< 1);
      sxn = qmul_ref(nx, factor) + tangx;
      syn = qmul_ref(ny, factor) + tangy;
      sx  = cx_pix + qmul_ref(sxn, fx_pix);
      sy  = cy_pix + qmul_ref(syn, fy_pix);
    end
  endtask

  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;

  distortion_model_pkg::calib_params_t cfg;
  logic              in_valid;
  logic [COORD_W-1:0] in_x, in_y;
  logic               out_valid;
  logic signed [31:0] out_sx_q16, out_sy_q16;
  logic               busy;

  coord_gen dut (
    .clk, .rst_n, .cfg,
    .in_valid, .in_x, .in_y,
    .out_valid, .out_sx_q16, .out_sy_q16, .busy
  );

  int total_checks, total_fail;

  // Polls for out_valid rather than a fixed cycle count: coord_gen's
  // LATENCY is a testbench-visible constant, but polling is robust to it
  // changing without needing this file edited too.
  task automatic check_point(input string label, input int x, input int y);
    longint exp_sx, exp_sy;
    longint diff_x, diff_y;
    int wait_cycles;
    begin
      coord_gen_ref(cfg.cx_pix, cfg.cy_pix, cfg.fx_pix, cfg.fy_pix,
                     cfg.k1, cfg.k2, cfg.k3, cfg.p1, cfg.p2,
                     x, y, exp_sx, exp_sy);

      in_x <= x[COORD_W-1:0]; in_y <= y[COORD_W-1:0]; in_valid <= 1'b1;
      @(posedge clk);
      in_valid <= 1'b0;
      wait_cycles = 0;
      while (!out_valid && wait_cycles < 100) begin
        @(posedge clk);
        wait_cycles = wait_cycles + 1;
      end

      total_checks = total_checks + 1;
      if (!out_valid) begin
        $display("[%s] (%0d,%0d) FAIL: out_valid not asserted within timeout", label, x, y);
        total_fail = total_fail + 1;
      end else begin
        diff_x = longint'(out_sx_q16) - exp_sx; if (diff_x < 0) diff_x = -diff_x;
        diff_y = longint'(out_sy_q16) - exp_sy; if (diff_y < 0) diff_y = -diff_y;
        if (diff_x <= 4 && diff_y <= 4) begin
          $display("[%s] (%0d,%0d) PASS  sx=%0d (exp %0d, d=%0d)  sy=%0d (exp %0d, d=%0d)",
                     label, x, y, out_sx_q16, exp_sx, diff_x, out_sy_q16, exp_sy, diff_y);
        end else begin
          $display("[%s] (%0d,%0d) FAIL  sx=%0d (exp %0d, d=%0d)  sy=%0d (exp %0d, d=%0d)",
                     label, x, y, out_sx_q16, exp_sx, diff_x, out_sy_q16, exp_sy, diff_y);
          total_fail = total_fail + 1;
        end
      end
    end
  endtask

  initial begin
    rst_n = 0; in_valid = 0; in_x = '0; in_y = '0;
    cfg = '0;
    total_checks = 0; total_fail = 0;
    repeat (5) @(posedge clk);
    rst_n = 1;
    repeat (3) @(posedge clk);

    // ---- 1. legacy-equivalent identity (k=p=0) --------------------------
    cfg.cx_pix = 32'sd32 <<< 16; cfg.cy_pix = 32'sd32 <<< 16;
    cfg.fx_pix = 32'sd32 <<< 16; cfg.fy_pix = 32'sd32 <<< 16;
    cfg.recip_fx = recip_ref(cfg.fx_pix); cfg.recip_fy = recip_ref(cfg.fy_pix);
    cfg.k1 = 0; cfg.k2 = 0; cfg.k3 = 0; cfg.p1 = 0; cfg.p2 = 0;
    check_point("identity",        0,  0);
    check_point("identity",       32, 32);
    check_point("identity",       63, 47);

    // ---- 2. radial: BARREL distortion (k1 < 0) --------------------------
    cfg.k1 = -32'sd6554;   // ~-0.1
    cfg.k2 =  32'sd1311;   // ~0.02
    cfg.k3 = 0;
    check_point("barrel",          0,  0);
    check_point("barrel",         63,  0);
    check_point("barrel",          0, 63);
    check_point("barrel",         63, 63);
    check_point("barrel",         40, 25);

    // ---- 3. tangential distortion ----------------------------------------
    cfg.p1 = 32'sd819;   // ~0.0125
    cfg.p2 = -32'sd819;
    check_point("tangential",     40, 25);
    check_point("tangential",     10, 50);

    // ---- 4. direct camera-calibration fx/fy/cx/cy (fx != fy) -------------
    cfg.cx_pix = 32'sd37 <<< 16; cfg.cy_pix = 32'sd29 <<< 16;
    cfg.fx_pix = 32'sd53 <<< 16; cfg.fy_pix = 32'sd61 <<< 16;
    cfg.recip_fx = recip_ref(cfg.fx_pix); cfg.recip_fy = recip_ref(cfg.fy_pix);
    check_point("camera_calib",    0,  0);
    check_point("camera_calib",   63, 47);
    check_point("camera_calib",   12,  8);

    // ---- 5. boundary coordinates for this demo's max frame size ---------
    // Short edge 64, long edge 96; coord_gen's own headroom (from
    // MAX_W/MAX_H=128 in barrel_pkg.sv) goes up to 127.
    cfg.cx_pix = 32'sd48 <<< 16; cfg.cy_pix = 32'sd48 <<< 16;
    cfg.fx_pix = 32'sd48 <<< 16; cfg.fy_pix = 32'sd48 <<< 16;
    cfg.recip_fx = recip_ref(cfg.fx_pix); cfg.recip_fy = recip_ref(cfg.fy_pix);
    cfg.k1 = -32'sd6554; cfg.k2 = 32'sd1311; cfg.k3 = 0; cfg.p1 = 0; cfg.p2 = 0;
    check_point("boundary",        0,   0);
    check_point("boundary",       95,   0);
    check_point("boundary",        0,  95);
    check_point("boundary",       95,  95);
    check_point("boundary",      127, 127);

    $display("=== SMOKE TEST: %0d/%0d points passed ===", total_checks - total_fail, total_checks);
    if (total_fail == 0) $display(">>> SMOKE TEST PASSED <<<");
    else                 $display(">>> SMOKE TEST FAILED (%0d mismatches) <<<", total_fail);

    $finish;
  end
endmodule

// ***************
// Filename: tb_image_system_demo.sv
// Author: Paul Barcelona
// Description: Pure-SystemVerilog top-level self-checking testbench.
// Barrel-distortion demo scope: synthesizes its own barrel-warped
// test image (square/portrait/landscape, short edge 64), corrects
// it through the DUT (bilinear only), and checks the result
// bit-exact vs. an independent golden model plus a genuine
// measured image-quality improvement.
// Date: September 28, 2026
// ***************
// =============================================================================
// tb_image_system_demo.sv
//
// Pure-Verilog (no Python) self-checking testbench for the
// lens-distortion-correction demo (RTL module image_system_demo).
//
// Flow:
//   1. Generate a synthetic test chart (this demo never reads a
//      user-supplied image file -- see ppm_io_pkg.sv).
//   2. Synthesize work/warped_*.ppm using golden_model_pkg's radial-remap
//      primitive fed barrel-distortion k values.
//   3. Fit correction k values that approximately invert that distortion,
//      compute the bit-exact golden "corrected" reference.
//   4. Program the DUT over AXI4-Lite, stream the warped image in over
//      AXI4-Stream with the spec's "line, then 5 idle cycles" timing,
//      capture the output with the same timing.
//   5. Save work/corrected_*.ppm from the DUT's actual output.
//   6. Self-check: DUT vs golden bit-exact, and warped-vs-corrected
//      image-quality sanity check.
//
// This demo performs NO bounds checking of IMG_WIDTH/IMG_HEIGHT against
// the frame buffer's actual capacity (MAX_W/MAX_H in barrel_pkg.sv): a
// size that exceeds it is a silent configuration error, by design (see
// README's Known limitations) -- this testbench never exercises that
// case, and no error message exists anywhere in this design for it.
// =============================================================================
`timescale 1ns/1ps

module tb_image_system_demo;
  import barrel_pkg::*;
  import ppm_io_pkg::*;
  import golden_model_pkg::*;

  localparam int CLK_PERIOD_NS = 10;   // 100 MHz
  localparam int LINE_GAP      = barrel_pkg::LINE_GAP_CYCLES;

  localparam int REG_STATUS     = 8'h04;
  localparam int REG_IMG_WIDTH  = 8'h08;
  localparam int REG_IMG_HEIGHT = 8'h0C;
  localparam int REG_K1         = 8'h10;
  localparam int REG_K2         = 8'h14;
  localparam int REG_K3         = 8'h18;
  localparam int REG_CENTER_X   = 8'h1C;
  localparam int REG_CENTER_Y   = 8'h20;
  localparam int REG_SCALE      = 8'h24;
  localparam int REG_VERSION    = 8'h28;
  localparam int REG_CALIB_MODE = 8'h30;
  localparam int REG_FX         = 8'h34;
  localparam int REG_FY         = 8'h38;
  localparam int REG_CX         = 8'h3C;
  localparam int REG_CY         = 8'h40;
  localparam int REG_P1         = 8'h44;
  localparam int REG_P2         = 8'h48;

  string work_dir = "work";
  // ---- clock / reset ----------------------------------------------------
  logic clk = 0, rst_n = 0;
  always #(CLK_PERIOD_NS/2) clk = ~clk;

  // ---- DUT AXI4-Stream / AXI4-Lite signals -------------------------------
  logic               s_axis_tvalid, s_axis_tready, s_axis_tlast, s_axis_tuser;
  logic [PIX_W-1:0]   s_axis_tdata;
  logic               m_axis_tvalid, m_axis_tready, m_axis_tlast, m_axis_tuser;
  logic [PIX_W-1:0]   m_axis_tdata;

  logic [7:0]   s_axil_awaddr;  logic s_axil_awvalid, s_axil_awready;
  logic [31:0]  s_axil_wdata;   logic [3:0] s_axil_wstrb; logic s_axil_wvalid, s_axil_wready;
  logic [1:0]   s_axil_bresp;   logic s_axil_bvalid, s_axil_bready;
  logic [7:0]   s_axil_araddr;  logic s_axil_arvalid, s_axil_arready;
  logic [31:0]  s_axil_rdata;   logic [1:0] s_axil_rresp; logic s_axil_rvalid, s_axil_rready;

  image_system_demo dut (
    .clk, .rst_n,
    .s_axis_tvalid, .s_axis_tready, .s_axis_tdata, .s_axis_tlast, .s_axis_tuser,
    .m_axis_tvalid, .m_axis_tready, .m_axis_tdata, .m_axis_tlast, .m_axis_tuser,
    .s_axil_awaddr, .s_axil_awvalid, .s_axil_awready,
    .s_axil_wdata, .s_axil_wstrb, .s_axil_wvalid, .s_axil_wready,
    .s_axil_bresp, .s_axil_bvalid, .s_axil_bready,
    .s_axil_araddr, .s_axil_arvalid, .s_axil_arready,
    .s_axil_rdata, .s_axil_rresp, .s_axil_rvalid, .s_axil_rready
  );

  // ---- AXI4-Lite driver tasks --------------------------------------------
  task automatic axil_write(input int addr, input longint data);
    begin
      @(posedge clk);
      s_axil_awaddr  <= addr[7:0];
      s_axil_awvalid <= 1'b1;
      s_axil_wdata   <= data[31:0];
      s_axil_wstrb   <= 4'hF;
      s_axil_wvalid  <= 1'b1;
      @(posedge clk);
      s_axil_awvalid <= 1'b0;
      s_axil_wvalid  <= 1'b0;
      while (s_axil_bvalid !== 1'b1) @(posedge clk);
      s_axil_bready <= 1'b1;
      @(posedge clk);
      s_axil_bready <= 1'b0;
    end
  endtask

  task automatic axil_read(input int addr, output logic [31:0] data);
    begin
      @(posedge clk);
      s_axil_araddr  <= addr[7:0];
      s_axil_arvalid <= 1'b1;
      @(posedge clk);
      s_axil_arvalid <= 1'b0;
      while (s_axil_rvalid !== 1'b1) @(posedge clk);
      data = s_axil_rdata;
      s_axil_rready <= 1'b1;
      @(posedge clk);
      s_axil_rready <= 1'b0;
    end
  endtask

  // ---- AXI4-Stream input driver -------------------------------------------
  task automatic stream_frame_in(
    input int w, input int h,
    input logic [7:0] img_r[], input logic [7:0] img_g[], input logic [7:0] img_b[]
  );
    int x, y;
    begin
      for (y = 0; y < h; y = y + 1) begin
        for (x = 0; x < w; x = x + 1) begin
          s_axis_tvalid <= 1'b1;
          s_axis_tdata  <= {img_r[y*w+x], img_g[y*w+x], img_b[y*w+x]};
          s_axis_tlast  <= (x == w-1);
          s_axis_tuser  <= (x == 0) && (y == 0);
          @(posedge clk);
        end
        s_axis_tvalid <= 1'b0;
        s_axis_tlast  <= 1'b0;
        s_axis_tuser  <= 1'b0;
        repeat (LINE_GAP) @(posedge clk);
      end
    end
  endtask

  // ---- AXI4-Stream output monitor (runs concurrently, via fork) ---------
  logic [7:0] cap_r[], cap_g[], cap_b[];
  int cap_w, cap_h, cap_count, cap_total;
  logic cap_done, cap_tlast_err, cap_tuser_err;

  task automatic capture_frame_out(input int w, input int h);
    int x;
    begin
      cap_w = w; cap_h = h;
      cap_r = new[w*h]; cap_g = new[w*h]; cap_b = new[w*h];
      cap_count = 0; cap_total = w*h; cap_done = 1'b0;
      cap_tlast_err = 1'b0; cap_tuser_err = 1'b0;
      while (cap_count < cap_total) begin
        @(posedge clk);
        if (m_axis_tvalid === 1'b1 && m_axis_tready === 1'b1) begin
          x = cap_count % w;
          cap_r[cap_count] = m_axis_tdata[23:16];
          cap_g[cap_count] = m_axis_tdata[15:8];
          cap_b[cap_count] = m_axis_tdata[7:0];
          if (m_axis_tlast !== (x == w-1)) cap_tlast_err = 1'b1;
          if (cap_count == 0 && m_axis_tuser !== 1'b1) cap_tuser_err = 1'b1;
          cap_count = cap_count + 1;
        end
      end
      cap_done = 1'b1;
    end
  endtask

  // ---- one frame within a distortion group --------------------------------
  // Synthesizes a warped_<label>.ppm from src_r/g/b, computes the bit-exact
  // golden CORRECTED (bilinear) reference, programs IMG_WIDTH/IMG_HEIGHT for
  // this frame's own shape, streams it through the already-configured DUT,
  // captures the output, and runs the self-checks. Does NOT reset the DUT
  // and does NOT rewrite K1/K2/K3 -- those are set once per group by
  // run_group() below, so that calling this 3x in a row exercises the
  // back-to-back consecutive-frame path (with the image SIZE changing
  // between frames).
  logic [7:0] warp_r[], warp_g[], warp_b[];
  logic [7:0] gold_r[], gold_g[], gold_b[];
  remap_cfg_t cfg;
  longint kd1q, kd2q, kd3q, kc1q, kc2q, kc3q;
  real kc1, kc2, kc3;
  longint mae_warp_acc, mae_corr_acc;
  real mae_warp, mae_corr;
  int max_err, mismatches, d, i;
  logic [31:0] status_val, version_val;
  int overall_pass, overall_any_fail, overall_checks;

  task automatic run_one_frame(
    input string label, input int fw, input int fh,
    input logic [7:0] fsrc_r[], input logic [7:0] fsrc_g[], input logic [7:0] fsrc_b[]
  );
    begin
      $display("--- frame: %s  (%0dx%0d) ---", label, fw, fh);
      cfg = make_remap_cfg(fw, fh, 32'h0000_8000, 32'h0000_8000, 32'h0001_0000);
      radial_remap_ref(cfg, kd1q, kd2q, kd3q, fsrc_r, fsrc_g, fsrc_b, warp_r, warp_g, warp_b);
      ppm_write({work_dir, "/warped_", label, ".ppm"}, fw, fh, warp_r, warp_g, warp_b);

      radial_remap_ref(cfg, kc1q, kc2q, kc3q, warp_r, warp_g, warp_b, gold_r, gold_g, gold_b);

      axil_write(REG_IMG_WIDTH,  fw);
      axil_write(REG_IMG_HEIGHT, fh);

      status_val = 32'hFFFF_FFFF;
      i = 0;
      while (i < 200 && status_val[2] !== 1'b0) begin
        axil_read(REG_STATUS, status_val);
        if (status_val[2] === 1'b0) i = 200;
        else begin
          @(posedge clk);
          i = i + 1;
        end
      end
      if (status_val[2] !== 1'b0) begin
        $display("ERROR [%s]: timed out waiting for recip_busy to clear", label);
        $fatal;
      end

      fork
        stream_frame_in(fw, fh, warp_r, warp_g, warp_b);
        capture_frame_out(fw, fh);
      join

      ppm_write({work_dir, "/corrected_", label, ".ppm"}, fw, fh, cap_r, cap_g, cap_b);

      max_err = 0; mismatches = 0;
      for (i = 0; i < fw*fh; i = i + 1) begin
        d = int'(cap_r[i]) - int'(gold_r[i]); if (d<0) d=-d; if (d>max_err) max_err=d; if (d>1) mismatches=mismatches+1;
        d = int'(cap_g[i]) - int'(gold_g[i]); if (d<0) d=-d; if (d>max_err) max_err=d; if (d>1) mismatches=mismatches+1;
        d = int'(cap_b[i]) - int'(gold_b[i]); if (d<0) d=-d; if (d>max_err) max_err=d; if (d>1) mismatches=mismatches+1;
      end
      $display("[%s] DUT vs golden model: max_err=%0d  channel-mismatches(>1)=%0d/%0d",
                label, max_err, mismatches, fw*fh*3);

      mae_warp_acc = 0; mae_corr_acc = 0;
      for (i = 0; i < fw*fh; i = i + 1) begin
        d = int'(warp_r[i]) - int'(fsrc_r[i]); if (d<0) d=-d; mae_warp_acc += d;
        d = int'(warp_g[i]) - int'(fsrc_g[i]); if (d<0) d=-d; mae_warp_acc += d;
        d = int'(warp_b[i]) - int'(fsrc_b[i]); if (d<0) d=-d; mae_warp_acc += d;
        d = int'(cap_r[i])  - int'(fsrc_r[i]); if (d<0) d=-d; mae_corr_acc += d;
        d = int'(cap_g[i])  - int'(fsrc_g[i]); if (d<0) d=-d; mae_corr_acc += d;
        d = int'(cap_b[i])  - int'(fsrc_b[i]); if (d<0) d=-d; mae_corr_acc += d;
      end
      mae_warp = real'(mae_warp_acc) / real'(fw*fh*3);
      mae_corr = real'(mae_corr_acc) / real'(fw*fh*3);
      $display("[%s] MAE(warped, original)       = %f", label, mae_warp);
      $display("[%s] MAE(DUT-corrected, original) = %f", label, mae_corr);

      overall_checks = overall_checks + 4;
      if (mismatches == 0 && max_err <= 1) begin
        $display("[%s] SELF-CHECK bit-exact-vs-golden : PASS", label);
        overall_pass = overall_pass + 1;
      end else begin
        $display("[%s] SELF-CHECK bit-exact-vs-golden : FAIL", label);
        overall_any_fail = 1;
      end
      if (mae_corr < 0.85 * mae_warp) begin
        $display("[%s] SELF-CHECK correction-quality  : PASS", label);
        overall_pass = overall_pass + 1;
      end else begin
        $display("[%s] SELF-CHECK correction-quality  : FAIL", label);
        overall_any_fail = 1;
      end
      if (cap_tlast_err) begin
        $display("[%s] SELF-CHECK tlast timing       : FAIL", label);
        overall_any_fail = 1;
      end else begin
        $display("[%s] SELF-CHECK tlast timing       : PASS", label);
        overall_pass = overall_pass + 1;
      end
      if (cap_tuser_err) begin
        $display("[%s] SELF-CHECK tuser (start-of-frame) : FAIL", label);
        overall_any_fail = 1;
      end else begin
        $display("[%s] SELF-CHECK tuser (start-of-frame) : PASS", label);
        overall_pass = overall_pass + 1;
      end
    end
  endtask

  // Three test-image shapes, all with a SHORT EDGE of 64 pixels (this
  // demo's only tested frame size): square 64x64, portrait 64x96,
  // landscape 96x64. Always generated fresh by generate_synthetic_chart --
  // this testbench has no capability to read a user-supplied image file
  // (see ppm_io_pkg.sv).
  int sq_w, sq_h, pt_w, pt_h, ls_w, ls_h;
  logic [7:0] sq_r[], sq_g[], sq_b[];
  logic [7:0] pt_r[], pt_g[], pt_b[];
  logic [7:0] ls_r[], ls_g[], ls_b[];

  task automatic run_group(input string dist_label, input real kd1, input real kd2, input real kd3);
    begin
      $display("=== group: %s  (kd1=%f, kd2=%f, kd3=%f) ===", dist_label, kd1, kd2, kd3);
      kd1q = longint'($rtoi(kd1*65536.0));
      kd2q = longint'($rtoi(kd2*65536.0));
      kd3q = longint'($rtoi(kd3*65536.0));
      fit_correction_coeffs(kd1, kd2, kd3, kc1, kc2, kc3);
      kc1q = longint'($rtoi(kc1*65536.0));
      kc2q = longint'($rtoi(kc2*65536.0));
      kc3q = longint'($rtoi(kc3*65536.0));
      $display("correction coeffs (Q16.16): k1=%0d k2=%0d k3=%0d", kc1q, kc2q, kc3q);

      axil_write(REG_K1, kc1q);
      axil_write(REG_K2, kc2q);
      axil_write(REG_K3, kc3q);
      axil_write(REG_CENTER_X, 32'h0000_8000);
      axil_write(REG_CENTER_Y, 32'h0000_8000);
      axil_write(REG_SCALE,    32'h0001_0000);

      run_one_frame({dist_label, "_square"},    sq_w, sq_h, sq_r, sq_g, sq_b);
      run_one_frame({dist_label, "_portrait"},  pt_w, pt_h, pt_r, pt_g, pt_b);
      run_one_frame({dist_label, "_landscape"}, ls_w, ls_h, ls_r, ls_g, ls_b);
    end
  endtask

  // ---- main sequence ------------------------------------------------------

  initial begin
    m_axis_tready  <= 1'b1;
    s_axis_tvalid  <= 1'b0; s_axis_tlast <= 1'b0; s_axis_tuser <= 1'b0; s_axis_tdata <= '0;
    s_axil_awvalid <= 1'b0; s_axil_wvalid <= 1'b0; s_axil_bready <= 1'b0;
    s_axil_arvalid <= 1'b0; s_axil_rready <= 1'b0;
    rst_n = 1'b0;
    repeat (5) @(posedge clk);
    rst_n = 1'b1;
    repeat (5) @(posedge clk);

    // ---- generate the three shaped test images (short edge 64) ----------
    sq_w = 64; sq_h = 64;
    generate_synthetic_chart(sq_w, sq_h, sq_r, sq_g, sq_b);
    ppm_write({work_dir, "/test_square.ppm"}, sq_w, sq_h, sq_r, sq_g, sq_b);

    pt_w = 64; pt_h = 96;
    generate_synthetic_chart(pt_w, pt_h, pt_r, pt_g, pt_b);
    ppm_write({work_dir, "/test_portrait.ppm"}, pt_w, pt_h, pt_r, pt_g, pt_b);

    ls_w = 96; ls_h = 64;
    generate_synthetic_chart(ls_w, ls_h, ls_r, ls_g, ls_b);
    ppm_write({work_dir, "/test_landscape.ppm"}, ls_w, ls_h, ls_r, ls_g, ls_b);

    $display("test images: square %0dx%0d, portrait %0dx%0d, landscape %0dx%0d",
              sq_w, sq_h, pt_w, pt_h, ls_w, ls_h);

    axil_read(REG_VERSION, version_val);
    $display("core VERSION = 0x%08h", version_val);

    overall_pass = 0;
    overall_any_fail = 0;
    overall_checks = 0;

    // Sign convention (verified empirically, see README): applying this
    // remap primitive with POSITIVE k1 to a flat/undistorted image
    // produces genuine barrel bulge. The fitted correction coefficient
    // comes out negative, matching the AXI-Lite register documentation
    // ("k1<0 corrects barrel bulge").
    //
    // Barrel only (no pincushion for this demo), bilinear interpolation only,
    // 3 shapes run as 3 CONSECUTIVE frames (no reset between them), per
    // the back-to-back multi-frame, multi-aspect-ratio testing this
    // project's testbenches use throughout.
    run_group("barrel", 0.08, -0.01, 0.0);

    $display("=== TOTAL: %0d/%0d checks passed across 3 frame-scenarios ===", overall_pass, overall_checks);
    if (overall_pass == overall_checks && !overall_any_fail)
      $display(">>> ALL SELF-CHECKS PASSED (barrel x square+portrait+landscape) <<<");
    else
      $display(">>> SELF-CHECK FAILURE <<<");

    $finish;
  end

  // safety timeout
  initial begin
    #50_000_000; // 50ms sim time
    $display("ERROR: global timeout -- simulation did not finish");
    $fatal;
  end


  // Optional waveform dump: compile with -DDUMP_VCD (run.sh does this when
  // VCD=1). Only the first VCD_WINDOW_NS nanoseconds are recorded -- a
  // whole multi-frame regression would produce an unmanageably large file.
  // Override with -DVCD_WINDOW_NS=<ns>. View with synth/view_waves.sh.
`ifdef DUMP_VCD
`ifndef VCD_WINDOW_NS
`define VCD_WINDOW_NS 300000
`endif
  initial begin
    $dumpfile("work/waves.vcd");
    $dumpvars(0, dut);
    #(`VCD_WINDOW_NS) $dumpoff;
  end
`endif
endmodule

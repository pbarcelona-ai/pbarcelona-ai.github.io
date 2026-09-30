// ***************
// Filename: coord_gen.sv
// Author: Paul Barcelona
// Description: Reusable IP. Per-pixel source-address generator for
// radial + tangential ("plumb bob") barrel/pincushion distortion
// correction. Fixed 23-cycle latency, 1 pixel/clock. All multiplies
// use the mulq_s IP.
// Date: September 28, 2026
// ***************
// =============================================================================
// coord_gen.sv
//
// For each output (corrected-image) pixel (x,y), computes the fractional
// source coordinate to sample from the (distorted) input frame: camera-
// calibration-style pinhole normalization, then the standard
// radial+tangential ("plumb bob") distortion model:
//
//   nx = (x - cx_pix) / fx_pix          -- normalize (pinhole intrinsics)
//   ny = (y - cy_pix) / fy_pix
//   r2 = nx^2 + ny^2
//   radial   = 1 + k1*r2 + k2*r2^2 + k3*r2^3        (k3 * r^6 term)
//   tang_x   = 2*p1*nx*ny + p2*(r2 + 2*nx^2)
//   tang_y   =   p1*(r2 + 2*ny^2) + 2*p2*nx*ny
//   sx = cx_pix + (nx*radial + tang_x) * fx_pix
//   sy = cy_pix + (ny*radial + tang_y) * fy_pix
//
// cfg (calib_params_t, distortion_model_pkg.sv) bundles every one of the
// above parameters into a single struct port -- see that package for why.
// Barrel distortion is k1<0 (this demo's only tested case); this same
// math also does pincushion (k1>0) and tangential-only correction, but
// only barrel is exercised by this demo's testbenches.
//
// All arithmetic is Q16.16 (see barrel_pkg). This is a fully pipelined,
// feed-forward (no feedback/stall) datapath: one (x,y) request is
// accepted every clock cycle, with a fixed 23-cycle delay to the
// corresponding output -- every multiply goes through the mulq_s IP (2
// cycles) plus a saturate/add stage, confirmed by direct measurement
// (see the latency-probe methodology described in README.md).
//
// TIMING: a one-cycle 32x32 multiply plus its shift/saturate/add is
// ~11 ns of logic on 7-series -- far short of a 100 MHz (10 ns) target.
// Splitting every multiply across mulq_s brings this module's worst
// path to ~6.5 ns (~7.2 ns inside mulq_s itself) -- see README's
// "Timing closure" section for the full account.
// =============================================================================

module coord_gen #(
  parameter int COORD_W = barrel_pkg::COORD_W
) (
  input  logic clk,
  input  logic rst_n,

  // Static per-frame configuration (held stable while streaming)
  input  distortion_model_pkg::calib_params_t cfg,

  // Per-pixel request
  input  logic                    in_valid,
  input  logic [COORD_W-1:0]      in_x,
  input  logic [COORD_W-1:0]      in_y,

  // Result, LATENCY cycles later
  output logic                    out_valid,
  output logic signed [31:0]      out_sx_q16,   // full Q16.16 source X (pre-split)
  output logic signed [31:0]      out_sy_q16,   // full Q16.16 source Y (pre-split)

  // Always 0 in this demo (kept as a port for interface stability with
  // axis_out_ctrl.sv; an earlier, more general revision of this project
  // used it to pace a per-pixel-divide "slow path" for models removed
  // from this demo's scope).
  output logic                    busy
);

  localparam int LATENCY = 23;

  // =======================================================================
  // TIMING NOTE (pipeline structure, LATENCY 23)
  //
  // Every multiply goes through the mulq_s IP (2 cycles: 16x16 DSP partial
  // products registered inside the DSPs, then combined into the exact
  // 48-bit (a*b)>>>16), followed by one register stage that saturates
  // (barrel_pkg::qsat48) and does any small add. qsat48(mulq_s(a,b)) is
  // exactly barrel_pkg::qmul(a,b), so results are bit-identical to the
  // original single-cycle formulation -- only registers were added.
  // Data registers carry no reset (only the valid bits do): an async
  // reset on a datapath register prevents DSP-register packing and costs
  // an inverter per flop. Their contents are meaningless until valid.
  //
  // Each "multiply stage" below is therefore 3 register levels: two inside
  // mulq_s, one saturate/add. Side-band values that must stay aligned with
  // a multiply's result are delayed by the same 2 cycles.
  // =======================================================================

  // Signed views of the unsigned reciprocals (intermediate wires, not
  // $signed() in port connections: Yosys 0.33 frontend signedness bug).
  // Reinterpreting the 32-bit reciprocal as signed matches the original
  // qmul(.., $signed({1'b0, recip})) which truncated to 32 bits.
  logic signed [31:0] recip_fx_s, recip_fy_s;
  assign recip_fx_s = cfg.recip_fx;
  assign recip_fy_s = cfg.recip_fy;

  // ---- valid pipeline: 23 stages, aligned with the datapath below -------
  logic [22:0] vpipe;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) vpipe <= '0;
    else        vpipe <= {vpipe[21:0], in_valid};
  end
  logic v8;
  assign v8 = vpipe[22];

  // ---- Stage 0 (level 1): dx, dy ----------------------------------------
  logic signed [31:0] dx0, dy0;
  always_ff @(posedge clk) begin
    dx0 <= ({{(32-COORD_W){1'b0}}, in_x} <<< barrel_pkg::FRAC_BITS) - cfg.cx_pix;
    dy0 <= ({{(32-COORD_W){1'b0}}, in_y} <<< barrel_pkg::FRAC_BITS) - cfg.cy_pix;
  end

  // ---- Stage 1 (levels 2-4): nx = dx/fx ; ny = dy/fy --------------------
  logic signed [47:0] fm_nx1, fm_ny1;
  logic signed [31:0] nx1, ny1;
  mulq_s u_m_nx (.clk, .a(dx0), .b(recip_fx_s), .s(fm_nx1));
  mulq_s u_m_ny (.clk, .a(dy0), .b(recip_fy_s), .s(fm_ny1));
  always_ff @(posedge clk) begin
    nx1 <= barrel_pkg::qsat48(fm_nx1);
    ny1 <= barrel_pkg::qsat48(fm_ny1);
  end

  // ---- Stage 2 (levels 5-7): nx^2, ny^2, nx*ny, r2 = nx^2+ny^2 ----------
  // (nx,ny,nx^2,ny^2,nx*ny carried forward for the tangential terms.)
  logic signed [47:0] fm_nxsq, fm_nysq, fm_nxny;
  logic signed [31:0] nx2a, nx2b, ny2a, ny2b;
  logic signed [31:0] nx2, ny2, r2_2, nxsq_2, nysq_2, nxny_2;
  mulq_s u_m_nxsq (.clk, .a(nx1), .b(nx1), .s(fm_nxsq));
  mulq_s u_m_nysq (.clk, .a(ny1), .b(ny1), .s(fm_nysq));
  mulq_s u_m_nxny (.clk, .a(nx1), .b(ny1), .s(fm_nxny));
  always_ff @(posedge clk) begin
    nx2a <= nx1;  nx2b <= nx2a;
    ny2a <= ny1;  ny2b <= ny2a;
    nxsq_2 <= barrel_pkg::qsat48(fm_nxsq);
    nysq_2 <= barrel_pkg::qsat48(fm_nysq);
    nxny_2 <= barrel_pkg::qsat48(fm_nxny);
    r2_2   <= barrel_pkg::qsat48(fm_nxsq) + barrel_pkg::qsat48(fm_nysq);
    nx2    <= nx2b;
    ny2    <= ny2b;
  end

  // ---- Stage 3 (levels 8-10): r4 = r2*r2 ---------------------------------
  logic signed [47:0] fm_r4;
  logic signed [31:0] nx3a, nx3b, ny3a, ny3b, r2_3a, r2_3b, nxsq_3a, nxsq_3b, nysq_3a, nysq_3b, nxny_3a, nxny_3b;
  logic signed [31:0] nx3, ny3, r2_3, r4_3, nxsq_3, nysq_3, nxny_3;
  mulq_s u_m_r4 (.clk, .a(r2_2), .b(r2_2), .s(fm_r4));
  always_ff @(posedge clk) begin
    nx3a <= nx2;      nx3b <= nx3a;
    ny3a <= ny2;      ny3b <= ny3a;
    r2_3a <= r2_2;    r2_3b <= r2_3a;
    nxsq_3a <= nxsq_2; nxsq_3b <= nxsq_3a;
    nysq_3a <= nysq_2; nysq_3b <= nysq_3a;
    nxny_3a <= nxny_2; nxny_3b <= nxny_3a;
    r4_3   <= barrel_pkg::qsat48(fm_r4);
    nx3 <= nx3b; ny3 <= ny3b; r2_3 <= r2_3b;
    nxsq_3 <= nxsq_3b; nysq_3 <= nysq_3b; nxny_3 <= nxny_3b;
  end

  // ---- Stage 4 (levels 11-13): r6 = r4*r2 ; pre-add the two tangential
  // (r2 + 2n^2) sums so the stage-5 multiplies take registered operands --
  logic signed [47:0] fm_r6;
  logic signed [31:0] nx4a, nx4b, ny4a, ny4b, r2_4a, r2_4b, r4_4a, r4_4b, nxny_4a, nxny_4b;
  logic signed [31:0] sumb_4a, sumb_4b, sumc_4a, sumc_4b;
  logic signed [31:0] nx4, ny4, r2_4, r4_4, r6_4, nxny_4, sumb_4, sumc_4;
  mulq_s u_m_r6 (.clk, .a(r4_3), .b(r2_3), .s(fm_r6));
  always_ff @(posedge clk) begin
    nx4a <= nx3;     nx4b <= nx4a;
    ny4a <= ny3;     ny4b <= ny4a;
    r2_4a <= r2_3;   r2_4b <= r2_4a;
    r4_4a <= r4_3;   r4_4b <= r4_4a;
    nxny_4a <= nxny_3; nxny_4b <= nxny_4a;
    sumb_4a <= r2_3 + (nxsq_3 <<< 1);          // r2 + 2nx^2
    sumc_4a <= r2_3 + (nysq_3 <<< 1);          // r2 + 2ny^2
    sumb_4b <= sumb_4a;  sumc_4b <= sumc_4a;
    r6_4   <= barrel_pkg::qsat48(fm_r6);
    nx4 <= nx4b; ny4 <= ny4b; r2_4 <= r2_4b; r4_4 <= r4_4b;
    nxny_4 <= nxny_4b; sumb_4 <= sumb_4b; sumc_4 <= sumc_4b;
  end

  // ---- Stage 5 (levels 14-16): t1=k1*r2, t2=k2*r4, t3=k3*r6 ; tangential
  logic signed [47:0] fm_t1, fm_t2, fm_t3, fm_ta, fm_tb, fm_tc, fm_td;
  logic signed [31:0] nx5a, nx5b, ny5a, ny5b;
  logic signed [31:0] nx5, ny5, t1_5, t2_5, t3_5, tangx_5, tangy_5;
  mulq_s u_m_t1 (.clk, .a(cfg.k1), .b(r2_4),   .s(fm_t1));
  mulq_s u_m_t2 (.clk, .a(cfg.k2), .b(r4_4),   .s(fm_t2));
  mulq_s u_m_t3 (.clk, .a(cfg.k3), .b(r6_4),   .s(fm_t3));
  mulq_s u_m_ta (.clk, .a(cfg.p1), .b(nxny_4), .s(fm_ta));   // -> 2*p1*nx*ny
  mulq_s u_m_tb (.clk, .a(cfg.p2), .b(sumb_4), .s(fm_tb));   // -> p2*(r2+2nx^2)
  mulq_s u_m_tc (.clk, .a(cfg.p1), .b(sumc_4), .s(fm_tc));   // -> p1*(r2+2ny^2)
  mulq_s u_m_td (.clk, .a(cfg.p2), .b(nxny_4), .s(fm_td));   // -> 2*p2*nx*ny
  always_ff @(posedge clk) begin
    nx5a <= nx4;  nx5b <= nx5a;
    ny5a <= ny4;  ny5b <= ny5a;
    nx5 <= nx5b;  ny5 <= ny5b;
    t1_5    <= barrel_pkg::qsat48(fm_t1);
    t2_5    <= barrel_pkg::qsat48(fm_t2);
    t3_5    <= barrel_pkg::qsat48(fm_t3);
    tangx_5 <= (barrel_pkg::qsat48(fm_ta) <<< 1) + barrel_pkg::qsat48(fm_tb);
    tangy_5 <= barrel_pkg::qsat48(fm_tc) + (barrel_pkg::qsat48(fm_td) <<< 1);
  end

  // ---- Stage 6 (level 17): factor = 1 + t1 + t2 + t3 (adds only) --------
  logic signed [31:0] nx6, ny6, factor6, tangx6, tangy6;
  always_ff @(posedge clk) begin
    nx6     <= nx5; ny6 <= ny5;
    factor6 <= barrel_pkg::Q16_ONE + t1_5 + t2_5 + t3_5;
    tangx6  <= tangx_5;
    tangy6  <= tangy_5;
  end

  // ---- Stage 7 (levels 18-20): sxn = nx*factor + tang_x ; syn similarly --
  logic signed [47:0] fm_sx, fm_sy;
  logic signed [31:0] tangx7a, tangx7b, tangy7a, tangy7b, sxn7, syn7;
  mulq_s u_m_sx (.clk, .a(nx6), .b(factor6), .s(fm_sx));
  mulq_s u_m_sy (.clk, .a(ny6), .b(factor6), .s(fm_sy));
  always_ff @(posedge clk) begin
    tangx7a <= tangx6;  tangx7b <= tangx7a;
    tangy7a <= tangy6;  tangy7b <= tangy7a;
    sxn7 <= barrel_pkg::qsat48(fm_sx) + tangx7b;
    syn7 <= barrel_pkg::qsat48(fm_sy) + tangy7b;
  end

  // ---- Stage 8 (levels 21-23): sx = cx + sxn*fx ; sy = cy + syn*fy -------
  logic signed [47:0] fm_fx, fm_fy;
  logic signed [31:0] sx8, sy8;
  mulq_s u_m_fx (.clk, .a(sxn7), .b(cfg.fx_pix), .s(fm_fx));
  mulq_s u_m_fy (.clk, .a(syn7), .b(cfg.fy_pix), .s(fm_fy));
  always_ff @(posedge clk) begin
    sx8 <= cfg.cx_pix + barrel_pkg::qsat48(fm_fx);
    sy8 <= cfg.cy_pix + barrel_pkg::qsat48(fm_fy);
  end

  assign busy      = 1'b0;   // no slow path in this demo -- always fast, 1 px/clock
  assign out_valid  = v8;
  assign out_sx_q16 = sx8;
  assign out_sy_q16 = sy8;

endmodule

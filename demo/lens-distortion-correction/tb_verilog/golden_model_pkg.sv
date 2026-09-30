// ***************
// Filename: golden_model_pkg.sv
// Author: Paul Barcelona
// Description: Independent, from-scratch SystemVerilog golden-model
// package: fixed-point radial-distortion bilinear remap, a
// least-squares correction-coefficient fitter, and synthetic
// chart generation. Demo scope: barrel/pincushion radial
// distortion, bilinear interpolation only.
// Date: September 28, 2026
// ***************
// =============================================================================
// golden_model_pkg.sv
//
// An INDEPENDENT (separately written, not shared/imported from the RTL)
// reimplementation of the same Q16.16 fixed-point radial-remap primitive
// the RTL (barrel_pkg::qmul + coord_gen + axis_out_ctrl's clamp logic +
// bilinear.sv) implements, used both to synthesize warped.ppm from the
// original image and as the golden bit-exact reference that the DUT's
// streamed output is checked against.
//
// This is deliberately a second, from-scratch implementation (not a
// wrapper around the RTL modules) -- reusing the DUT's own qmul/recip
// would make the "self-check" circular and unable to catch bugs in
// those primitives.
// =============================================================================
package golden_model_pkg;

  localparam int FRAC_BITS = 16;
  localparam longint ONE_Q16 = 32'h0001_0000;

  // 32x32->64 signed multiply, arithmetic shift right 16, saturate to 32 bits.
  function automatic longint qmul_ref(input longint a, input longint b);
    longint prod;
    begin
      prod = (a * b) >>> FRAC_BITS;
      if (prod > 64'sh0000_0000_7FFF_FFFF) prod = 64'sh0000_0000_7FFF_FFFF;
      if (prod < -64'sh0000_0000_8000_0000) prod = -64'sh0000_0000_8000_0000;
      qmul_ref = prod;
    end
  endfunction

  // Unsigned reciprocal: floor(2^32 / operand), operand a positive Q16.16
  // value. A plain integer divide is fine here -- this is testbench code,
  // not required to be synthesizable, and it is written independently of
  // fixed_recip.sv's iterative shift/subtract implementation.
  function automatic longint recip_ref(input longint operand);
    longint op, q;
    begin
      op = (operand <= 0) ? 1 : operand;
      q = (64'sh1_0000_0000) / op;
      if (q > 64'shFFFF_FFFF) q = 64'shFFFF_FFFF;
      recip_ref = q;
    end
  endfunction

  function automatic int bits_ref(input longint v, input int hi, input int lo);
    longint uv;
    begin
      uv = v & 64'hFFFF_FFFF;
      bits_ref = (uv >> lo) & ((1 << (hi - lo + 1)) - 1);
    end
  endfunction

  typedef struct packed {
    int    w, h;
    longint cx_pix, cy_pix;
    longint halfw_scaled, halfh_scaled;
    longint recip_halfw, recip_halfh;
  } remap_cfg_t;

  function automatic remap_cfg_t make_remap_cfg(
    input int w, input int h,
    input longint center_x_q16, input longint center_y_q16, input longint scale_q16
  );
    remap_cfg_t cfg;
    longint imgw_q16, imgh_q16;
    begin
      cfg.w = w; cfg.h = h;
      imgw_q16 = longint'(w) <<< FRAC_BITS;
      imgh_q16 = longint'(h) <<< FRAC_BITS;
      cfg.cx_pix       = qmul_ref(center_x_q16, imgw_q16);
      cfg.cy_pix       = qmul_ref(center_y_q16, imgh_q16);
      cfg.halfw_scaled = qmul_ref(qmul_ref(imgw_q16, 32'h0000_8000), scale_q16);
      cfg.halfh_scaled = qmul_ref(qmul_ref(imgh_q16, 32'h0000_8000), scale_q16);
      cfg.recip_halfw  = recip_ref(cfg.halfw_scaled);
      cfg.recip_halfh  = recip_ref(cfg.halfh_scaled);
      make_remap_cfg = cfg;
    end
  endfunction

  // Applies the radial remap to src (w*h, r/g/b dynamic arrays), bit-exact
  // reproduction of coord_gen + axis_out_ctrl's addressing/clamp logic +
  // bilinear.sv, writing into freshly-allocated out_r/g/b (same w*h).
  task automatic radial_remap_ref(
    input  remap_cfg_t cfg,
    input  longint      k1_q16, input longint k2_q16, input longint k3_q16,
    input  logic [7:0] src_r[], input logic [7:0] src_g[], input logic [7:0] src_b[],
    output logic [7:0] out_r[], output logic [7:0] out_g[], output logic [7:0] out_b[]
  );
    int x, y, x0, y0, fx, fy;
    longint dx, dy, nx, ny, r2, r4, r6, t1, t2, t3, factor, sxn, syn, sx, sy, x0s, y0s;
    int idx_tl, idx_tr, idx_bl, idx_br;
    longint w00, w10, w01, w11, acc;
    begin
      out_r = new[cfg.w * cfg.h];
      out_g = new[cfg.w * cfg.h];
      out_b = new[cfg.w * cfg.h];

      for (y = 0; y < cfg.h; y = y + 1) begin
        dy = (longint'(y) <<< FRAC_BITS) - cfg.cy_pix;
        ny = qmul_ref(dy, cfg.recip_halfh);
        for (x = 0; x < cfg.w; x = x + 1) begin
          dx = (longint'(x) <<< FRAC_BITS) - cfg.cx_pix;
          nx = qmul_ref(dx, cfg.recip_halfw);

          r2 = qmul_ref(nx, nx) + qmul_ref(ny, ny);
          r4 = qmul_ref(r2, r2);
          r6 = qmul_ref(r4, r2);
          t1 = qmul_ref(k1_q16, r2);
          t2 = qmul_ref(k2_q16, r4);
          t3 = qmul_ref(k3_q16, r6);
          factor = ONE_Q16 + t1 + t2 + t3;

          sxn = qmul_ref(nx, factor);
          syn = qmul_ref(ny, factor);
          sx  = cfg.cx_pix + qmul_ref(sxn, cfg.halfw_scaled);
          sy  = cfg.cy_pix + qmul_ref(syn, cfg.halfh_scaled);

          if (sx < 0) begin
            x0 = 0; fx = 0;
          end else begin
            x0s = sx >>> FRAC_BITS;
            if (x0s > (cfg.w - 2)) begin x0 = cfg.w - 2; fx = 255; end
            else begin x0 = int'(x0s); fx = bits_ref(sx, 15, 8); end
          end
          if (sy < 0) begin
            y0 = 0; fy = 0;
          end else begin
            y0s = sy >>> FRAC_BITS;
            if (y0s > (cfg.h - 2)) begin y0 = cfg.h - 2; fy = 255; end
            else begin y0 = int'(y0s); fy = bits_ref(sy, 15, 8); end
          end

          idx_tl = y0 * cfg.w + x0;
          idx_tr = idx_tl + 1;
          idx_bl = idx_tl + cfg.w;
          idx_br = idx_bl + 1;

          w00 = (256 - fx) * (256 - fy);
          w10 = fx * (256 - fy);
          w01 = (256 - fx) * fy;
          w11 = fx * fy;

          acc = longint'(src_r[idx_tl]) * w00 + longint'(src_r[idx_tr]) * w10
              + longint'(src_r[idx_bl]) * w01 + longint'(src_r[idx_br]) * w11 + 32768;
          out_r[y * cfg.w + x] = 8'(acc >>> 16);

          acc = longint'(src_g[idx_tl]) * w00 + longint'(src_g[idx_tr]) * w10
              + longint'(src_g[idx_bl]) * w01 + longint'(src_g[idx_br]) * w11 + 32768;
          out_g[y * cfg.w + x] = 8'(acc >>> 16);

          acc = longint'(src_b[idx_tl]) * w00 + longint'(src_b[idx_tr]) * w10
              + longint'(src_b[idx_bl]) * w01 + longint'(src_b[idx_br]) * w11 + 32768;
          out_b[y * cfg.w + x] = 8'(acc >>> 16);
        end
      end
    end
  endtask

  task automatic fit_correction_coeffs(
    input  real kd1, input real kd2, input real kd3,
    output real kc1, output real kc2, output real kc3
  );
    int n, i;
    real r_max, ru, rd, target;
    real f2, f4, f6;
    // normal-equation accumulators for A^T A (3x3, symmetric) and A^T b (3x1)
    real s22, s24, s26, s44, s46, s66, b2, b4, b6;
    real det, i22,i24,i26,i44,i46,i66; // not used directly; solved via Cramer's rule below
    real m[3][3], rhs[3];
    real d0, d1, d2, d3;
    begin
      n = 400; r_max = 1.6;
      s22=0; s24=0; s26=0; s44=0; s46=0; s66=0; b2=0; b4=0; b6=0;
      for (i = 1; i <= n; i = i + 1) begin
        ru = r_max * real'(i) / real'(n);
        rd = ru * (1.0 + kd1*ru*ru + kd2*ru*ru*ru*ru + kd3*ru*ru*ru*ru*ru*ru);
        if (rd > 1.0e-6) begin
          target = ru/rd - 1.0;
          f2 = rd*rd; f4 = f2*f2; f6 = f4*f2;
          s22 += f2*f2; s24 += f2*f4; s26 += f2*f6;
          s44 += f4*f4; s46 += f4*f6; s66 += f6*f6;
          b2  += f2*target; b4 += f4*target; b6 += f6*target;
        end
      end
      // symmetric 3x3 system:
      // [s22 s24 s26][kc1]   [b2]
      // [s24 s44 s46][kc2] = [b4]
      // [s26 s46 s66][kc3]   [b6]
      m[0][0]=s22; m[0][1]=s24; m[0][2]=s26; rhs[0]=b2;
      m[1][0]=s24; m[1][1]=s44; m[1][2]=s46; rhs[1]=b4;
      m[2][0]=s26; m[2][1]=s46; m[2][2]=s66; rhs[2]=b6;

      det = m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])
          - m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])
          + m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]);

      d1 = rhs[0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])
         - m[0][1]*(rhs[1]*m[2][2]-m[1][2]*rhs[2])
         + m[0][2]*(rhs[1]*m[2][1]-m[1][1]*rhs[2]);

      d2 = m[0][0]*(rhs[1]*m[2][2]-m[1][2]*rhs[2])
         - rhs[0]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])
         + m[0][2]*(m[1][0]*rhs[2]-rhs[1]*m[2][0]);

      d3 = m[0][0]*(m[1][1]*rhs[2]-rhs[1]*m[2][1])
         - m[0][1]*(m[1][0]*rhs[2]-rhs[1]*m[2][0])
         + rhs[0]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]);

      kc1 = d1/det; kc2 = d2/det; kc3 = d3/det;
    end
  endtask

  task automatic generate_synthetic_chart(
    input  int w, input int h,
    output logic [7:0] img_r[], output logic [7:0] img_g[], output logic [7:0] img_b[]
  );
    int x, y, cx, cy, ring, step, dxp, dyp;
    real r;
    begin
      img_r = new[w*h]; img_g = new[w*h]; img_b = new[w*h];
      step = (w/16 > 6) ? w/16 : 6;
      cx = w/2; cy = h/2;
      for (y = 0; y < h; y = y+1) begin
        for (x = 0; x < w; x = x+1) begin
          img_r[y*w+x] = 250; img_g[y*w+x] = 250; img_b[y*w+x] = 250;
        end
      end
      for (x = 0; x < w; x = x + step)
        for (y = 0; y < h; y = y+1) begin img_r[y*w+x]=40; img_g[y*w+x]=40; img_b[y*w+x]=40; end
      for (y = 0; y < h; y = y + step)
        for (x = 0; x < w; x = x+1) begin img_r[y*w+x]=40; img_g[y*w+x]=40; img_b[y*w+x]=40; end
      for (ring = step; ring < (w<h?w:h)*0.6; ring = ring + step) begin
        for (y = 0; y < h; y = y+1) begin
          for (x = 0; x < w; x = x+1) begin
            dxp = x-cx; dyp = y-cy;
            r = $sqrt(real'(dxp*dxp+dyp*dyp));
            if (r > real'(ring)-1.0 && r < real'(ring)+1.0) begin
              img_r[y*w+x] = (60 + (ring/step)*40) % 256;
              img_g[y*w+x] = (180 - (ring/step)*20 + 256) % 256;
              img_b[y*w+x] = (20 + (ring/step)*30) % 256;
            end
          end
        end
      end
    end
  endtask


endpackage

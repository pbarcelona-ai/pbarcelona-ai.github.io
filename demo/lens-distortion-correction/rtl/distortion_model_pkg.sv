// ***************
// Filename: distortion_model_pkg.sv
// Author: Paul Barcelona
// Description: Defines calib_params_t, the packed struct bundling every
// camera-calibration and radial/tangential distortion coefficient
// coord_gen needs. Demo scope: radial (barrel/pincushion) distortion
// only -- see README.md for what was removed and why.
// Date: September 28, 2026
// ***************
// =============================================================================
// distortion_model_pkg.sv
//
// Reusable SystemVerilog structure bundling every per-frame calibration /
// distortion parameter coord_gen needs. Bundling these into ONE packed
// struct (rather than coord_gen taking a dozen individual scalar ports)
// keeps the port list stable across axis_out_ctrl.sv, image_system_demo.sv
// and axi_lite_regs.sv.
//
// FIXED-POINT: every field is Q16.16 (see barrel_pkg.sv) unless noted.
//
// CAMERA CALIBRATION: fx_pix/fy_pix/cx_pix/cy_pix follow the standard
// pinhole camera intrinsic-matrix convention (focal lengths and principal
// point, in pixels) --
//     nx = (x - cx_pix) / fx_pix
//     ny = (y - cy_pix) / fy_pix
// rather than this design's original "fraction-of-width center + single
// edge-crop scale" parameterization (CENTER_X/CENTER_Y/SCALE), of which
// fx_pix/fy_pix/cx_pix/cy_pix are a strict generalization: the original
// parameterization is recovered by setting fx_pix=halfW*scale,
// fy_pix=halfH*scale, cx_pix=CENTER_X*width, cy_pix=CENTER_Y*height (this
// is exactly what axi_lite_regs.sv's CALIB_MODE=0, the default, still
// does -- see its header comment). CALIB_MODE=1 takes fx_pix/fy_pix/
// cx_pix/cy_pix directly from AXI-Lite registers instead.
//
// RADIAL + TANGENTIAL DISTORTION (barrel/pincushion + "plumb bob"):
// k1/k2/k3 (radial, r^2/r^4/r^6 terms) plus p1/p2 (tangential, the
// standard OpenCV/"plumb bob" camera-calibration terms):
//     x' = x*(1+k1 r^2+k2 r^4+k3 r^6) + 2 p1 x y + p2 (r^2 + 2x^2)
//     y' = y*(1+k1 r^2+k2 r^4+k3 r^6) + p1 (r^2 + 2y^2) + 2 p2 x y
// Barrel distortion is k1<0 (this demo's only tested case); pincushion
// (k1>0), fisheye/panoramic (division model) and perspective (homography)
// were supported by an earlier, more general revision of this project and
// were removed for this demo -- the hardware only implements the one
// model above, unconditionally (there is no MODEL_SEL any more).
// =============================================================================
package distortion_model_pkg;

  typedef struct packed {
    // Camera calibration intrinsics (pinhole model), pixels, Q16.16
    logic signed [31:0] cx_pix;
    logic signed [31:0] cy_pix;
    logic signed [31:0] fx_pix;
    logic signed [31:0] fy_pix;
    logic        [31:0] recip_fx;   // 1/fx_pix, Q16.16 unsigned (precomputed -- avoids a
    logic        [31:0] recip_fy;   // per-pixel divide; see fixed_recip.sv)

    // Radial distortion coefficients (r^2, r^4, r^6 terms).
    logic signed [31:0] k1;
    logic signed [31:0] k2;
    logic signed [31:0] k3;

    // Tangential ("plumb bob") distortion coefficients
    logic signed [31:0] p1;
    logic signed [31:0] p2;
  } calib_params_t;

endpackage

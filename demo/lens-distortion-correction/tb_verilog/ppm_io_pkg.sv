// ***************
// Filename: ppm_io_pkg.sv
// Author: Paul Barcelona
// Description: Pure-SystemVerilog binary PPM (P6) writer used by the
// no-Python testbench. Demo scope: write-only -- this testbench
// always generates its own synthetic test chart, it never reads a
// user-supplied image file (see golden_model_pkg.sv's
// generate_synthetic_chart).
// Date: September 28, 2026
// ***************
// =============================================================================
// ppm_io_pkg.sv
//
// Minimal binary-PPM (P6) writer for the pure-Verilog testbench, so it
// can save test/warped/corrected images without any external tooling
// dependency. There is deliberately no reader: this demo only ever
// generates its own synthetic test image, never loads one from disk.
//
// Images are stored as three parallel dynamic byte arrays (r/g/b) plus a
// width/height pair, rather than a struct array, to keep indexing simple
// (idx = y*w + x) and avoid any packed-struct portability surprises.
// =============================================================================
package ppm_io_pkg;

  task automatic ppm_write(
    input string path,
    input int    w,
    input int    h,
    input logic [7:0] img_r[],
    input logic [7:0] img_g[],
    input logic [7:0] img_b[]
  );
    integer fd, i;
    begin
      fd = $fopen(path, "wb");
      $fwrite(fd, "P6\n%0d %0d\n255\n", w, h);
      for (i = 0; i < w * h; i = i + 1)
        $fwrite(fd, "%c%c%c", img_r[i], img_g[i], img_b[i]);
      $fclose(fd);
    end
  endtask

endpackage

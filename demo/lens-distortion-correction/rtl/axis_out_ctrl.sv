// ***************
// Filename: axis_out_ctrl.sv
// Author: Paul Barcelona
// Description: Generates the output raster and AXI4-Stream video
// master. Drives coord_gen for each pixel's source address, expands
// it into the four frame_buffer read addresses, and bilinear-
// interpolates the result. Fully pipelined, 1 pixel/clock, fixed
// 31-cycle latency.
// Date: September 28, 2026
// ***************
// =============================================================================
// axis_out_ctrl.sv
//
// Generates the output raster, drives coord_gen to compute the fractional
// source address for each output pixel, expands that into the frame_buffer
// read addresses (with clamp-to-edge boundary handling), and produces the
// bilinear-interpolated AXI4-Stream video output.
//
// This is the original, fully-pipelined, never-stalling 2x2-tap datapath:
// one output pixel per clock, with a fixed TOTAL_LATENCY=31-cycle delay --
// this reproduces the exact same "line, then barrel_pkg::LINE_GAP_CYCLES
// idle" timing at the output as at the input, because every stage always
// flows (no backpressure capability mid-pipeline -- see README).
//
// This design assumes the downstream consumer is always ready
// (m_axis_tready held high) -- consistent with a fixed-rate video
// pipeline.
// =============================================================================

module axis_out_ctrl #(
  parameter int COORD_W = barrel_pkg::COORD_W,
  parameter int ADDR_W  = barrel_pkg::ADDR_W
) (
  input  logic                 clk,
  input  logic                 rst_n,

  // control
  input  logic                 start_output,     // 1-cycle pulse: begin generating a frame
  input  logic [COORD_W-1:0]   img_width,
  input  logic [COORD_W-1:0]   img_height,
  output logic                 busy,
  output logic                 frame_out_done,   // 1-cycle pulse: last output beat sent

  // configuration (passed straight through to coord_gen as a single
  // struct -- see distortion_model_pkg.sv)
  input  distortion_model_pkg::calib_params_t cfg,

  // frame_buffer read port
  output logic                 fb_rd_en,
  output logic [ADDR_W-1:0]    fb_rd_addr0,
  output logic [ADDR_W-1:0]    fb_rd_addr1,
  output logic [ADDR_W-1:0]    fb_rd_addr2,
  output logic [ADDR_W-1:0]    fb_rd_addr3,
  input  logic [barrel_pkg::PIX_W-1:0]     fb_rd_data0,
  input  logic [barrel_pkg::PIX_W-1:0]     fb_rd_data1,
  input  logic [barrel_pkg::PIX_W-1:0]     fb_rd_data2,
  input  logic [barrel_pkg::PIX_W-1:0]     fb_rd_data3,

  // AXI4-Stream master (video out)
  output logic                 m_axis_tvalid,
  input  logic                 m_axis_tready,
  output logic [barrel_pkg::PIX_W-1:0]     m_axis_tdata,
  output logic                 m_axis_tlast,
  output logic                 m_axis_tuser
);

  // ---------------------------------------------------------------------
  // Raster / gap generator (request side). Bilinear-only, always
  // fully-pipelined: unlike an earlier, more general revision of this
  // project (which also supported bicubic and a per-pixel-divide "slow
  // path", both needing to pace requests one-at-a-time), this datapath
  // always sustains 1 pixel/clock, so the raster generator never needs
  // to hold and wait for a request to complete before issuing the next.
  // ---------------------------------------------------------------------
  typedef enum logic [1:0] {R_IDLE, R_ACTIVE, R_GAP, R_DONE} rstate_t;
  rstate_t rstate;

  logic [COORD_W-1:0] x_cnt, y_cnt;
  logic [2:0]          gap_cnt;
  logic                 req_valid, req_tlast, req_tuser;
  logic [COORD_W-1:0]   req_x, req_y;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rstate <= R_IDLE; x_cnt <= '0; y_cnt <= '0; gap_cnt <= '0;
      req_valid <= 1'b0; req_tlast <= 1'b0; req_tuser <= 1'b0;
      req_x <= '0; req_y <= '0;
    end else begin
      req_valid <= 1'b0; req_tlast <= 1'b0; req_tuser <= 1'b0;
      unique case (rstate)
        R_IDLE: begin
          if (start_output && img_width != 0 && img_height != 0) begin
            x_cnt <= '0; y_cnt <= '0;
            rstate <= R_ACTIVE;
          end
        end
        R_ACTIVE: begin
          req_valid <= 1'b1;
          req_x     <= x_cnt;
          req_y     <= y_cnt;
          req_tlast <= (x_cnt == img_width - 1);
          req_tuser <= (x_cnt == 0) && (y_cnt == 0);
          if (x_cnt == img_width - 1) begin
            if (y_cnt == img_height - 1) begin
              rstate <= R_DONE;
            end else begin
              x_cnt   <= '0;
              y_cnt   <= y_cnt + 1'b1;
              gap_cnt <= '0;
              rstate  <= R_GAP;
            end
          end else begin
            x_cnt <= x_cnt + 1'b1;
          end
        end
        R_GAP: begin
          if (gap_cnt == barrel_pkg::LINE_GAP_CYCLES - 1) rstate <= R_ACTIVE;
          else                                gap_cnt <= gap_cnt + 1'b1;
        end
        R_DONE: begin
          rstate <= R_IDLE;
        end
        default: rstate <= R_IDLE;
      endcase
    end
  end

  assign busy = (rstate != R_IDLE);

  // ---------------------------------------------------------------------
  // coord_gen: request (x,y) -> fractional source address. Fixed
  // 23-cycle latency, 1 request/clock.
  // ---------------------------------------------------------------------
  logic               cg_valid;
  logic signed [31:0] cg_sx, cg_sy;
  logic               cg_busy;   // unused (coord_gen never stalls in this demo)

  coord_gen #(.COORD_W(COORD_W)) u_coord_gen (
    .clk, .rst_n,
    .cfg,
    .in_valid (req_valid),
    .in_x     (req_x),
    .in_y     (req_y),
    .out_valid (cg_valid),
    .out_sx_q16(cg_sx),
    .out_sy_q16(cg_sy),
    .busy      (cg_busy)
  );

  // ---------------------------------------------------------------------
  // Address-expand stage: split into integer/fraction, clamp-to-edge,
  // compute the two row base addresses (single multiply: y0*width) and
  // the four corner read addresses. +1 cycle latency.
  // ---------------------------------------------------------------------
  logic                ae_valid;
  logic [7:0]           ae_fx, ae_fy;
  logic [ADDR_W-1:0]    ae_addr_tl, ae_addr_tr, ae_addr_bl, ae_addr_br;

  logic signed [COORD_W+1:0] x0_s, y0_s;      // extra headroom for clamp compares
  logic [7:0]                fx_c, fy_c;
  logic [COORD_W-1:0]        x0_clamped, y0_clamped;

  always_comb begin
    x0_s = cg_sx >>> barrel_pkg::FRAC_BITS;
    y0_s = cg_sy >>> barrel_pkg::FRAC_BITS;

    if (cg_sx < 0) begin
      x0_clamped = '0;
      fx_c       = 8'd0;                 // fully weight the leftmost column
    end else if (x0_s > $signed({2'b00, img_width}) - 2) begin
      x0_clamped = img_width - 2;
      fx_c       = 8'd255;               // fully weight the rightmost column
    end else begin
      x0_clamped = x0_s[COORD_W-1:0];
      fx_c       = cg_sx[15:8];
    end

    if (cg_sy < 0) begin
      y0_clamped = '0;
      fy_c       = 8'd0;                 // fully weight the topmost row
    end else if (y0_s > $signed({2'b00, img_height}) - 2) begin
      y0_clamped = img_height - 2;
      fy_c       = 8'd255;               // fully weight the bottommost row
    end else begin
      y0_clamped = y0_s[COORD_W-1:0];
      fy_c       = cg_sy[15:8];
    end

  end

  // Address generation is pipelined over 4 register stages (timing: the
  // row-base multiply y0*width, the row-base adds, and the four corner
  // adds each get their own cycle, instead of clamp+multiply+add in one):
  //   AE0: clamp / split into integer + fraction
  //   AE1: rowbase0 = y0 * width      (registered product)
  //   AE2: rowbase1 = rowbase0 + width
  //   AE3: the four corner addresses
  // fx/fy/valid are delayed alongside so everything stays aligned.
  logic                v_ae0, v_ae1, v_ae2;
  logic [7:0]          fx_ae0, fy_ae0, fx_ae1, fy_ae1, fx_ae2, fy_ae2;
  logic [COORD_W-1:0]  x_ae0, y_ae0, x_ae1, x_ae2;
  logic [ADDR_W-1:0]   rowbase0_ae1, rowbase0_ae2, rowbase1_ae2;
  logic [ADDR_W-1:0]   img_width_x;            // width zero-extended to address width
  assign img_width_x = {{(ADDR_W-COORD_W){1'b0}}, img_width};

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      v_ae0 <= 1'b0; v_ae1 <= 1'b0; v_ae2 <= 1'b0; ae_valid <= 1'b0;
    end else begin
      v_ae0    <= cg_valid;
      v_ae1    <= v_ae0;
      v_ae2    <= v_ae1;
      ae_valid <= v_ae2;
    end
  end
  // Data registers carry no reset (only the valid bits do), so the
  // synthesizer can absorb the multiplier's product register into the DSP.
  always_ff @(posedge clk) begin
    // AE0
    x_ae0 <= x0_clamped; y_ae0 <= y0_clamped; fx_ae0 <= fx_c; fy_ae0 <= fy_c;
    // AE1
    rowbase0_ae1 <= {{(ADDR_W-COORD_W){1'b0}}, y_ae0} * img_width_x;
    x_ae1 <= x_ae0; fx_ae1 <= fx_ae0; fy_ae1 <= fy_ae0;
    // AE2
    rowbase0_ae2 <= rowbase0_ae1;
    rowbase1_ae2 <= rowbase0_ae1 + img_width_x;
    x_ae2 <= x_ae1; fx_ae2 <= fx_ae1; fy_ae2 <= fy_ae1;
    // AE3
    ae_addr_tl <= rowbase0_ae2 + {{(ADDR_W-COORD_W){1'b0}}, x_ae2};
    ae_addr_tr <= rowbase0_ae2 + {{(ADDR_W-COORD_W){1'b0}}, x_ae2} + 1'b1;
    ae_addr_bl <= rowbase1_ae2 + {{(ADDR_W-COORD_W){1'b0}}, x_ae2};
    ae_addr_br <= rowbase1_ae2 + {{(ADDR_W-COORD_W){1'b0}}, x_ae2} + 1'b1;
    ae_fx <= fx_ae2; ae_fy <= fy_ae2;
  end

  assign fb_rd_en    = ae_valid;
  assign fb_rd_addr0 = ae_addr_tl;
  assign fb_rd_addr1 = ae_addr_tr;
  assign fb_rd_addr2 = ae_addr_bl;
  assign fb_rd_addr3 = ae_addr_br;

  // frame_buffer read itself is synchronous (+1 cycle); delay fx,fy and
  // valid to stay aligned with fb_rd_data*.
  logic        rd_valid;
  logic [7:0]  rd_fx, rd_fy;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rd_valid <= 1'b0; rd_fx <= '0; rd_fy <= '0;
    end else begin
      rd_valid <= ae_valid;
      rd_fx    <= ae_fx;
      rd_fy    <= ae_fy;
    end
  end

  // ---------------------------------------------------------------------
  // Bilinear interpolation, 3-cycle latency
  // ---------------------------------------------------------------------
  logic               bl_valid;
  logic [barrel_pkg::PIX_W-1:0]   bl_pixel;

  bilinear u_bilinear (
    .clk, .rst_n,
    .valid_in (rd_valid),
    .fx (rd_fx), .fy (rd_fy),
    .tl (fb_rd_data0), .tr (fb_rd_data1), .bl (fb_rd_data2), .br (fb_rd_data3),
    .valid_out (bl_valid),
    .pixel_out (bl_pixel)
  );

  // ---------------------------------------------------------------------
  // tlast/tuser tag delay line. Fed every cycle by req_tlast/req_tuser;
  // TOTAL_LATENCY = coord_gen(23) + address-expand(4) + frame_buffer
  // read(1) + bilinear(3) = 31 cycles, measured directly in simulation
  // (never hand-derived alone -- an earlier, more general revision of
  // this project was once bitten by a hand-derived bicubic latency being
  // off by one; see README's "A real bug found & fixed during bring-up").
  // ---------------------------------------------------------------------
  localparam int TOTAL_LATENCY = 31;
  logic [TOTAL_LATENCY-1:0] tlast_sr, tuser_sr;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      tlast_sr <= '0; tuser_sr <= '0;
    end else begin
      tlast_sr <= {tlast_sr[TOTAL_LATENCY-2:0], req_tlast};
      tuser_sr <= {tuser_sr[TOTAL_LATENCY-2:0], req_tuser};
    end
  end

  assign m_axis_tvalid = bl_valid;
  assign m_axis_tdata  = bl_pixel;
  assign m_axis_tlast  = tlast_sr[TOTAL_LATENCY-1];
  assign m_axis_tuser  = tuser_sr[TOTAL_LATENCY-1];

  // ---------------------------------------------------------------------
  // Output beat counter -> frame_out_done
  // ---------------------------------------------------------------------
  logic [ADDR_W:0] beats_remaining;
  logic             counting;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      beats_remaining <= '0; counting <= 1'b0; frame_out_done <= 1'b0;
    end else begin
      frame_out_done <= 1'b0;
      if (start_output) begin
        beats_remaining <= {1'b0, img_width} * {1'b0, img_height};
        counting <= 1'b1;
      end else if (counting && m_axis_tvalid && m_axis_tready) begin
        if (beats_remaining <= 1) begin
          counting       <= 1'b0;
          frame_out_done <= 1'b1;
        end else begin
          beats_remaining <= beats_remaining - 1'b1;
        end
      end
    end
  end

endmodule

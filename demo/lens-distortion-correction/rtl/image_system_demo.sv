// ***************
// Filename: image_system_demo.sv
// Author: Paul Barcelona
// Description: Top-level RTL for lens-distortion-correction
// (module image_system_demo). Integrates
// axis_in_ctrl, frame_buffer, axis_out_ctrl, and axi_lite_regs,
// and sequences the load-then-output FSM (T_LOAD/T_OUTPUT) that
// buffers a whole input frame before streaming the corrected
// output. Demo scope: barrel/pincushion radial distortion
// correction, bilinear interpolation only.
// Date: September 28, 2026
// ***************
// =============================================================================
// image_system_demo.sv
//
// Top-level barrel-distortion-correction demo core.
//
//   - s_axis_*: AXI4-Stream video input. Each line = IMG_WIDTH back-to-back
//     beats (tlast on the final pixel), followed by >=5 idle cycles before
//     the next line. tuser marks the first pixel of the frame.
//   - m_axis_*: AXI4-Stream video output, same per-line/idle-gap timing,
//     carrying the corrected frame.
//   - s_axil_*: AXI4-Lite configuration (k1/k2/k3, image size, center,
//     scale -- see axi_lite_regs.sv for the register map).
//
// Sequencing: a whole input frame is captured into the frame buffer, then
// the corrected frame is generated and streamed out; the next input frame
// is only accepted once the previous frame's output has finished. See
// README's Known limitations for the ping-pong-buffer extension needed
// for fully overlapped (back-to-back, no dead time) frame-rate operation.
//
// The frame buffer is entirely internal (on-chip) memory -- see
// frame_buffer.sv -- sized to MAX_W x MAX_H (barrel_pkg.sv, 128x128 for
// this demo's short-edge-64 test frames). There is no bounds checking of
// IMG_WIDTH/IMG_HEIGHT against that capacity anywhere in this design: a
// configuration that exceeds it is simply wrong, silently, with no error
// signal or message (see README's Known limitations).
// =============================================================================

module image_system_demo #(
  parameter int COORD_W = barrel_pkg::COORD_W,
  parameter int ADDR_W  = barrel_pkg::ADDR_W
) (
  input  logic clk,
  input  logic rst_n,

  // AXI4-Stream slave (video in)
  input  logic                s_axis_tvalid,
  output logic                s_axis_tready,
  input  logic [barrel_pkg::PIX_W-1:0]    s_axis_tdata,
  input  logic                s_axis_tlast,
  input  logic                s_axis_tuser,

  // AXI4-Stream master (video out)
  output logic                m_axis_tvalid,
  input  logic                m_axis_tready,
  output logic [barrel_pkg::PIX_W-1:0]    m_axis_tdata,
  output logic                m_axis_tlast,
  output logic                m_axis_tuser,

  // AXI4-Lite slave (config)
  input  logic [7:0]   s_axil_awaddr,
  input  logic         s_axil_awvalid,
  output logic         s_axil_awready,
  input  logic [31:0]  s_axil_wdata,
  input  logic [3:0]   s_axil_wstrb,
  input  logic         s_axil_wvalid,
  output logic         s_axil_wready,
  output logic [1:0]   s_axil_bresp,
  output logic         s_axil_bvalid,
  input  logic         s_axil_bready,
  input  logic [7:0]   s_axil_araddr,
  input  logic         s_axil_arvalid,
  output logic         s_axil_arready,
  output logic [31:0]  s_axil_rdata,
  output logic [1:0]   s_axil_rresp,
  output logic         s_axil_rvalid,
  input  logic         s_axil_rready
);

  // ---- config regs ---------------------------------------------------
  distortion_model_pkg::calib_params_t cfg;
  logic [COORD_W-1:0] img_width, img_height;
  logic                cfg_recip_busy;

  logic top_busy, frame_done_in, frame_out_done;

  axi_lite_regs #(.COORD_W(COORD_W)) u_regs (
    .clk, .rst_n,
    .s_axil_awaddr, .s_axil_awvalid, .s_axil_awready,
    .s_axil_wdata, .s_axil_wstrb, .s_axil_wvalid, .s_axil_wready,
    .s_axil_bresp, .s_axil_bvalid, .s_axil_bready,
    .s_axil_araddr, .s_axil_arvalid, .s_axil_arready,
    .s_axil_rdata, .s_axil_rresp, .s_axil_rvalid, .s_axil_rready,
    .top_busy, .top_frame_done_pulse(frame_out_done),
    .cfg_out(cfg),
    .img_width, .img_height,
    .cfg_recip_busy
  );

  // ---- top sequencing FSM ---------------------------------------------
  typedef enum logic {T_LOAD, T_OUTPUT} tstate_t;
  tstate_t tstate;

  logic capture_en, start_output;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      tstate <= T_LOAD;
      start_output <= 1'b0;
    end else begin
      start_output <= 1'b0;
      unique case (tstate)
        T_LOAD: begin
          if (frame_done_in) begin
            start_output <= 1'b1;
            tstate <= T_OUTPUT;
          end
        end
        T_OUTPUT: begin
          if (frame_out_done) tstate <= T_LOAD;
        end
        default: tstate <= T_LOAD;
      endcase
    end
  end

  assign capture_en = (tstate == T_LOAD) && !cfg_recip_busy;
  assign top_busy   = (tstate == T_OUTPUT) || cfg_recip_busy;

  // ---- frame buffer (internal memory only -- see frame_buffer.sv) -----
  logic               fb_wr_en;
  logic [ADDR_W-1:0]  fb_wr_addr;
  logic [barrel_pkg::PIX_W-1:0]   fb_wr_data;
  logic               fb_rd_en;
  logic [ADDR_W-1:0]  fb_rd_addr0, fb_rd_addr1, fb_rd_addr2, fb_rd_addr3;
  logic [barrel_pkg::PIX_W-1:0]   fb_rd_data0, fb_rd_data1, fb_rd_data2, fb_rd_data3;

  frame_buffer #(.PIX_W(barrel_pkg::PIX_W), .ADDR_W(ADDR_W)) u_fb (
    .clk,
    .wr_en(fb_wr_en), .wr_addr(fb_wr_addr), .wr_data(fb_wr_data),
    .rd_en(fb_rd_en),
    .rd_addr0(fb_rd_addr0), .rd_addr1(fb_rd_addr1), .rd_addr2(fb_rd_addr2), .rd_addr3(fb_rd_addr3),
    .rd_data0(fb_rd_data0), .rd_data1(fb_rd_data1), .rd_data2(fb_rd_data2), .rd_data3(fb_rd_data3)
  );

  // ---- input controller ---------------------------------------------
  axis_in_ctrl #(.COORD_W(COORD_W), .ADDR_W(ADDR_W)) u_in (
    .clk, .rst_n,
    .capture_en, .img_width, .img_height,
    .frame_done(frame_done_in), .busy(), .err_line_len(),
    .s_axis_tvalid, .s_axis_tready, .s_axis_tdata, .s_axis_tlast, .s_axis_tuser,
    .wr_en(fb_wr_en), .wr_addr(fb_wr_addr), .wr_data(fb_wr_data)
  );

  // ---- output controller (bilinear only) -------------------------------
  axis_out_ctrl #(.COORD_W(COORD_W), .ADDR_W(ADDR_W)) u_out (
    .clk, .rst_n,
    .start_output, .img_width, .img_height,
    .busy(), .frame_out_done,
    .cfg,
    .fb_rd_en, .fb_rd_addr0, .fb_rd_addr1, .fb_rd_addr2, .fb_rd_addr3,
    .fb_rd_data0, .fb_rd_data1, .fb_rd_data2, .fb_rd_data3,
    .m_axis_tvalid, .m_axis_tready, .m_axis_tdata, .m_axis_tlast, .m_axis_tuser
  );

endmodule

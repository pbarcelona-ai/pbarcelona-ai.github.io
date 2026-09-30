# barcelona-enterprizes
Barcelona Enterprises of Florida is a fabless IP developer targeting FPGA and ASIC designs.

Live site: https://pbarcelona-ai.github.io/

## GitHub Actions

The root-level workflow at `.github/workflows/ci.yml` runs the lens-distortion-correction demo's simulation and synthesis checks on pushes, pull requests, and manual dispatches. Jobs use GitHub-hosted `ubuntu-latest` runners by default.

To select a self-hosted runner, add the repository Actions variable `CI_RUNNER_LABELS` with a JSON array of runner labels, for example `["self-hosted","linux"]`. The runner must be Linux with Bash and `make`; Icarus Verilog and Yosys must be preinstalled unless the runner can install packages using `sudo apt-get`.

See [the demo documentation](demo/lens-distortion-correction/README.md) for the test and synthesis details.

## Site generation

Run `python3 scripts/generate_site.py` to generate `index.html` and `demo/index.html` from the templates in `templates/`.

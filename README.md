# barcelona-enterprizes
FPGA Cores 4U is a fabless IP developer targeting FPGA and ASIC designs.

Live site: https://pbarcelona-ai.github.io/

## GitHub Actions

The root-level workflow at `.github/workflows/ci.yml` runs the lens-distortion-correction demo's simulation and synthesis checks on pushes, pull requests, and manual dispatches. Jobs use GitHub-hosted `ubuntu-latest` runners by default.

To select a self-hosted runner, add the repository Actions variable `CI_RUNNER_LABELS` with a JSON array of runner labels, for example `["self-hosted","linux"]`. The runner must be Linux with Bash and `make`; Icarus Verilog and Yosys must be preinstalled unless the runner can install packages using `sudo apt-get`.

See [the demo documentation](demo/lens-distortion-correction/README.md) for the test and synthesis details.

## Site generation

Run `python3 scripts/generate_site.py` to generate `index.html` and `demo/index.html` from the templates in `templates/`.

## Digital IP catalog

`digital_ip/` is the [digital_ip](https://github.com/pbarcelona-ai/digital_ip) git submodule (see `.gitmodules`), checked out in full. Its generated catalog pages (`digital_ip/ip/docs/` and `digital_ip/ip/tools/docs/`) are build artifacts of that project's own doc generators and are not committed here.

To (re)build them locally:

```
git submodule update --init --recursive
python3 scripts/build_digital_ip_docs.py
```

The script runs the submodule's own doc generators in place, replaces links to full RTL source with header/port-list snippets (`<module>.sv`) and shared-module snippets (`digital_ip/ip/docs/shared/`), and adds this site's SEO tags, favicon, breadcrumbs, and per-category "typical applications"/related-module sections. The `Deploy Pages` GitHub Actions workflow runs the same script on every push to `main`.

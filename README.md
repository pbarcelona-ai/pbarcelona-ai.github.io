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

To (re)build the whole site locally:

```
git submodule update --init --recursive
python3 -m pip install pillow "pagefind[extended]==1.5.2"
python3 scripts/build_digital_ip_docs.py   # IP pages under /ip/, social cards under /og/
python3 scripts/finalize_site.py           # sitemap.xml, cards for hand-written pages, analytics tag
python3 -m pagefind --site .               # search index under /pagefind/ (used by search.html)
```

`build_digital_ip_docs.py` runs the submodule's own doc generators in place, replaces links to full RTL source with header/port-list snippets (`<module>.sv`) and shared-module snippets (`digital_ip/ip/docs/shared/`), and publishes every module page at a short URL (`/ip/<module-name>/`, e.g. `/ip/async-fifo/`) with SEO tags, a datasheet section (clocking, latency, Yosys utilization, parameters), the RTL hierarchy diagram, a social card, JSON-LD and related modules. The old `digital_ip/ip/docs/...` URLs become redirects. It also regenerates the IP index on the home page (between the `IP-INDEX` markers). `ip/`, `og/` and `pagefind/` are build output and are gitignored.

`finalize_site.py` writes `sitemap.xml`, draws the social cards for the home, demo and design-notes pages, and adds the GoatCounter analytics tag to every page when `GOATCOUNTER_CODE` is set at the top of the script.

The `Deploy Pages` GitHub Actions workflow runs these steps on every push to `main`, deploys, then submits the sitemap's URLs to IndexNow (Bing, Yandex and others) with `scripts/indexnow.py`. The IndexNow key is the `<32 hex chars>.txt` file at the site root.

Design notes live in `design-notes/`; add new ones to the list on the home page, and to `DESIGN_NOTES` in `build_digital_ip_docs.py` to link them from the matching module pages.

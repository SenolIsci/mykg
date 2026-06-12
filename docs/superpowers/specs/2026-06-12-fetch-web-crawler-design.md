# Design: `mykg fetch-web` — Website Fetching & Ingestion

**Date:** 2026-06-12
**Status:** Proposed (awaiting implementation)
**Scope:** v1 — standalone web crawler that produces a local folder consumable by `extract-graph`.

---

## 1. Goal

Let mykg build knowledge graphs from **websites** in addition to local raw files.
A new standalone command `mykg fetch-web <url>` performs a **full same-domain
site crawl**, saves each page as **raw HTML** (plus optionally linked binary
assets) into a target folder, and writes a `fetch_manifest.json` recording URL →
local-file provenance and content hashes. The folder is then an ordinary
`extract-graph` input: the existing `preprocess` step converts the HTML to
Markdown via `markdownify` (D44) and any PDFs/DOCX via MinerU (D40), and the
rest of the pipeline runs unchanged.

**Non-goals (v1):**
- No new pipeline step and no session creation — `fetch-web` is a pure
  file-to-file utility, exactly like `parse-docs` (D40).
- No HTML→Markdown conversion inside the crawler — that stays in
  `step_preprocess` (D44). The crawler's only job is **acquisition + provenance**.
- No in-graph URL provenance — the graph's existing `source_files` field names
  the local file; a consumer joins back to the URL via `fetch_manifest.json`.
  Threading the URL into nodes/edges is deferred to a later iteration.
- No JavaScript rendering (no headless browser). Static HTML only.

---

## 2. Decisions (resolved during brainstorming)

| # | Question | Decision |
|---|----------|----------|
| 1 | Fetch scope | **Full same-domain site crawl** (seed URL → follow all internal links) |
| 2 | Integration | **Separate `mykg fetch-web` command** (no pipeline coupling; output is a normal `extract-graph` input) |
| 3 | Save format | **Raw HTML**; existing `preprocess` does the conversion |
| 4 | Linked assets | **Configurable** via `fetch.download_assets` (default reuses the `preprocess.extensions` allowlist) |
| 5 | Guardrails | **All four**: robots.txt, same-domain + max-depth/max-pages caps, rate limiting (delay + concurrency), resume/dedup via manifest |
| 6 | Crawler stack | **Crawlee for Python** (`crawlee[beautifulsoup]`) in an **ephemeral uv venv**, destroyed on exit (mirrors MinerU, D48) |
| 7 | Output layout | **Folder + `fetch_manifest.json`** (the manifest also serves as resume/dedup state) |
| 8 | URL provenance | **Manifest-only for v1** (no pipeline data-model changes) |

---

## 3. Architecture

`fetch-web` mirrors the **MinerU pattern** that already exists in the codebase
for heavy/conflicting dependencies (D48): the crawler library is **never**
installed into mykg's own interpreter. It runs inside an ephemeral
`uv`-managed venv created per invocation and deleted on exit. Crawlee's asyncio
runtime is fully contained inside the subprocess and never touches mykg's
`ThreadPoolExecutor` world (Invariant 12 untouched).

### 3.1 Component boundaries

| Unit | Responsibility | Depends on |
|---|---|---|
| `cli.py :: fetch_web` (new command) | Parse args, resolve output dir, build/teardown venv, write the crawl-config JSON, spawn the crawl runner inside the venv, surface failures via exit code | `uv_venv`, `config`, `fetch_web` |
| `uv_venv.py :: ephemeral_venv(...)` (generalized) | Generic ephemeral venv: create with a pinned Python, `uv pip install` a spec, yield a named binary (or the venv `python`). `ephemeral_mineru_venv` is refactored into a thin wrapper over it — **no behavior change** | `uv` |
| `fetch_web.py` (new module) | Pure, unit-testable helpers: build the crawl-config dict from `config` constants + CLI args; resolve the output directory; load the prior `fetch_manifest.json`; merge new rows; write the manifest atomically (`*.tmp` → `os.replace`) | `config` |
| `data/_crawl_runner.py` (new bundled script, run **inside** the venv) | The actual Crawlee BFS. Reads a crawl-config JSON path from argv; runs a `BeautifulSoupCrawler`; saves each page's raw bytes to the output folder; emits one manifest row per fetched resource to a results JSON the parent reads back | `crawlee` (venv-only; **never** imported by mykg) |

The runner is shipped as package data (like `src/mykg/data/mykg_config.yaml`) and
executed via `<venv>/bin/python <path-to-runner>.py <config.json>`. It is the
**single** place Crawlee is imported.

### 3.2 Why a generic `ephemeral_venv`

`ephemeral_mineru_venv` currently hardcodes `prefix="mykg-mineru-venv-"`, the
binary name `mineru`, and MinerU-flavored error messages. The new generic
`ephemeral_venv(python_version, spec, uv_path, install_timeout, *, bin_name,
prefix)` factors those out. `ephemeral_mineru_venv` becomes:

```python
@contextmanager
def ephemeral_mineru_venv(python_version, mineru_spec, uv_path, install_timeout):
    with ephemeral_venv(python_version, mineru_spec, uv_path, install_timeout,
                        bin_name="mineru", prefix="mykg-mineru-venv-") as mineru_bin:
        yield mineru_bin
```

For `fetch-web` we need the venv **`python`**, not a console-script binary
(we run `python _crawl_runner.py`). `ephemeral_venv` therefore yields the venv
`python` path when `bin_name="python"`; the existing MinerU caller is unaffected.

---

## 4. CLI surface

```
mykg fetch-web URL
    [--output PATH]              # target folder (default: ./fetched_web/<domain>/)
    [--max-pages N]              # hard cap on total fetched pages (overrides config)
    [--max-depth N]              # max crawl depth from the seed (overrides config)
    [--strategy same-domain|same-origin|all]   # link-following scope (default: same-domain).
                                                # `all` leaves the seed domain — use with caution;
                                                # combine with --max-pages to bound it.
    [--download-assets / --no-download-assets]   # override fetch.download_assets
    [--delay SECONDS]            # per-request delay (overrides config)
    [--concurrency N]            # max concurrent requests (overrides config)
    [--no-robots]                # disable robots.txt compliance (default: respect)
    [--force]                    # ignore prior manifest; re-fetch everything
    [--verbose / -v]
```

- `URL` is the single seed (required). Multiple seeds are out of scope for v1.
- CLI flags **override** the corresponding `fetch:` YAML defaults (Invariant 7:
  YAML is the source of truth; flags are per-run overrides).
- `--output` defaults to `./fetched_web/<seed-domain>/` so a bare
  `mykg fetch-web https://example.com` is one-shot usable, then
  `mykg extract-graph ./fetched_web/example.com/`.

### 4.1 Handler flow (mirrors `parse_docs`, D40)

1. Resolve output dir; `mkdir -p`.
2. Load prior `fetch_manifest.json` if present and `--force` not set →
   `already_fetched: {url: sha256}` for dedup/resume.
3. Build the crawl-config dict (seed, scope, caps, delay, concurrency, robots,
   allowed asset extensions = `PREPROCESS_EXTENSIONS` when `download_assets`,
   else `frozenset()`), write it to `<output>/.fetch_config.json`.
4. `with ephemeral_venv(FETCH_UV_PYTHON_VERSION, FETCH_CRAWLEE_SPEC,
   FETCH_UV_PATH, FETCH_INSTALL_TIMEOUT_SECONDS, bin_name="python") as py:`
   run `subprocess.run([py, runner_path, config_path], timeout=FETCH_TIMEOUT_SECONDS)`.
5. Runner writes pages to disk and a `<output>/.fetch_results.json` (list of
   manifest rows). Parent reads it back, merges with the prior manifest, and
   writes `fetch_manifest.json` atomically.
6. Exit non-zero if the runner failed; per-page fetch failures (4xx/5xx) are
   recorded in the manifest with their status and do **not** fail the command
   (matches D39 non-blocking per-file semantics). Timeout is fatal (matches
   `parse-docs`).

---

## 5. Crawl runner (`_crawl_runner.py`)

Runs inside the venv. Reads the crawl-config JSON, then:

```python
crawler = BeautifulSoupCrawler(
    max_requests_per_crawl=cfg["max_pages"],
    respect_robots_txt_file=cfg["respect_robots"],
    # concurrency + delay via ConcurrencySettings / request-handler sleep
)

@crawler.router.default_handler
async def handler(context):
    # 1. Save raw response bytes to <output>/<url-path>.html (or asset ext)
    # 2. Append a manifest row: {url, local_file, sha256, content_type,
    #    status, depth, fetched_at}
    # 3. enqueue_links(strategy=cfg["strategy"])  # same-domain by default
    # 4. If download_assets: also enqueue allowed-extension asset links and
    #    save their bytes verbatim (no parsing)

await crawler.run([cfg["seed_url"]])
# write all manifest rows to <output>/.fetch_results.json
```

Crawlee provides all four guardrails natively
(`respect_robots_txt_file`, `enqueue_links(strategy='same-domain')`,
`max_requests_per_crawl`, concurrency/delay settings), so the runner stays small.

### 5.1 Filename derivation

Each URL maps to a local path under `<output>/`:
- Path component of the URL becomes the subpath; `index.html` for trailing-slash
  paths; query strings hashed into the filename to avoid collisions.
- Content-type decides the extension: `text/html` → `.html`; otherwise the asset's
  own extension (validated against the allowlist).
- Subfolder structure under `<output>/` is preserved so `extract-graph`'s
  `rglob("*.html")` / preprocess pick them up naturally.

### 5.2 Resume / dedup

A URL already present in the prior manifest with a matching content SHA is
**skipped** (not re-saved). New/changed URLs are fetched. This mirrors the D49
SHA-based incremental conversion contract on the acquisition layer. `--force`
clears the prior manifest and re-fetches everything.

---

## 6. `fetch_manifest.json` format

Written atomically to `<output>/fetch_manifest.json`. Mirrors
`preprocess_manifest.json` (D49):

```json
{
  "seed_url": "https://example.com",
  "strategy": "same-domain",
  "fetched_at": "2026-06-12T12:34:56Z",
  "crawlee_version": "<resolved>",
  "stats": { "pages": 142, "assets": 17, "skipped_robots": 3, "errors": 2 },
  "pages": {
    "https://example.com/": {
      "local_file": "index.html",
      "sha256": "<hex of response bytes>",
      "content_type": "text/html",
      "status": 200,
      "depth": 0,
      "fetched_at": "2026-06-12T12:34:50Z"
    },
    "https://example.com/docs/guide.pdf": {
      "local_file": "docs/guide.pdf",
      "sha256": "...", "content_type": "application/pdf",
      "status": 200, "depth": 1, "fetched_at": "..."
    }
  }
}
```

The manifest is keyed by URL; `local_file` is relative to `<output>/`. This is
both the **provenance record** (join `source_files` → `local_file` → URL) and the
**resume state** (URL + SHA dedup).

---

## 7. Configuration (`fetch:` block)

New YAML section under each profile, exposed as `config.py` constants per
Invariant 7. **Per Invariant 17, this block must be added to both
`mykg_config.yaml` (repo root, all profiles) and
`src/mykg/data/mykg_config.yaml` (packaged template).**

```yaml
fetch:
  enabled: true                  # master toggle for the fetch-web command
  strategy: same-domain          # link-following scope (same-domain | same-origin | all)
  max_pages: 500                 # hard cap on total fetched pages (Invariant 16 bound)
  max_depth: 10                  # max crawl depth from the seed
  respect_robots: true           # honor robots.txt disallow + crawl-delay
  request_delay_seconds: 0.5     # politeness delay between requests
  concurrency: 4                 # max concurrent requests (mirrors LLM worker caps, Invariant 13)
  download_assets: true          # download linked binaries whose suffix is in preprocess.extensions
  timeout_seconds: 1800          # crawl run-phase timeout (30 min)
  uv_path: uv                    # uv CLI path (uv is a core mykg dependency)
  uv_python_version: "3.12"      # interpreter pinned for the ephemeral crawl venv
  crawlee_spec: "crawlee[beautifulsoup]"   # spec installed via `uv pip install -U`
  install_timeout_seconds: 1800  # install-phase timeout (30 min)
```

`config.py` constants: `FETCH_ENABLED`, `FETCH_STRATEGY`, `FETCH_MAX_PAGES`,
`FETCH_MAX_DEPTH`, `FETCH_RESPECT_ROBOTS`, `FETCH_REQUEST_DELAY_SECONDS`,
`FETCH_CONCURRENCY`, `FETCH_DOWNLOAD_ASSETS`, `FETCH_TIMEOUT_SECONDS`,
`FETCH_UV_PATH`, `FETCH_UV_PYTHON_VERSION`, `FETCH_CRAWLEE_SPEC`,
`FETCH_INSTALL_TIMEOUT_SECONDS`. The asset allowlist reuses the existing
`PREPROCESS_EXTENSIONS` frozenset — no separate `fetch.extensions` key.

---

## 8. Failure semantics

| Failure | Behavior |
|---|---|
| `uv` not on PATH | `RuntimeError` / `ClickException` (reuses `ephemeral_venv`'s existing guard) |
| Crawlee install fails / times out | Fatal `ClickException` with truncated stderr (existing `_run` behavior) |
| Per-page HTTP error (4xx/5xx) | Recorded in manifest with status; crawl continues (non-blocking, D39) |
| robots.txt disallow | Page skipped; counted in `stats.skipped_robots`; not an error |
| Crawl run-phase timeout | Fatal `ClickException` (matches `parse-docs` timeout semantics) |
| Runner crashes (non-zero exit) | `ClickException`; partial pages on disk + partial manifest preserved for inspection |

---

## 9. Invariants honored

- **I7** (no hardcoded values): every knob in `fetch:` YAML → `config.py` constant.
- **I9** (run isolation): `fetch-web` writes only into its `--output` folder; no
  shared state. The folder is self-contained and re-consumable.
- **I12** (parallelism): crawl concurrency is Crawlee-managed inside the venv;
  mykg's own ThreadPoolExecutor model is untouched.
- **I13** (respect rate limits): `concurrency` + `request_delay_seconds` are
  conservative defaults; a 429 from a site is a signal to lower them, not retry.
- **I16** (complexity bounded): full crawl is capped by `max_pages` and
  `max_depth`; resume/dedup makes re-runs O(new pages), not O(site).
- **I17** (config in two places): `fetch:` added to both YAML files.
- **D48** (ephemeral venv): Crawlee never enters mykg's interpreter; one venv per
  invocation, destroyed on exit. No cache by design.

---

## 10. Testing

- **Unit (no network):** `fetch_web.py` helpers — output-path resolution,
  manifest load/merge/atomic-write, crawl-config dict construction, filename
  derivation, dedup skip logic. `ephemeral_venv` generalization: assert
  `ephemeral_mineru_venv` still yields the `mineru` binary (regression).
- **Unit (runner, mocked):** `_crawl_runner` filename/manifest-row logic tested
  with a fake context (no real Crawlee run).
- **Integration (`@pytest.mark.live`):** `mykg fetch-web` against a small known
  static site (or a local `http.server` fixture serving a 3-page tree); assert
  pages saved, manifest correct, second run skips unchanged pages, then
  `extract-graph` on the folder produces a graph. Marked `live` so it's
  deselectable with `-m "not live"` (matches the existing live-test convention).

---

## 11. End-to-end verification recipe

1. `python -m http.server` over a tiny fixture site (3 linked HTML pages + 1 PDF),
   **or** a stable public docs site.
2. `mykg fetch-web http://localhost:8000/ --output /tmp/fw --max-pages 10`
3. Assert `/tmp/fw/` contains the HTML files + `fetch_manifest.json` with correct
   URL→file rows; PDF present iff `download_assets`.
4. Re-run the same command → manifest unchanged, log shows pages skipped (dedup).
5. `mykg extract-graph /tmp/fw/ --review` (or full run) → confirm preprocess
   converts the HTML to `.md`, ingest picks them up, and a graph is produced.

---

## 12. Out of scope (future iterations)

- In-graph URL provenance (thread URL through preprocess/ingest into node/edge
  `source_files` or a dedicated field).
- JS-rendered sites (`crawlee[playwright]` backend — same venv pattern, heavier).
- Multiple seed URLs / seed-list file in one invocation.
- An `extract-graph --url` convenience flag that calls fetch internally.
- Auth/cookies/login-gated crawling.

# mykg healthiness check — a dry-run smoke test

## Context

You want one command that answers: **"is everything alive and right?"** — every LLM
endpoint reachable, and every major capability in the README still working end-to-end,
run the way a user runs it.

This is a **healthiness/smoke test, not a correctness suite**. It asserts that each moving
part responds and produces sane output. It deliberately does *not* assert entity-level
extraction accuracy — that is what the 1358 unit tests cover, and an LLM-driven pipeline
is non-deterministic enough that strict content assertions would fail for the wrong
reasons and erode trust in the signal.

Research confirmed the gap is real: **no existing test drives `extract-graph` through the
CLI to real output.** Every CLI test stubs `mykg.orchestrator.run` and `load_adapter`; the
7 `@pytest.mark.live` tests bypass the CLI and call `run(STEPS, ctx)` directly. Nothing
exercises MinerU for real, nothing chains commands, and `mykg query` is only tested
against hand-written fixtures.

## What live probing established

Verified against the real endpoints and site, not assumed:

| Finding | Evidence |
|---|---|
| aiportal.news is a Next.js SPA | homepage 8.4 MB, ~1901 links, mostly `/news/<id>` |
| **mykg still extracts clean content from it** | mykg's exact chain (`BeautifulSoupCrawler` → `markdownify(html, strip=["img","a"])`) turns a 21 KB article into **359 chars / 7 clean lines, zero JS noise**: headline, publication, timestamp. Confirmed on 4 articles |
| The site is a link aggregator by design | every article ends "Go to Source Site to Read Full Story" |
| `.xlsx` already in `preprocess.extensions` | both config copies → MinerU handles it |
| `fetch.max_depth` default is already 1 | matches the requested depth |
| No usable `robots.txt` | returns a Next.js 404 → treated as allowed |
| `_test_files/` spans all three ingest paths | `technologies.md` (native), `team.pdf` (MinerU), `projects.xlsx` (MinerU) |

## Approach

One new file, `tests/test_healthiness.py`, driving the **real CLI** via
`CliRunner().invoke(cli, [...])` — the gap that matters. Config isolation via
`monkeypatch.chdir(tmp_path)` + a generated minimal `mykg_config.yaml`, because
`config._find_config()` walks upward from `cwd` and would otherwise load the repo's 84 KB
config.

**Reuse, don't reinvent:** `conftest._load_key` (generalized to `provider_key(name)`),
`exporters.neo4j._common.load_session()`, `_read_jsonl`
(`test_grow_schema_e2e.py:174`), `_output(result)` (`test_cli_commands.py:10` — essential,
Click swallows exceptions), and the `rdflib.Graph().parse(format="turtle")` idiom.

### Stage 0 — endpoint healthiness (the "is it alive" part)

Parametrized over **openrouter, anthropic, openai, gemini, ollama**, each **skipping
individually** when its key is absent or Ollama isn't running — a missing key is never a
failure.

Each provider runs **two checks**, because reachability alone is a weak signal — a
provider can answer "PONG" and still fail every real pipeline call:

**0a — reachable.** One trivial PING via `adapter.complete()`; assert a non-empty reply.
Isolates "network/auth broken" from "model can't do the job".

**0b — can do mykg's actual job.** A miniature extraction against the **real Pass 2
contract**: a tiny schema (`Person(name)`, `Organization(name)`, `works_at`) plus the
sentence *"Alice Chen is an engineer at Acme Corp."*. Then the exact call the pipeline
makes — `json.loads(adapter.complete(...))`, since `complete()` already applies
`strip_code_fences` (`llm/adapter.py:26`) and `pass2.py:309` does `json.loads(raw)`.

Assert the response shape the pipeline depends on:
```
✓ parses as JSON                    (not prose, not a fenced block)
✓ has "nodes" and "edges" keys
✓ >= 1 node, each with id + type
✓ attributes are confidence-wrapped {"value": ..., "confidence": float}
```

**Verified live** against `gemini-3.6-flash` while planning — returned 2 nodes, 1 edge,
correctly wrapped: `{"id":"Alice Chen","type":"Person","attributes":{"name":{"value":
"Alice Chen","confidence":1.0}}}`. So the probe is known-workable, not speculative.

This is the check that actually earns the word "right" in *"alive and right"* — a provider
failing 0b is one that would produce blank chunks in a real run.

Runs standalone in seconds:
```bash
uv run pytest tests/test_healthiness.py -k endpoints -v --no-cov
```
Output is a per-provider table showing reachable + contract-capable, or the skip reason.

### Stages 1–6 — capability healthiness

Run once on **openrouter** (your requested default), overridable with
`MYKG_E2E_PROFILE`. Each stage asserts *it ran and produced sane output*, nothing more.

| # | Stage | Command | Healthiness assertion |
|---|---|---|---|
| 1 | Scrape | `fetch-web https://aiportal.news --max-pages 5 --max-depth 1 --strategy same-domain` | exit 0; ≤5 `.html` files; `fetch_manifest.json` parses; all URLs same-domain |
| 2 | Convert | `parse-docs --input _test_files/ --output <dir>` | exit 0; `team.pdf` and `projects.xlsx` each produced a `.md` with non-trivial size (>200 chars); `.DS_Store` skipped |
| 3 | Extract docs | `extract-graph <docs> --session live-docs --obsidian-vault` | exit 0; `nodes.jsonl`/`edges.jsonl` non-empty; TTL parses via rdflib; `knowledge_graph_validation.json` valid; **no `failed_chunks.json`**; `obsidian_vault/` non-empty; `knowledge_graph.html` exists (the README's "open in browser" promise) |
| 4 | Extract web | `extract-graph <fetched> --session live-web` | exit 0; ≥1 node; TTL parses |
| 5 | Query | `query "Acme" --session live-docs` | exit 0; output starts `# Knowledge Graph Context:` |
| 6 | Walkthrough | `walkthrough --session live-docs` | exit 0; `walkthrough.md` non-empty |

**Deliberately loose.** Stage 3 checks the graph is *well-formed and complete*, not that
specific entities were found. The one content-shaped check — **no `failed_chunks.json`** —
is a genuine healthiness signal: it means no chunk silently failed to extract.

### Reporting — the actual deliverable

A session-scoped fixture collects each stage's outcome and prints a summary table at the
end, so one run tells you what's alive:

```
mykg healthiness — profile=openrouter-free

  ENDPOINTS        reach   contract
  openrouter       ok      ok        2 nodes, 1 edge
  gemini           ok      ok        2 nodes, 1 edge   (429 backoff x1, recovered)
  openai           FAIL    —         quota or balance exhausted (429)
                                     → top up, or switch profile
  anthropic        skip    —         no ANTHROPIC_API_KEY in .env.mykg
  ollama           skip    —         not running at localhost:11434

  CAPABILITIES     (profile=openrouter-free)
  fetch-web        ok        5 pages fetched
  parse-docs       ok        2 converted via MinerU
  extract (docs)   ok        31 nodes / 44 edges, TTL valid, 0 failed chunks
  extract (web)    ok        12 nodes
  query            ok
  walkthrough      ok

  3 of 5 endpoints healthy · all 6 capabilities healthy
```

A provider that is `reach ok` but `contract FAIL` is the interesting case — it is
reachable but would produce blank chunks in a real extraction.

#### Failures name their cause, not just "FAIL"

A bare `FAIL` is not actionable — the user needs to know whether to top up credits, fix a
key, or simply wait. Every failure is classified by HTTP status + message into a cause and
a suggested fix. **The signatures below were captured from the real API while planning,
not guessed:**

| Cause | Detected by | Reported as |
|---|---|---|
| **No key configured** | `ValueError` from adapter `__init__` (msg contains `is required`) | `skip — no GEMINI_API_KEY set` |
| **Invalid key** | `400` + `API key not valid` *(verified)* | `FAIL — api key rejected; check .env.mykg` |
| **Auth rejected** | `401` / `403` | `FAIL — authentication failed (401)` |
| **No credit / quota exhausted** | `429` + `RESOURCE_EXHAUSTED` / `quota` / `insufficient` / `billing` *(verified: `quotaValue: 5` free tier)* | `FAIL — quota or balance exhausted; top up or switch profile` |
| **Rate limited (cadence)** | `429` with a `retryDelay` and no quota wording | `WARN — rate limited; retried and recovered` |
| **Model not found** | `404` + `is not found for API version` *(verified)* | `FAIL — model 'X' not available on this key` |
| **Provider overloaded** | `503` / `UNAVAILABLE` *(verified on 3.7-flash)* | `WARN — provider busy (503); transient` |
| **Timeout** | `TimeoutError` / wall-clock | `FAIL — timed out after Ns` |
| **Bad response shape** | `json.loads` raises, or keys missing | `FAIL — returned unparseable/non-contract output` |
| **Model unreachable locally** | Ollama connection refused | `skip — ollama not running at localhost:11434` |

The README already documents the subtle case (line 292): **a `429` can mean either
request cadence *or* a depleted balance**, and the two need opposite responses. The report
separates them on message wording so the user is not told to lower `max_workers` when the
real problem is an empty account.

Classification lives in one small helper, `_classify_failure(exc) -> (cause, hint)`, so
capability stages (1–6) reuse the same vocabulary — a failed `extract-graph` reports
`quota exhausted` rather than a raw traceback.

Crucially, **a classified endpoint failure is reported, not raised**: one dead provider
must not abort the run, or you would never see the health of the rest. Stage 0 fails the
test only if *every* configured provider fails; individual results all appear in the
table. Capability stages still fail hard, since they run on one chosen profile.

### Markers

```toml
"live: marks tests that make real network/API calls (deselect with '-m not live')",   # exists
"mineru: exercises the MinerU ephemeral venv (multi-GB first run)",                   # new
```
Reuse the **existing `live` marker** rather than adding an `e2e` one — CI's `-m "not
live"` then excludes it automatically, no CI change and no secrets needed. The `mineru`
marker lets the fast legs run alone while iterating; MinerU otherwise runs for real (D48
ephemeral venv is normal mykg behaviour).

## Files

**New:** `tests/test_healthiness.py` (~250 lines)

**Modified:**
- `pyproject.toml` — one marker declaration (`mineru`)
- `tests/conftest.py` — generalize `_load_key` → `provider_key(name)`; add per-provider
  fixtures (gemini/anthropic/openai + an Ollama reachability probe) alongside the existing
  `openrouter_api_key`
- `README.md` — short "Healthiness check" note under Development

`_test_files/` is read-only; the test copies into `tmp_path`.

## Verification

```bash
# Just the endpoints — seconds
uv run pytest tests/test_healthiness.py -k endpoints -v --no-cov

# Everything except MinerU — the usual quick check
uv run pytest tests/test_healthiness.py -m "live and not mineru" -v --no-cov

# Full check including PDF/XLSX conversion
uv run pytest tests/test_healthiness.py -m live -v --no-cov

# Pin a provider
MYKG_E2E_PROFILE=gemini uv run pytest tests/test_healthiness.py -m live -v --no-cov

# Confirm it stays out of the normal suite (must remain 1358 passed)
uv run pytest tests/ -m "not live" -q --no-cov
```

`--no-cov` matters — `addopts` forces coverage on every run, pure overhead here.

**Runtime:** endpoints ~5 s; without MinerU ~3–5 min; +5–15 min on the first MinerU run
(venv build + model download), less afterwards.

**Expect on free tiers:** Gemini allows 5 req/min/model and OpenRouter free models are
similarly capped, so stages 3–4 log 429 backoff warnings. Adapters retry and recover —
documented behaviour (Invariant 13), not a failure. The generated config pins
`max_workers: 1–2`.

## Out of scope

- Entity-level extraction accuracy — this is a healthiness check; the unit suite covers
  correctness
- Adding to CI — no LLM secrets exist; would need a new scheduled workflow
- `merge-graphs`, `mcp-serve`, `--append`, `--grow-schema` — each already has dedicated
  coverage; this is the first-run journey

---

## Results from the first real runs

The check was exercised against live endpoints during implementation. What it found:

**Endpoints — 4 of 5 healthy.**

```
  ENDPOINTS         reach   contract
  openrouter-free   ok      ok        2 node(s), 1 edge(s)
  anthropic-claude  ok      ok        2 node(s), 1 edge(s)
  openai            ok      ok        2 node(s), 1 edge(s)
  gemini            FAIL    —         quota or balance exhausted → top up, or switch profile
  ollama-local      ok      ok        2 node(s), 1 edge(s)
```

**Capabilities.** `fetch-web` pulled 5 pages from aiportal.news. MinerU converted
`team.pdf` and `projects.xlsx`. A full `extract-graph` on `anthropic-claude` produced a
valid TTL with zero TBox/ABox errors and a populated Obsidian vault. Stages 3, 5 and 6
chained green in 2m42s:

```
  CAPABILITIES      status
  extract (docs)    ok      37 nodes / 47 edges, TTL valid, 0 failed chunks
  query             ok      matched
  walkthrough       ok      4577 bytes
```

`query ok matched` is notable: it found a real seed node in a graph the pipeline had
just produced — previously `mykg query` was only ever tested against hand-written
session fixtures. Node/edge counts vary run to run (37/47 here, 45/44 on an earlier
run); the check asserts the graph is well-formed, not that it is identical.

### Two real findings

1. **`openrouter-free` is too weak for Pass 2 on real documents.** It returned malformed
   JSON at ~8k characters, retried, and extracted **zero nodes** after ~15 minutes. The
   same corpus on `anthropic-claude` completed in 2m51s with 45 nodes. Its Pass 1 schema
   was also thinner (4 concepts / 6 properties vs 6 / 13). Worth reconsidering whether
   `openrouter-free` should stay the recommended default in `mykg init`.

2. **The README Quick Start points at a path that does not exist.** Line 128 says to open
   `mykg_sessions/<timestamp>/output/knowledge_graph.html`, but the viewer is written by
   `export_networkx()` and always lands in `output/networkx_output/knowledge_graph.html`.
   A user following the Quick Start hits a missing file. Not fixed here — flagged for a
   separate change, since it is a docs/product decision rather than a test concern.

Both were surfaced by the check rather than by the 1358-test unit suite, which is the
point of having it.

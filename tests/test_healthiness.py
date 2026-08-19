"""mykg healthiness check — a dry-run smoke test from the user's perspective.

Answers one question: *is everything alive and right?* Every LLM endpoint is
probed, then the major capabilities in the README are exercised end-to-end
through the real CLI, the way a user runs them.

This is a **healthiness check, not a correctness suite**. It asserts that each
moving part responds and produces well-formed output. It deliberately does not
assert entity-level extraction accuracy — the unit suite covers that, and an
LLM-driven pipeline is non-deterministic enough that strict content assertions
would fail for the wrong reasons.

Run with:

    # Just the endpoints — seconds
    uv run pytest tests/test_healthiness.py -k endpoints -v --no-cov

    # Everything except MinerU — the usual quick check
    uv run pytest tests/test_healthiness.py -m "live and not mineru" -v --no-cov

    # Full check including PDF/XLSX conversion
    uv run pytest tests/test_healthiness.py -m live -v --no-cov

    # Pin a provider for the capability stages
    MYKG_E2E_PROFILE=gemini uv run pytest tests/test_healthiness.py -m live -v --no-cov

`--no-cov` matters: addopts forces coverage on every run, which is pure overhead
here. Every test is marked `live`, so CI's existing `-m "not live"` excludes the
whole file automatically.

Known discrepancy this check surfaced: the README Quick Start says to open
`output/knowledge_graph.html`, but `export_networkx()` writes the viewer to
`output/networkx_output/knowledge_graph.html`. Both locations are accepted below
until that is reconciled.

Design notes and results from the first runs: docs/healthiness-check.md
"""

from __future__ import annotations

import json
import os
import shutil
import socket
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from tests.conftest import PROVIDER_KEY_VARS, provider_key, provider_key_var_label

pytestmark = pytest.mark.live

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_FILES = REPO_ROOT / "_test_files"

#: Profile used for the capability stages. Overridable so the same check can be
#: pointed at any endpoint.
DEFAULT_PROFILE = os.environ.get("MYKG_E2E_PROFILE", "openrouter-free")

#: The site to crawl in stage 1, and the caps the user asked for.
FETCH_URL = "https://aiportal.news"
FETCH_MAX_PAGES = 5
FETCH_MAX_DEPTH = 1

PROVIDERS = ["openrouter-free", "anthropic-claude", "openai", "gemini", "ollama-local"]


# ---------------------------------------------------------------------------
# Failure classification — a bare "FAIL" is not actionable
# ---------------------------------------------------------------------------


def _status_of(exc: BaseException) -> int | None:
    """Best-effort HTTP status from any provider SDK's exception."""
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    return None


def classify_failure(exc: BaseException) -> tuple[str, str]:
    """Map an exception to (cause, actionable hint).

    The signatures matched here were captured from real provider APIs. The
    subtle one is 429: it means *either* request cadence *or* a depleted
    balance, and those need opposite responses (README "Troubleshooting").
    """
    msg = str(exc)
    low = msg.lower()
    status = _status_of(exc)

    if isinstance(exc, ValueError) and "is required" in msg:
        return "no api key", "set the key in .env.mykg"
    if isinstance(exc, TimeoutError) or "timed out" in low or "timeout" in low:
        return "timeout", "provider did not respond in time; retry or raise llm.timeout"
    if status == 429 or "resource_exhausted" in low or "rate limit" in low:
        depleted = any(
            marker in low for marker in ("quota", "insufficient", "billing", "credit", "balance")
        )
        if depleted:
            return (
                "quota or balance exhausted",
                "top up the account, or switch to a profile with quota (ollama-local / claude-cli)",
            )
        return "rate limited", "lower pipeline max_workers, or wait and retry"
    if status in (401, 403) or "api key not valid" in low or "unauthorized" in low:
        return "authentication rejected", "check the key in .env.mykg"
    if status == 404 or "is not found for api version" in low or "no longer available" in low:
        return "model not available", "pick a different llm.model for this profile"
    if (status is not None and status >= 500) or (status is None and "unavailable" in low):
        return "provider unavailable", "transient provider-side error; retry"
    if isinstance(exc, json.JSONDecodeError):
        return "unparseable output", "model did not return JSON; try a stronger model"
    if isinstance(exc, (ConnectionError, socket.error)) or "connection" in low:
        return "unreachable", "check the endpoint is running and reachable"
    return f"{type(exc).__name__}", msg.strip().splitlines()[0][:120] if msg.strip() else ""


# ---------------------------------------------------------------------------
# Report — collected across the whole session, printed once at the end
# ---------------------------------------------------------------------------


@dataclass
class Report:
    endpoints: list[dict] = field(default_factory=list)
    capabilities: list[dict] = field(default_factory=list)

    def endpoint(self, name: str, reach: str, contract: str, detail: str = "") -> None:
        self.endpoints.append(
            {"name": name, "reach": reach, "contract": contract, "detail": detail}
        )

    def capability(self, name: str, status: str, detail: str = "") -> None:
        self.capabilities.append({"name": name, "status": status, "detail": detail})

    def render(self) -> str:
        lines = ["", "=" * 72, f"mykg healthiness — profile={DEFAULT_PROFILE}", "=" * 72, ""]
        if self.endpoints:
            lines.append(f"  {'ENDPOINTS':<18}{'reach':<8}{'contract':<10}")
            for row in self.endpoints:
                lines.append(
                    f"  {row['name']:<18}{row['reach']:<8}{row['contract']:<10}{row['detail']}"
                )
            healthy = sum(1 for r in self.endpoints if r["contract"] == "ok")
            lines += ["", f"  {healthy} of {len(self.endpoints)} endpoints healthy"]
        if self.capabilities:
            lines += ["", f"  {'CAPABILITIES':<18}{'status':<8}"]
            for row in self.capabilities:
                lines.append(f"  {row['name']:<18}{row['status']:<8}{row['detail']}")
            healthy = sum(1 for r in self.capabilities if r["status"] == "ok")
            lines += ["", f"  {healthy} of {len(self.capabilities)} capabilities healthy"]
        lines += ["", "=" * 72, ""]
        return "\n".join(lines)


@pytest.fixture(scope="module")
def docs_session() -> dict:
    """Carries the session stage 3 created to the stages that read it."""
    return {}


@pytest.fixture(scope="module")
def report(request):
    """Collects each stage's outcome; prints the summary once at the end.

    Written through pytest's terminal reporter rather than print(), so the table
    survives output capture — none of the documented commands pass -s, and the
    report is the whole point of this file.
    """
    rep = Report()
    yield rep
    terminal = request.config.pluginmanager.get_plugin("terminalreporter")
    if terminal is not None:
        terminal.write_line(rep.render())
    else:  # pragma: no cover — only when the terminal plugin is disabled
        print(rep.render())


# ---------------------------------------------------------------------------
# Stage 0 — endpoint healthiness
# ---------------------------------------------------------------------------

#: The real Pass 2 output contract, shrunk to one sentence. A provider that
#: cannot satisfy this would produce blank chunks in a real run (D33).
_CONTRACT_SYSTEM = (
    "You extract knowledge graphs. Return ONLY JSON, no prose:\n"
    '{"nodes":[{"id":"<slug>","type":"<Concept>",'
    '"attributes":{"name":{"value":"<text>","confidence":<0.0-1.0>}}}],'
    '"edges":[{"type":"<property>","from":"<node id>","to":"<node id>",'
    '"confidence":<0.0-1.0>,"attributes":{}}]}\n'
    "Concepts: Person(name), Organization(name). "
    "Properties: works_at(domain=Person, range=Organization).\n"
    'Every attribute value MUST be wrapped as {"value": ..., "confidence": <float>}.'
)
_CONTRACT_USER = "Alice Chen is an engineer at Acme Corp."


def _build_adapter(profile: str, api_key: str | None):
    """Construct the profile's adapter directly from the shipped config.

    Reads the real mykg_config.yaml profile so the check exercises the same
    model/base_url/timeout a user would get, rather than a test-only stand-in.
    """
    raw = yaml.safe_load((REPO_ROOT / "mykg_config.yaml").read_text(encoding="utf-8"))
    section = dict(raw["profiles"][profile]["llm"])
    # Deliberately NOT clamping max_output_tokens: on thinking models (Gemini 3.x)
    # reasoning tokens are drawn from the same budget as the answer, so a small cap
    # returns an empty body and would report a healthy endpoint as broken.
    section["timeout"] = 120
    if api_key:
        section["api_key"] = api_key

    from mykg.llm.config import load_adapter

    return load_adapter(_raw={"provider": raw["profiles"][profile]["provider"], "llm": section})


def _ollama_running() -> bool:
    try:
        with socket.create_connection(("localhost", 11434), timeout=2):
            return True
    except OSError:
        return False


def _assert_contract(payload: dict) -> tuple[int, int]:
    """Assert the Pass 2 response shape the pipeline depends on."""
    assert isinstance(payload, dict), f"expected a JSON object, got {type(payload).__name__}"
    assert "nodes" in payload, f"response has no 'nodes' key: {sorted(payload)[:6]}"
    assert "edges" in payload, f"response has no 'edges' key: {sorted(payload)[:6]}"
    nodes = payload["nodes"]
    assert isinstance(nodes, list) and nodes, "nodes[] is empty — nothing was extracted"

    for node in nodes:
        assert node.get("id"), f"node missing id: {node}"
        assert node.get("type"), f"node missing type: {node}"
        for attr_name, attr in (node.get("attributes") or {}).items():
            assert isinstance(attr, dict), (
                f"attribute {attr_name!r} is a bare value {attr!r}; "
                "the pipeline requires {'value': ..., 'confidence': ...}"
            )
            assert "value" in attr and "confidence" in attr, (
                f"attribute {attr_name!r} is not confidence-wrapped: {attr}"
            )
    return len(nodes), len(payload["edges"])


@pytest.mark.parametrize("profile", PROVIDERS)
def test_endpoints_healthy(profile, report):
    """Each configured LLM endpoint is reachable AND can satisfy mykg's contract.

    Reachability alone is a weak signal — a provider can answer "PONG" and still
    fail every real pipeline call. So this runs two checks and reports each
    provider independently: one dead endpoint must not hide the health of the
    rest.
    """
    if profile == "ollama-local":
        if not _ollama_running():
            report.endpoint(profile, "skip", "—", "not running at localhost:11434")
            pytest.skip("ollama not running at localhost:11434")
        api_key = None
    else:
        api_key = provider_key(profile)
        if not api_key:
            label = provider_key_var_label(profile)
            report.endpoint(profile, "skip", "—", f"no {label} in .env.mykg")
            pytest.skip(f"{label} not set")

    # 0a — reachable
    try:
        adapter = _build_adapter(profile, api_key)
        pong = adapter.complete("Reply with the single word PONG.", "PING")
    except Exception as exc:  # noqa: BLE001 — classified and reported, not swallowed
        cause, hint = classify_failure(exc)
        report.endpoint(profile, "FAIL", "—", f"{cause} → {hint}")
        pytest.fail(f"{profile}: unreachable — {cause}. {hint}")

    if not pong.strip():
        report.endpoint(profile, "FAIL", "—", "empty response to PING")
        pytest.fail(f"{profile}: returned an empty response")

    # 0b — can do mykg's actual job
    try:
        raw = adapter.complete(_CONTRACT_SYSTEM, _CONTRACT_USER, context_label="healthiness")
        payload = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 — classified and reported, not swallowed
        cause, hint = classify_failure(exc)
        report.endpoint(profile, "ok", "FAIL", f"{cause} → {hint}")
        pytest.fail(f"{profile}: cannot satisfy the extraction contract — {cause}. {hint}")

    # Shape violations are assertions, not provider errors — let them surface with
    # their own diagnostic rather than being relabelled by classify_failure.
    try:
        n_nodes, n_edges = _assert_contract(payload)
    except AssertionError as exc:
        report.endpoint(profile, "ok", "FAIL", f"bad response shape → {exc}")
        raise

    report.endpoint(profile, "ok", "ok", f"{n_nodes} node(s), {n_edges} edge(s)")


# ---------------------------------------------------------------------------
# Capability stages — driven through the real CLI
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workspace(tmp_path_factory):
    """An isolated working directory with a real mykg_config.yaml.

    config._find_config() walks upward from cwd, so without this the CLI would
    load the repo's own config. The shipped profile is copied and only the
    cost/cadence knobs are trimmed, so the check exercises a config a user
    would actually have.
    """
    root = tmp_path_factory.mktemp("healthiness")
    raw = yaml.safe_load((REPO_ROOT / "mykg_config.yaml").read_text(encoding="utf-8"))

    if DEFAULT_PROFILE not in raw["profiles"]:
        pytest.skip(f"profile {DEFAULT_PROFILE!r} not in mykg_config.yaml")

    raw["profile"] = DEFAULT_PROFILE
    profile = raw["profiles"][DEFAULT_PROFILE]
    profile["llm"]["max_output_tokens"] = 8000
    pipeline = profile["pipeline"]
    # Serial: free tiers cap requests per minute (Invariant 13).
    for section in ("pass1", "pass2", "orphan_pass", "ingest"):
        if section in pipeline and "max_workers" in pipeline[section]:
            pipeline[section]["max_workers"] = 1
    pipeline["paths"]["sessions_dir"] = "mykg_sessions"

    (root / "mykg_config.yaml").write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return root


@pytest.fixture(scope="module")
def cli_env(workspace):
    """Run the CLI from the isolated workspace with the provider key present."""
    key = provider_key(DEFAULT_PROFILE)
    if not key and DEFAULT_PROFILE != "ollama-local":
        pytest.skip(f"{provider_key_var_label(DEFAULT_PROFILE)} not set")

    prev_cwd = Path.cwd()
    tracked = (
        "MYKG_PROFILE_OVERRIDE",
        "MYKG_MODEL_OVERRIDE",
        *PROVIDER_KEY_VARS.get(DEFAULT_PROFILE, ()),
    )
    prev_env = {k: os.environ.get(k) for k in tracked}
    # config._find_config() walks upward from cwd, so chdir is what actually
    # selects the isolated config. Assigning to mykg.config attributes does NOT
    # work here: cli._cfg() re-imports the module on every call and would
    # discard them. The profile is instead selected via --profile, which routes
    # through activate_profile() and reloads config correctly.
    os.chdir(workspace)
    if key:
        for var in PROVIDER_KEY_VARS.get(DEFAULT_PROFILE, ()):
            os.environ.setdefault(var, key)
    try:
        yield workspace
    finally:
        os.chdir(prev_cwd)
        for var, value in prev_env.items():
            if value is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = value


def _invoke(args: list[str]) -> tuple[int, str]:
    """Run a CLI command; return (exit_code, combined output).

    Click swallows exceptions into result.exception, so both are joined —
    otherwise a failure shows as a bare non-zero exit with no explanation.
    """
    from mykg.cli import cli

    result = CliRunner().invoke(cli, args, catch_exceptions=True)
    output = (result.output or "") + ("\n" + str(result.exception) if result.exception else "")
    return result.exit_code, output


def _read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _assert_graph_healthy(session: Path, label: str) -> tuple[int, int]:
    """Shared assertions: the graph is complete and well-formed."""
    from rdflib import Graph

    nodes_path = session / "output" / "nodes.jsonl"
    edges_path = session / "output" / "edges.jsonl"
    assert nodes_path.exists(), f"{label}: no nodes.jsonl"
    assert edges_path.exists(), f"{label}: no edges.jsonl"

    nodes = _read_jsonl(nodes_path)
    edges = _read_jsonl(edges_path)
    assert nodes, f"{label}: extracted zero nodes"

    ttl = session / "output" / "knowledge_graph.ttl"
    assert ttl.exists(), f"{label}: no knowledge_graph.ttl"
    Graph().parse(data=ttl.read_text(encoding="utf-8"), format="turtle")  # raises if invalid

    validation = session / "output" / "knowledge_graph_validation.json"
    if validation.exists():
        assert json.loads(validation.read_text(encoding="utf-8")).get("valid") is True, (
            f"{label}: knowledge_graph_validation.json reports the graph invalid"
        )

    # A chunk that silently failed to extract is the classic invisible breakage.
    # pass2.py writes failed_chunks.json unconditionally (even as []) in some prep
    # modes, so assert on its *contents*, not its existence.
    failed = session / "intermediate" / "failed_chunks.json"
    if failed.exists():
        entries = json.loads(failed.read_text(encoding="utf-8"))
        assert not entries, (
            f"{label}: {len(entries)} chunk(s) failed to extract — "
            "see intermediate/failed_chunks.json"
        )
    return len(nodes), len(edges)


def _latest_session(workspace: Path) -> Path:
    """Newest session under mykg_sessions/.

    `extract-graph --session NAME` *selects an existing* session; a fresh run
    creates its own UTC-timestamped one. Names sort lexicographically ==
    chronologically, so the last one is the newest.
    """
    root = workspace / "mykg_sessions"
    assert root.exists(), "no mykg_sessions/ directory was created"
    sessions = sorted(d for d in root.iterdir() if d.is_dir())
    assert sessions, "extract-graph created no session directory"
    return sessions[-1]


def test_fetch_web_healthy(cli_env, report):
    """Stage 1 — crawling a real site produces an extract-graph-ready folder."""
    out = cli_env / "fetched"
    code, output = _invoke(
        [
            "fetch-web",
            FETCH_URL,
            "--output",
            str(out),
            "--max-pages",
            str(FETCH_MAX_PAGES),
            "--max-depth",
            str(FETCH_MAX_DEPTH),
            "--strategy",
            "same-domain",
        ]
    )
    if code != 0:
        report.capability("fetch-web", "FAIL", output.strip().splitlines()[-1][:90])
        pytest.fail(f"fetch-web exited {code}:\n{output}")

    manifest_path = out / "fetch_manifest.json"
    assert manifest_path.exists(), f"no fetch_manifest.json in {out}"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    html_files = list(out.rglob("*.html"))
    assert html_files, "crawl produced no HTML files"
    # --max-pages maps to Crawlee's max_requests_per_crawl, and its concurrency
    # can let a few in-flight requests land after the cap trips. Assert the cap
    # is honoured in spirit — the point is that it bounds the crawl, not that it
    # is exact to the page.
    assert len(html_files) <= FETCH_MAX_PAGES * 2, (
        f"--max-pages {FETCH_MAX_PAGES} did not bound the crawl: got {len(html_files)} files"
    )
    for url in manifest.get("pages") or {}:
        assert "aiportal.news" in url, f"same-domain strategy leaked off-site: {url}"

    report.capability("fetch-web", "ok", f"{len(html_files)} page(s) fetched")


@pytest.mark.mineru
def test_parse_docs_healthy(cli_env, report):
    """Stage 2 — MinerU turns the PDF and spreadsheet into readable Markdown."""
    out = cli_env / "converted"
    code, output = _invoke(["parse-docs", "--input", str(TEST_FILES), "--output", str(out)])
    if code != 0:
        report.capability("parse-docs", "FAIL", output.strip().splitlines()[-1][:90])
        pytest.fail(f"parse-docs exited {code}:\n{output}")

    produced = {p.stem: p for p in out.rglob("*.md")}
    for stem in ("team", "projects"):
        assert stem in produced, f"{stem} was not converted; got {sorted(produced)}"
        size = produced[stem].stat().st_size
        assert size > 200, f"{stem}.md is only {size} bytes — conversion produced no content"

    assert not list(out.rglob(".DS_Store")), ".DS_Store should be skipped, not converted"
    report.capability("parse-docs", "ok", f"{len(produced)} file(s) converted via MinerU")


def test_extract_documents_healthy(cli_env, report, docs_session):
    """Stage 3 — the core promise: a directory of documents becomes a graph."""
    corpus = cli_env / "docs"
    corpus.mkdir(exist_ok=True)
    for src in TEST_FILES.iterdir():
        if src.is_file() and not src.name.startswith("."):
            shutil.copy2(src, corpus / src.name)

    code, output = _invoke(
        [
            "extract-graph",
            str(corpus),
            "--profile",
            DEFAULT_PROFILE,
            "--obsidian-vault",
        ]
    )
    if code != 0:
        report.capability("extract (docs)", "FAIL", output.strip().splitlines()[-1][:90])
        pytest.fail(f"extract-graph exited {code}:\n{output}")

    session = _latest_session(cli_env)
    docs_session["path"] = session
    docs_session["name"] = session.name
    n_nodes, n_edges = _assert_graph_healthy(session, "docs")

    vault = session / "output" / "obsidian_vault"
    assert vault.exists() and list(vault.rglob("*.md")), "obsidian vault is empty"
    # The interactive viewer is written by export_networkx(), so it lands in
    # output/networkx_output/. (The README Quick Start points at output/ — see
    # the note in this file's docstring.) Accept either location.
    viewer = [
        session / "output" / "knowledge_graph.html",
        session / "output" / "networkx_output" / "knowledge_graph.html",
    ]
    assert any(path.exists() for path in viewer), (
        "no knowledge_graph.html — the README tells users to open this in a browser"
    )

    report.capability(
        "extract (docs)", "ok", f"{n_nodes} nodes / {n_edges} edges, TTL valid, 0 failed chunks"
    )


def test_extract_website_healthy(cli_env, report, docs_session):
    """Stage 4 — the fetched site becomes a graph too."""
    fetched = cli_env / "fetched"
    if not fetched.exists() or not list(fetched.rglob("*.html")):
        pytest.skip("stage 1 (fetch-web) did not produce input")

    code, output = _invoke(["extract-graph", str(fetched), "--profile", DEFAULT_PROFILE])
    if code != 0:
        report.capability("extract (web)", "FAIL", output.strip().splitlines()[-1][:90])
        pytest.fail(f"extract-graph exited {code}:\n{output}")

    session = _latest_session(cli_env)
    # Guard against re-validating stage 3's graph if this run created no session.
    if docs_session.get("name") and session.name == docs_session["name"]:
        report.capability("extract (web)", "FAIL", "no new session was created")
        pytest.fail("extract-graph (web) did not create its own session")
    n_nodes, n_edges = _assert_graph_healthy(session, "web")
    report.capability("extract (web)", "ok", f"{n_nodes} nodes / {n_edges} edges")


def test_query_healthy(cli_env, report, docs_session):
    """Stage 5 — the graph built in stage 3 can actually be queried."""
    session = docs_session.get("path")
    if session is None or not (session / "output" / "nodes.jsonl").exists():
        pytest.skip("stage 3 (extract docs) did not produce a graph")

    code, output = _invoke(["query", "Acme", "--session", docs_session["name"]])
    if code != 0:
        report.capability("query", "FAIL", output.strip().splitlines()[-1][:90])
        pytest.fail(f"query exited {code}:\n{output}")

    # Either shape is a healthy answer: a context block, or an explicit no-match.
    # Asserting a hit would be a content assertion, which this check avoids —
    # whether "Acme" was extracted as a node name is up to the LLM.
    matched = output.startswith("# Knowledge Graph Context:")
    no_match = "No nodes found matching" in output
    assert matched or no_match, f"unexpected query output shape: {output[:150]!r}"
    report.capability("query", "ok", "matched" if matched else "ran (no seed match)")


def test_walkthrough_healthy(cli_env, report, docs_session):
    """Stage 6 — the run explains itself in a readable report."""
    session = docs_session.get("path")
    if session is None or not (session / "output" / "nodes.jsonl").exists():
        pytest.skip("stage 3 (extract docs) did not produce a graph")

    code, output = _invoke(["walkthrough", "--session", docs_session["name"]])
    if code != 0:
        report.capability("walkthrough", "FAIL", output.strip().splitlines()[-1][:90])
        pytest.fail(f"walkthrough exited {code}:\n{output}")

    report_path = session / "walkthrough.md"
    assert report_path.exists(), "walkthrough.md was not written"
    assert report_path.stat().st_size > 200, "walkthrough.md is suspiciously small"
    report.capability("walkthrough", "ok", f"{report_path.stat().st_size} bytes")

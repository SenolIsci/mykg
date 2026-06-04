"""CLI: emit plain-header CSVs + Cypher scripts for `LOAD CSV` import.

Usage:
    python -m mykg.exporters.neo4j.emit_load_csv \\
        --session <session-name> \\
        [--sessions-root sessions] \\
        --out <output-dir>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ._common import load_session
from .load_csv import (
    build_browser_cypher,
    build_plain_csvs,
    build_readme,
    build_shell_cypher,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m mykg.exporters.neo4j.emit_load_csv",
        description="Emit plain-header CSVs + Cypher scripts for Neo4j LOAD CSV import.",
    )
    parser.add_argument("--session", required=True, help="Session name (directory under --sessions-root)")
    parser.add_argument("--sessions-root", default="sessions", help="Parent directory of sessions (default: sessions)")
    parser.add_argument("--out", required=True, help="Directory to write CSVs and Cypher scripts into")
    return parser.parse_args(argv)


def _print_recipe(out_dir: Path, csv_count: int) -> None:
    print(f"\nWrote {csv_count} CSVs + 2 Cypher scripts + README to {out_dir}\n")
    print("Flow A — Neo4j Browser:")
    print(f"  1. Copy {out_dir}/*.csv into <your-DBMS-home>/import/")
    print(f"  2. Open Neo4j Browser, paste the contents of {out_dir / 'import_browser.cypher'}, press play")
    print()
    print("Flow B — cypher-shell:")
    print(f"  cypher-shell -u neo4j -p <pw> -f {out_dir / 'import_shell.cypher'}")
    print("  (one-time setup: set dbms.security.allow_csv_import_from_file_urls=true in neo4j.conf and restart)")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    session_root = Path(args.sessions_root) / args.session
    out_dir = Path(args.out).absolute()
    out_dir.mkdir(parents=True, exist_ok=True)

    nodes, edges, schema = load_session(session_root)
    csvs = build_plain_csvs(nodes, edges, schema)

    for rel_path, content in csvs.items():
        (out_dir / rel_path.name).write_text(content)

    (out_dir / "import_browser.cypher").write_text(build_browser_cypher(csvs))
    (out_dir / "import_shell.cypher").write_text(build_shell_cypher(csvs, out_dir))
    (out_dir / "README.md").write_text(build_readme(out_dir, list(csvs.keys())))

    _print_recipe(out_dir, len(csvs))
    return 0


if __name__ == "__main__":
    sys.exit(main())

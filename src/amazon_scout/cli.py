from __future__ import annotations

import argparse
import os
from pathlib import Path

from .database import ScoutDatabase
from .pipeline import run_mock


def main() -> int:
    parser = argparse.ArgumentParser(description="Amazon UAE deterministic product research analytics")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init-db")
    init.add_argument("--database", default="data/scout.db")
    score = sub.add_parser("research")
    score.add_argument("--fixture", default="tests/fixtures/mock_research.json")
    args = parser.parse_args()
    if args.command == "init-db":
        ScoutDatabase(args.database).initialize()
        print(f"Initialized {args.database}")
        return 0
    mode = os.getenv("SCOUT_MODE", "mock")
    credentials = all(os.getenv(k) for k in ("SP_API_CLIENT_ID", "SP_API_CLIENT_SECRET", "SP_API_REFRESH_TOKEN"))
    if mode == "live":
        if not credentials:
            print("Live mode requested but credentials are incomplete; no API call made.")
            return 2
        print("Live collection is orchestrated by Codex through the configured Amazon MCP; normalize its read-only responses, then run deterministic analytics. No direct SP-API client is bundled.")
        return 0
    if mode == "research":
        print("Research mode is orchestrated by Codex live web search. Create a schema-valid evidence bundle, then run scripts/ingest-research <file>.")
        return 0
    markdown, json_path = run_mock(args.fixture)
    print(f"Created {markdown} and {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

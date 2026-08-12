#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if ! command -v node >/dev/null 2>&1; then
  echo "Error: Node.js 20+ is required." >&2; exit 1
fi
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
if [ "$NODE_MAJOR" -lt 20 ]; then
  echo "Error: Node.js 20+ is required (found major version $NODE_MAJOR)." >&2; exit 1
fi
if ! command -v codex >/dev/null 2>&1; then
  echo "Error: codex is not installed or not on PATH." >&2; exit 1
fi

# Parse only KEY=VALUE credential lines; never execute .env as shell code.
if [ -f .env ]; then
  while IFS='=' read -r key value; do
    key="${key%$'\r'}"; value="${value%$'\r'}"
    case "$key" in
      SP_API_CLIENT_ID|SP_API_CLIENT_SECRET|SP_API_REFRESH_TOKEN|SCOUT_MODE|SERPAPI_API_KEY|DATAFORSEO_LOGIN|DATAFORSEO_PASSWORD|RAINFOREST_API_KEY|RESEARCH_ALLOW_PAID_PROVIDERS|RESEARCH_MAX_PAID_CALLS|RESEARCH_MAX_COST_USD|SERPAPI_CACHE_TTL_HOURS)
        if [[ "$value" == \"*\" ]] || [[ "$value" == \'*\' ]]; then value="${value:1:${#value}-2}"; fi
        export "$key=$value"
        ;;
      ""|\#*) ;;
      *) echo "Warning: ignored unsupported key in .env: $key" >&2 ;;
    esac
  done < .env
fi

missing=()
for key in SP_API_CLIENT_ID SP_API_CLIENT_SECRET SP_API_REFRESH_TOKEN; do
  if [ -z "${!key:-}" ]; then missing+=("$key"); fi
done
if [ -z "${SCOUT_MODE:-}" ]; then
  if [ "${#missing[@]}" -eq 0 ]; then export SCOUT_MODE=live; else export SCOUT_MODE=research; fi
fi
case "$SCOUT_MODE" in mock|research|live) ;; *) echo "Error: SCOUT_MODE must be mock, research, or live." >&2; exit 1;; esac
if [ "${#missing[@]}" -gt 0 ]; then
  if [ "$SCOUT_MODE" = "live" ]; then
    echo "Error: live mode requires: ${missing[*]}" >&2; exit 1
  fi
  [ "$SCOUT_MODE" = "research" ] && echo "Amazon credentials are incomplete; launching research mode with live web search." >&2
fi

# The project config already fixes web_search="live"; the CLI override makes
# research/live intent explicit and survives user-level cached-search defaults.
if [ "$SCOUT_MODE" = "research" ] || [ "$SCOUT_MODE" = "live" ]; then
  exec codex -c 'web_search="live"' "$@"
fi
exec codex "$@"

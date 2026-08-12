#!/usr/bin/env bash
set -uo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
failures=0
ok() { printf 'OK: %s\n' "$1"; }
bad() { printf 'FAIL: %s\n' "$1" >&2; failures=$((failures + 1)); }

command -v codex >/dev/null 2>&1 && ok "Codex installed ($(codex --version 2>/dev/null))" || bad "Codex is missing"
if command -v node >/dev/null 2>&1; then
  major="$(node -p 'process.versions.node.split(".")[0]')"
  [ "$major" -ge 20 ] && ok "Node.js $(node --version)" || bad "Node.js 20+ required"
else bad "Node.js is missing"; fi
command -v npx >/dev/null 2>&1 && ok "npx installed" || bad "npx is missing"
command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; raise SystemExit(sys.version_info < (3,11))' && ok "Python $(python3 --version 2>&1)" || bad "Python 3.11+ required"
[ -f .codex/config.toml ] && python3 -c 'import tomllib; tomllib.load(open(".codex/config.toml", "rb"))' && ok ".codex/config.toml parses" || bad ".codex/config.toml missing or invalid"
for path in config data reports research/raw research/normalized research/evidence.schema.json src/amazon_scout src/amazon_scout/sources scripts tests .agents/skills/amazon-uae-research; do [ -e "$path" ] && ok "Found $path" || bad "Missing $path"; done
[ "$(python3 -c 'import tomllib; print(tomllib.load(open(".codex/config.toml","rb")).get("web_search"))')" = "live" ] && ok "Codex web search configured live" || bad "Codex web search is not live"

missing=()
for key in SP_API_CLIENT_ID SP_API_CLIENT_SECRET SP_API_REFRESH_TOKEN; do [ -n "${!key:-}" ] || missing+=("$key"); done
if [ "${#missing[@]}" -eq 0 ]; then ok "Amazon credential variables are present (values hidden)"; else printf 'INFO: research mode is ready; missing optional SP-API variables: %s (values never shown)\n' "${missing[*]}"; fi

if [ "${SCOUT_CHECK_MCP_PACKAGE:-0}" = "1" ]; then
  # Startup smoke test: MCP servers are long-running, so a short timeout/signal is success.
  python3 - "$@" <<'PY'
import subprocess, sys
commands = [
    ["npx", "-y", "@amazon-sp-api-release/sp-api-dev-mcp", "sp-api-dev-assistant-mcp-server"],
    ["npx", "-y", "@amazon-sp-api-release/sp-api-dev-mcp", "sp-api-workflow-mcp-server"],
]
for command in commands:
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=8, text=True)
        if result.returncode != 0:
            print(f"FAIL: {' '.join(command[-1:])} exited {result.returncode}: {result.stderr[:240]}", file=sys.stderr)
            sys.exit(1)
        print(f"OK: {command[-1]} startup command completed")
    except subprocess.TimeoutExpired:
        print(f"OK: {command[-1]} stayed running until smoke-test timeout")
PY
  [ "$?" -eq 0 ] && ok "Amazon MCP package startup smoke test" || bad "Amazon MCP package startup failed"
else
  printf 'INFO: MCP package startup not downloaded/tested. Run SCOUT_CHECK_MCP_PACKAGE=1 ./scripts/check-setup.sh when network access is available.\n'
fi

if command -v codex >/dev/null 2>&1; then
  listing="$(codex mcp list 2>/dev/null || true)"
  if printf '%s' "$listing" | grep -q 'sp-api-dev-assistant' && printf '%s' "$listing" | grep -q 'sp-api-workflow'; then ok "Codex detects both project MCP servers"; else printf 'INFO: Codex did not list both servers yet; restart Codex and trust this project, then run /mcp.\n'; fi
fi
exit "$failures"

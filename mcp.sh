#!/usr/bin/env bash
# audiobooklm MCP (HTTP Streamable) helper
# Usage:
#   mcp.sh list
#   mcp.sh call <tool_name> '<json_params_string>'
set -uo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SKILL_DIR/.env"

URL="${AUDIOBOOKLM_MCP_URL}"
TOKEN="${AUDIOBOOKLM_TOKEN}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- 1. initialize ---
curl -sS -D "$TMP/init.h" -o "$TMP/init.b" -X POST "$URL" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"workbuddy","version":"1.0.0"}}}'

SID="$(grep -i '^mcp-session-id:' "$TMP/init.h" | head -1 | cut -d: -f2- | tr -d '\r' | sed 's/^ *//')"

if [ -z "$SID" ]; then
  echo "INIT_FAILED: no mcp-session-id returned"
  echo "--- headers ---"; cat "$TMP/init.h"
  echo "--- body ---"; cat "$TMP/init.b"
  exit 1
fi

# --- 2. notifications/initialized ---
curl -sS -o /dev/null -X POST "$URL" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "mcp-session-id: $SID" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'

MODE="${1:-list}"

if [ "$MODE" = "list" ]; then
  PAYLOAD='{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
else
  TOOL="$2"
  PARAMS="${3:-{}}"
  PAYLOAD="$(printf '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"%s","arguments":%s}}' "$TOOL" "$PARAMS")"
fi

# --- 3. request ---
curl -sS -D "$TMP/call.h" -o "$TMP/call.b" -X POST "$URL" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "mcp-session-id: $SID" \
  -d "$PAYLOAD"

echo "=== HTTP STATUS ==="
head -1 "$TMP/call.h"
echo "=== BODY ==="
cat "$TMP/call.b"
echo ""

#!/usr/bin/env python3
"""audiobooklm MCP (HTTP Streamable) client.

Usage:
  python mcp_client.py list
  python mcp_client.py call <tool_name> '<json_params>'
  python mcp_client.py call <tool_name> @params.json
"""
import json
import os
import sys
import urllib.request
import urllib.error

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(SKILL_DIR, ".env")


def load_env(path):
    cfg = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


CFG = load_env(ENV_PATH)
URL = CFG.get("AUDIOBOOKLM_MCP_URL", "https://aigc.ximalaya.com/audiobooklm/mcp")
TOKEN = CFG.get("AUDIOBOOKLM_TOKEN", "")

SESSION = None


def post(payload, rid=1):
    global SESSION
    headers = {
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }
    if SESSION:
        headers["mcp-session-id"] = SESSION
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(URL, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=300) as resp:
        sid = resp.headers.get("mcp-session-id")
        if sid:
            SESSION = sid
        raw = resp.read().decode("utf-8", errors="replace")
    return raw


def parse_sse(raw):
    """Return the last JSON-RPC payload found in SSE text."""
    objs = []
    buf = ""
    for line in raw.splitlines():
        if line.startswith("data:"):
            buf = line[5:].strip()
        elif buf:
            try:
                objs.append(json.loads(buf))
            except Exception:
                pass
            buf = ""
    if buf:
        try:
            objs.append(json.loads(buf))
        except Exception:
            pass
    if not objs:
        try:
            objs.append(json.loads(raw))
        except Exception:
            pass
    return objs[-1] if objs else None


def handshake():
    post({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "workbuddy", "version": "1.0.0"},
        },
    }, rid=1)
    # notification: no response expected, errors are non-fatal
    try:
        post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    except Exception:
        pass


def main():
    if not TOKEN:
        print("ERROR: AUDIOBOOKLM_TOKEN not configured")
        sys.exit(1)

    mode = sys.argv[1] if len(sys.argv) > 1 else "list"
    handshake()

    if mode == "list":
        payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    elif mode == "call":
        tool = sys.argv[2]
        arg = sys.argv[3] if len(sys.argv) > 3 else "{}"
        if arg.startswith("@"):
            with open(arg[1:], "r", encoding="utf-8") as f:
                params = json.load(f)
        else:
            params = json.loads(arg)
        payload = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                   "params": {"name": tool, "arguments": params}}
    else:
        print("ERROR: unknown mode")
        sys.exit(1)

    raw = post(payload)
    obj = parse_sse(raw)

    if obj is None:
        print("RAW_RESPONSE:")
        print(raw[:4000])
        sys.exit(2)

    if "error" in obj:
        print("JSONRPC_ERROR:", json.dumps(obj["error"], ensure_ascii=False))
        sys.exit(3)

    res = obj.get("result", {})
    if mode == "list":
        tools = res.get("tools", [])
        print("TOOL_COUNT:", len(tools))
        for t in tools:
            print("-", t["name"])
        with open(os.path.join(SKILL_DIR, "tools_cache.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        return

    # tools/call
    content = res.get("content", [])
    out = []
    for c in content:
        if c.get("type") == "text":
            out.append(c.get("text", ""))
        else:
            out.append(json.dumps(c, ensure_ascii=False))
    text = "\n".join(out)
    print(text if text else json.dumps(res, ensure_ascii=False, indent=2))
    if res.get("isError"):
        sys.exit(4)


if __name__ == "__main__":
    main()

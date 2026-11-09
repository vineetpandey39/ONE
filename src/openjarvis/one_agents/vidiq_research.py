"""Bounded, read-only vidIQ MCP research; never generates media or edits videos.

The hosted endpoint accepts stateless JSON-RPC requests. Read an SSE response
until the matching RPC result, not until the persistent event stream closes.
Credentials stay in ONE's local vault; receipts contain only research data.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import jsonschema

from openjarvis.core.credentials import load_credentials
from openjarvis.core.paths import get_config_dir

ENDPOINT = "https://mcp.vidiq.com/mcp"
FREE = {"vidiq_balance", "vidiq_user_channels"}
ALLOWED = FREE | {"vidiq_keyword_research", "vidiq_outliers", "vidiq_trending_videos"}
DAILY_CALL_LIMIT = 8  # Shared across jobs and fallback models, including failed attempts.


class ResearchUnavailable(RuntimeError):
    pass


def rpc(method: str, params: dict) -> dict:
    token = load_credentials().get("custom", {}).get("VIDIQ_API_KEY", "")
    if not token.startswith("vidiq") or any(c.isspace() for c in token):
        raise ResearchUnavailable("vidIQ read-only key is not configured in ONE vault")
    request_id = "one-research"
    try:
        with httpx.Client(timeout=35, follow_redirects=False) as client:
            with client.stream("POST", ENDPOINT, headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/json, text/event-stream",
            }, json={"jsonrpc": "2.0", "id": request_id,
                     "method": method, "params": params}) as response:
                response.raise_for_status()
                if "text/event-stream" in response.headers.get("content-type", ""):
                    result = None
                    for line in response.iter_lines():
                        if line.startswith("data:"):
                            candidate = json.loads(line[5:].strip())
                            if candidate.get("id") == request_id:
                                result = candidate
                                break
                    if result is None:
                        raise ResearchUnavailable("vidIQ returned no matching MCP result")
                else:
                    result = json.loads(response.read())
    except (httpx.HTTPError, ValueError) as exc:
        # Exception bodies/headers must not leak the credential to job logs.
        raise ResearchUnavailable(f"vidIQ MCP transport failed: {type(exc).__name__}") from None
    if result.get("error"):
        raise ResearchUnavailable("vidIQ MCP returned an RPC error")
    return result.get("result", {})


class ResearchClient:
    def __init__(self, root: Path | None = None, call_rpc=None):
        self.root = root or get_config_dir() / "vidiq_research"
        self.root.mkdir(parents=True, exist_ok=True)
        self.rpc = call_rpc or rpc
        self.catalog = {t["name"]: t for t in self.rpc("tools/list", {}).get("tools", [])}
        self.db = self.root / "calls.sqlite3"
        with sqlite3.connect(self.db) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS calls (day TEXT, digest TEXT, name TEXT, result TEXT, PRIMARY KEY(day,digest))")

    def call(self, name: str, arguments: dict) -> dict:
        if name not in ALLOWED or name not in self.catalog:
            raise ResearchUnavailable("Tool is not approved for daily research")
        jsonschema.validate(arguments, self.catalog[name]["inputSchema"])
        day = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        digest = hashlib.sha256(json.dumps([name, arguments], sort_keys=True).encode()).hexdigest()
        with sqlite3.connect(self.db, timeout=10) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT result FROM calls WHERE day=? AND digest=?", (day,digest)).fetchone()
            if row:
                if row[0]:
                    return json.loads(row[0])
                raise ResearchUnavailable("Identical vidIQ call is pending or failed; no automatic paid retry")
            used = conn.execute("SELECT count(*) FROM calls WHERE day=? AND name NOT IN (?,?)", (day,*sorted(FREE))).fetchone()[0]
            if name not in FREE and used >= DAILY_CALL_LIMIT:
                raise ResearchUnavailable("vidIQ daily research call limit reached")
            conn.execute("INSERT INTO calls VALUES (?,?,?,NULL)", (day,digest,name))
        result = self.rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise ResearchUnavailable(f"{name} returned an error; see account health before retry")
        receipt = {"source": "vidiq_mcp", "retrieved_at": datetime.now(timezone.utc).isoformat(),
                   "tool": name, "arguments": arguments, "result": result}
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE calls SET result=? WHERE day=? AND digest=?", (json.dumps(receipt), day,digest))
        return receipt

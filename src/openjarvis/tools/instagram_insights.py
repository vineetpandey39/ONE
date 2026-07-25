"""Read Instagram account/post performance via the Instagram Graph API.

Born from a real failure (2026-07-25): Vineet asked for "the stats of my
last video performance from instagram" and the Ghost Agent could only
lecture him about how the Graph API works, because no tool existed. This
is that tool: read-only insights (recent posts, per-post metrics,
account summary) against graph.facebook.com.

Credentials come from ONE's Credential Vault (the existing "Instagram"
preset on the /credentials page, section `instagram_post`), injected into
the environment at server startup -- INSTAGRAM_ACCESS_TOKEN and
INSTAGRAM_BUSINESS_ACCOUNT_ID. Per the standing vault-only rule, nothing
is ever hardcoded here; with no credentials saved, the tool returns a
short instruction pointing at the vault page instead of failing
cryptically (and the system prompt tells the Ghost Agent to relay that,
not improvise an API tutorial).

requests(verify=False): same Avast SSL-interception workaround already
confirmed necessary for web_search (DDGS) and Deepgram on this machine.
"""

from __future__ import annotations

import os
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_GRAPH = "https://graph.facebook.com/v21.0"
_TIMEOUT = 15

# Post-level metric set for current API versions (impressions is gone for
# newly-created media as of v22 deprecations; `views` is the successor).
# If the API rejects the set for a given media type, we retry with the
# minimal universally-valid pair instead of failing the whole call.
_MEDIA_METRICS = "views,reach,likes,comments,shares,saved,total_interactions"
_MEDIA_METRICS_FALLBACK = "reach,saved"

_MISSING_CREDS_MSG = (
    "Instagram access isn't configured yet. Add INSTAGRAM_ACCESS_TOKEN and "
    "INSTAGRAM_BUSINESS_ACCOUNT_ID under the Instagram preset on ONE's "
    "Credential Vault page (/credentials), then restart ONE. The token must "
    "be a long-lived Page token for the Facebook Page linked to the "
    "Instagram Business/Creator account."
)


def _get(url: str, params: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """GET a Graph API endpoint. Returns (json, "") or (None, error)."""
    import requests
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT, verify=False)
        data = resp.json()
    except Exception as exc:
        return None, f"Request failed: {exc}"
    if "error" in data:
        err = data["error"]
        return None, f"{err.get('type', 'APIError')}: {err.get('message', 'unknown error')}"
    return data, ""


@ToolRegistry.register("instagram_insights")
class InstagramInsightsTool(BaseTool):
    """Read-only Instagram performance data (posts, metrics, account)."""

    tool_id = "instagram_insights"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="instagram_insights",
            description=(
                "Read REAL performance data from Vineet's Instagram "
                "Business account via the Graph API. Actions: "
                "'recent_media' lists the latest posts (id, type, caption, "
                "timestamp, likes, comments) -- call this FIRST to find the "
                "post he means (e.g. his last video/reel), then "
                "'media_insights' with that media_id for full metrics "
                "(views, reach, shares, saves, total interactions); "
                "'account_summary' for follower/media counts. Read-only, "
                "no confirmation needed. If it reports credentials missing, "
                "tell Vineet exactly what it says (vault page setup) -- do "
                "not improvise developer-portal tutorials."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["recent_media", "media_insights", "account_summary"],
                        "description": "What to fetch.",
                    },
                    "media_id": {
                        "type": "string",
                        "description": "media_insights only: id from recent_media.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "recent_media only: how many posts (default 5, max 20).",
                    },
                },
                "required": ["action"],
            },
            category="web_intelligence",
            cost_estimate=0.0,
            timeout_seconds=45,
        )

    def execute(self, **params: Any) -> ToolResult:
        token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
        ig_id = os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID", "").strip()
        if not token or not ig_id:
            return ToolResult(
                tool_name=self.tool_id, content=_MISSING_CREDS_MSG, success=False
            )

        action = str(params.get("action", "")).strip()

        if action == "account_summary":
            data, err = _get(
                f"{_GRAPH}/{ig_id}",
                {"fields": "username,followers_count,media_count", "access_token": token},
            )
            if data is None:
                return ToolResult(tool_name=self.tool_id, content=err, success=False)
            return ToolResult(
                tool_name=self.tool_id,
                content=(
                    f"@{data.get('username', '?')}: "
                    f"{data.get('followers_count', '?')} followers, "
                    f"{data.get('media_count', '?')} posts."
                ),
                success=True,
            )

        if action == "recent_media":
            limit = max(1, min(int(params.get("limit") or 5), 20))
            data, err = _get(
                f"{_GRAPH}/{ig_id}/media",
                {
                    "fields": (
                        "id,media_type,media_product_type,caption,timestamp,"
                        "like_count,comments_count,permalink"
                    ),
                    "limit": limit,
                    "access_token": token,
                },
            )
            if data is None:
                return ToolResult(tool_name=self.tool_id, content=err, success=False)
            posts = data.get("data", [])
            if not posts:
                return ToolResult(
                    tool_name=self.tool_id,
                    content="No posts found on the account.",
                    success=True,
                )
            lines = []
            for p in posts:
                caption = (p.get("caption") or "").replace("\n", " ")[:80]
                lines.append(
                    f"- id={p.get('id')} [{p.get('media_product_type') or p.get('media_type')}] "
                    f"{p.get('timestamp', '')[:10]} likes={p.get('like_count', '?')} "
                    f"comments={p.get('comments_count', '?')} :: {caption}"
                )
            return ToolResult(
                tool_name=self.tool_id, content="\n".join(lines), success=True
            )

        if action == "media_insights":
            media_id = str(params.get("media_id", "")).strip()
            if not media_id:
                return ToolResult(
                    tool_name=self.tool_id,
                    content="media_insights needs media_id (get it from recent_media).",
                    success=False,
                )
            data, err = _get(
                f"{_GRAPH}/{media_id}/insights",
                {"metric": _MEDIA_METRICS, "access_token": token},
            )
            if data is None and "metric" in err.lower():
                data, err = _get(
                    f"{_GRAPH}/{media_id}/insights",
                    {"metric": _MEDIA_METRICS_FALLBACK, "access_token": token},
                )
            if data is None:
                return ToolResult(tool_name=self.tool_id, content=err, success=False)
            lines = [
                f"{m.get('name')}: {(m.get('values') or [{}])[0].get('value', '?')}"
                for m in data.get("data", [])
            ]
            return ToolResult(
                tool_name=self.tool_id,
                content="\n".join(lines) or "No insights returned for this post.",
                success=True,
                metadata={"media_id": media_id},
            )

        return ToolResult(
            tool_name=self.tool_id,
            content=f"Unknown action '{action}'.",
            success=False,
        )


__all__ = ["InstagramInsightsTool"]

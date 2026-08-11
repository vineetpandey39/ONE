"""Function surface exposed to Deepgram's cloud 'think' LLM.

3 narrow functions (get_current_time, agent_stats, recall_memory) plus one
gateway function, `ask_ghost_agent`, added 2026-08-11 per Vineet's explicit
request (confirmed: full toolset) to make the Ghost Agent voice's actual
driver for "everything on this PC" and for handing work to the floor
agents (ZEUS, ATHENA, etc.). `ask_ghost_agent` runs the SAME code path
typed chat's Ghost Agent uses (`_one_agent_command` for agent dispatch,
`_run_cloud_tool_loop` + `_cloud_escalation_tools()` for web_search/
file_read/shell_exec/open_app/play_video/system_query/instagram_insights/
screen_control) -- no new tool loop, no tunnel, just an in-process function
call, since both already run inside the same FastAPI server. shell_exec
keeps its existing requires_confirmation gate unchanged (voice does not
bypass it -- it is refused exactly like a typed request would be, unless
ONE_GHOST_AGENT_AUTO_EXECUTE is set locally).

The redaction requirement did not go away when this was added -- if
anything it matters more now, since Ghost Agent can touch far more (file
contents, shell output, screen state). Every function here, including
ask_ghost_agent, is still piped through `voice_bridge.redact.redact()`
before its result is ever written back onto the Deepgram socket, and still
audit-logged pre/post locally. search_obsidian and agent_network's
history/status actions remain excluded (raw free-text vault/task content).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from openjarvis.tools._stubs import BaseTool
from openjarvis.tools.agent_network import AgentNetworkTool
from openjarvis.tools.datetime_tool import GetCurrentTimeTool
from openjarvis.tools.memory_recall import MemoryRecallTool
from openjarvis.voice_bridge.redact import redact

logger = logging.getLogger("openjarvis.voice_bridge")

# Ghost Agent's replies are written for a TEXT reader (typed chat renders
# markdown properly) -- but ask_ghost_agent's return value goes straight
# onto the Deepgram socket as a FunctionCallResponse and gets spoken. Raw
# "**word**"/"# Heading"/"`code`" syntax either gets read back literally
# (confirmed live 2026-08-12: Vineet heard/saw stray asterisks -- "why she
# always says ** this ** that") or adds junk characters TTS has to deal
# with. Stripped only at this voice-facing boundary -- typed chat's replies
# (same Ghost Agent, same _run_cloud_tool_loop) are untouched and keep full
# markdown, since that's rendered properly there.
_MARKDOWN_STRIP_PATTERNS = [
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),  # **bold**
    (re.compile(r"__(.+?)__"), r"\1"),  # __bold__
    (re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)"), r"\1"),  # *italic*
    (re.compile(r"`{1,3}([^`]+?)`{1,3}"), r"\1"),  # `code` / ```code```
    (re.compile(r"^#{1,6}\s*", re.MULTILINE), ""),  # # Heading
    (re.compile(r"^\s*[-*+]\s+", re.MULTILINE), ""),  # - bullet
    (re.compile(r"^\s*\d+\.\s+", re.MULTILINE), ""),  # 1. numbered list
]


def _strip_markdown_for_speech(text: str) -> str:
    out = text
    for pattern, replacement in _MARKDOWN_STRIP_PATTERNS:
        out = pattern.sub(replacement, out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()

_time_tool = GetCurrentTimeTool()
_agent_tool = AgentNetworkTool()
_memory_tool = MemoryRecallTool()

# Set once, from routes.py's voice_bridge_start (which has request.app.state),
# since this module's functions are plain dispatch calls with no session
# object of their own to carry it. Left empty when no cloud key is
# configured -- ask_ghost_agent then reports unavailable rather than crash.
_ghost_ctx: Dict[str, Any] = {}

# Per-voice-session conversation history for ask_ghost_agent. Confirmed live
# (2026-08-11) that without this, every ask_ghost_agent call started a BRAND
# NEW conversation with the Ghost Agent LLM -- only that single query, no
# memory of what it tried or said one turn earlier in the SAME live voice
# call. A multi-step request (e.g. "create a file with 5 messages" ->
# "check if it's there" -> "it's not, try again") looked to Sir like ONE
# repeatedly forgetting/restarting instead of building on its own last
# attempt -- reported as "voice breaking and getting lost in conversation."
# Reset at the start of every voice_bridge_start (see set_ghost_agent_context)
# so a new live session starts clean; capped so a very long session doesn't
# grow the prompt/cost unbounded.
_conversation_history: list = []
_MAX_HISTORY_TURNS = 12  # user+assistant pairs kept, oldest dropped first


def set_ghost_agent_context(engine: Any, model: Optional[str], app_config: Any = None) -> None:
    _ghost_ctx["engine"] = engine
    _ghost_ctx["model"] = model
    _ghost_ctx["app_config"] = app_config
    _conversation_history.clear()


_ASK_GHOST_AGENT_SCHEMA: Dict[str, Any] = {
    "name": "ask_ghost_agent",
    "description": (
        "Hand a request to Sir's full local Ghost Agent -- the one with real "
        "access to this PC and to Sir's team of floor agents (ZEUS, ATHENA, "
        "DAEDALUS, TITAN, and the rest). Use this for anything beyond a "
        "simple time/agent-stats/memory lookup: web searches, reading a "
        "local file, opening an app, playing a video, checking system info, "
        "Instagram insights, screen control, running a shell command (Sir "
        "will be asked to confirm before anything actually executes), or "
        "dispatching/handing off work to one of the named floor agents. "
        "Pass Sir's request through close to verbatim -- the Ghost Agent "
        "does its own planning."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Sir's request, in his own words.",
            }
        },
        "required": ["query"],
    },
}

_AGENT_STATS_SCHEMA: Dict[str, Any] = {
    "name": "agent_stats",
    "description": (
        "Get a summary of how Sir's local agents are doing -- job counts and "
        "last-run status. Use for any 'how are the agents doing' or "
        "status-review question. Never use this to start new agent work."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "detail": {
                "type": "string",
                "enum": ["brief", "holistic"],
                "description": "brief = one line per agent (default). holistic = fuller breakdown.",
            }
        },
        "required": [],
    },
}


def deepgram_function_schemas() -> List[Dict[str, Any]]:
    """The functions declared to Deepgram, in its flat schema shape.

    Deepgram's `agent.think.functions` wants `[{name, description,
    parameters}]` -- one layer flatter than BaseTool.to_openai_function()'s
    `{type: "function", function: {...}}` envelope -- so this just unwraps
    it. No `endpoint` is set on any of these, which per Deepgram's docs means
    they're executed client-side: the server sends a FunctionCallRequest and
    this bridge answers it locally (see client.py's _handle_function_calls).
    """
    tools: list[BaseTool] = [_time_tool]
    schemas = [t.to_openai_function()["function"] for t in tools]
    schemas.append(_AGENT_STATS_SCHEMA)

    mem_schema = _memory_tool.to_openai_function()["function"]
    mem_schema["description"] = (
        mem_schema["description"]
        + " Results are sanitized and shortened before you receive them; some detail may be trimmed."
    )
    schemas.append(mem_schema)
    schemas.append(_ASK_GHOST_AGENT_SCHEMA)
    return schemas


def _ask_ghost_agent(query: str) -> str:
    """Route a request through the same in-process code path typed chat's
    Ghost Agent uses. Deterministic agent-dispatch commands ("ZEUS, look
    into X") are tried first via `_one_agent_command` -- free, local, no
    LLM round-trip, exactly how typed chat resolves them. Anything else
    falls through to the real tool loop (`_run_cloud_tool_loop` +
    `_cloud_escalation_tools()`): web_search, file_read, open_app,
    play_video, system_query, instagram_insights, screen_control,
    shell_exec (still gated behind its own confirmation requirement).

    Reads `_conversation_history` (built from EVERY turn of the live
    conversation via client.py's remember_full_turn, not just tool-triggered
    ones) so the Ghost Agent's own reasoning has real context. Does not
    write to history/Obsidian itself -- remember_full_turn already covers
    this turn once Deepgram finishes speaking the reply; recording here too
    would double-save it."""
    query = (query or "").strip()
    if not query:
        return "No request came through, Sir."

    # Deterministic agent-dispatch ("ZEUS, look into X", "how are the agents
    # doing") needs no cloud key at all -- this is pure local parsing, the
    # same path typed chat resolves it through. Tried before the cloud-key
    # check below so agent dispatch by voice keeps working even on a setup
    # (like this one) with no ANTHROPIC_API_KEY/OPENAI_API_KEY configured --
    # only the broader tool loop (web_search/file_read/shell_exec/etc.)
    # actually needs a cloud key. Deterministic replies are still added to
    # history/Obsidian below so a later "the same thing I just dispatched"
    # reference in the SAME tool-loop call still resolves correctly.
    from openjarvis.server.routes import _one_agent_command

    deterministic = _one_agent_command(query)
    if deterministic:
        # Not recorded here -- client.py's ConversationText flush
        # (remember_full_turn) covers every turn uniformly, tool-triggered
        # or not; recording here too would double-save this exchange.
        return _strip_markdown_for_speech(deterministic)

    engine = _ghost_ctx.get("engine")
    model = _ghost_ctx.get("model")
    if engine is None or not model:
        return "The Ghost Agent isn't available right now -- no cloud key is configured, Sir."

    from openjarvis.server.routes import (
        _ensure_identity_prompt,
        _run_cloud_tool_loop,
        _with_ghost_agent_prompt,
    )
    from openjarvis.core.types import Message, Role

    messages: list[Message] = list(_conversation_history) + [Message(role=Role.USER, content=query)]
    messages = _ensure_identity_prompt(messages, _ghost_ctx.get("app_config"))
    messages = _with_ghost_agent_prompt(messages)
    try:
        result = _run_cloud_tool_loop(engine, model, messages, temperature=0.4, max_tokens=600)
    except Exception as exc:  # noqa: BLE001
        return f"The Ghost Agent hit an error: {exc}"
    reply = (result.get("content") or "").strip() or "Done, Sir -- though I don't have a summary to report."
    # Not recorded here -- see the note on the deterministic-reply branch
    # above; client.py's ConversationText flush covers this turn already.
    return _strip_markdown_for_speech(reply)


def _remember_exchange(query: str, reply: str) -> None:
    """Append to the in-session history (so the NEXT ask_ghost_agent call in
    this same voice session has real context) and best-effort save to the
    Obsidian journal (so it survives a page refresh / new session, exactly
    like typed chat's exchanges already do)."""
    from openjarvis.core.types import Message, Role

    _conversation_history.append(Message(role=Role.USER, content=query))
    _conversation_history.append(Message(role=Role.ASSISTANT, content=reply))
    # Keep the last _MAX_HISTORY_TURNS user+assistant pairs only.
    max_messages = _MAX_HISTORY_TURNS * 2
    if len(_conversation_history) > max_messages:
        del _conversation_history[: len(_conversation_history) - max_messages]

    try:
        from openjarvis.server.routes import _save_exchange_to_obsidian

        _save_exchange_to_obsidian(query, reply)
    except Exception:
        logger.debug("voice bridge: saving exchange to Obsidian failed", exc_info=True)


def remember_full_turn(user_text: str, assistant_text: str) -> None:
    """Called from client.py for EVERY turn of the live conversation, not
    just ones that happened to call a function -- confirmed live
    (2026-08-12) that most of a real conversation is Deepgram's own
    think-model answering directly, with no function call at all, and none
    of that was previously captured anywhere (in-session history OR
    Obsidian). No redaction needed here: this is Deepgram's own transcript
    of what it already said/heard over the SAME socket -- saving it locally
    (Obsidian) or replaying it back to Deepgram as history exposes nothing
    that party doesn't already have."""
    _remember_exchange(user_text, assistant_text)

    try:
        from openjarvis.server.routes import _save_exchange_to_obsidian

        _save_exchange_to_obsidian(query, reply)
    except Exception:
        logger.debug("voice bridge: saving exchange to Obsidian failed", exc_info=True)


def _audit(name: str, arguments: Dict[str, Any], pre: str, post: str) -> None:
    """Local-only audit trail: what a function returned before and after
    redaction, so Vineet can verify the filter is actually working. Never
    transmitted -- this file never leaves the machine."""
    try:
        from openjarvis.core.paths import get_config_dir

        log_dir = get_config_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "function": name,
                "arguments": arguments,
                "pre_redaction": pre,
                "post_redaction": post,
            },
            ensure_ascii=True,
        )
        with open(log_dir / "voice_bridge_audit.log", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        logger.debug("voice bridge audit log write failed", exc_info=True)


def execute_function(name: str, arguments: Dict[str, Any]) -> str:
    """Run one of the allowed functions and return an already-redacted string.

    Never raises: an unknown function name or a tool-level error becomes a
    safe generic message rather than propagating, since this return value
    goes straight back over the WebSocket to Deepgram's cloud.
    """
    try:
        if name == "get_current_time":
            pre = _time_tool.execute(**arguments).content
        elif name == "agent_stats":
            pre = _agent_tool.execute(action="stats", detail=arguments.get("detail", "brief")).content
        elif name == "recall_memory":
            pre = _memory_tool.execute(**arguments).content
        elif name == "ask_ghost_agent":
            pre = _ask_ghost_agent(arguments.get("query", ""))
        else:
            pre = f"Unknown function: {name}"
    except Exception as exc:  # noqa: BLE001
        pre = f"Function '{name}' failed: {exc}"

    post = redact(pre)
    _audit(name, arguments, pre, post)
    return post


__all__ = [
    "deepgram_function_schemas",
    "execute_function",
    "set_ghost_agent_context",
    "remember_full_turn",
]

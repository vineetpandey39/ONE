"""Understand what the Chairman actually asked for, instead of keyword-matching.

The old router was a regex over a verb list. It worked only if you happened to
use one of ~12 blessed words: "HERMES, execute the KDP book factory" silently
fell through to the paid cloud path because `execute` wasn't on the list, and
"Dispatch Hermes agent." researched-and-stopped because `dispatch` mapped to
plan mode. That is a vocabulary quiz, not comprehension.

This asks Claude instead, showing it the live agent roster and asking which
agent — if any — should act, and whether the ask is to do the work or only to
look into it. Any phrasing, any language, works.

Design rules:
  * Deterministic first. The caller keeps its cheap regex fast-path; this is
    only consulted when that path is unsure. No new latency on clear commands.
  * Fails safe. If Claude is unreachable or answers oddly, return None and let
    the caller fall back to its existing behaviour — never guess an agent.
  * Never dispatches by itself. It returns a decision; the caller acts on it.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

# A question about an agent is not an instruction to that agent.
_ACTIONS = {"work", "research", "none"}


def _client():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None, "ANTHROPIC_API_KEY is not in ONE's credential vault"
    try:
        import anthropic
    except ImportError as exc:
        return None, f"anthropic package unavailable: {exc}"
    try:
        # verify=False: the same Avast SSL-interception workaround already used
        # for Deepgram, web_search and instagram_insights on this machine.
        return anthropic.Anthropic(
            api_key=api_key,
            http_client=httpx.Client(verify=False, timeout=30.0),
        ), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"client init failed: {exc}"


def _roster_lines(agents: dict[str, dict[str, str]]) -> str:
    return "\n".join(
        f"- {key}: {value.get('name')} — Floor {value.get('floor_id')} "
        f"({value.get('floor_name')}) — {value.get('role')}"
        for key, value in agents.items()
    )


def classify(message: str, agents: dict[str, dict[str, str]]) -> dict[str, Any] | None:
    """Decide who should act on a message, and how.

    Returns ``{"agent_id", "action", "task", "reason"}`` or ``None`` when the
    call fails — None means "no opinion", not "nobody should act".

    ``action``:
        work     — do the job end to end
        research — look into it and report back, don't commission anything
        none     — conversation, a question, or nothing for an agent to do
    """
    text = str(message or "").strip()
    if not text:
        return None

    client, note = _client()
    if client is None:
        return None

    model = os.environ.get("ONE_INTENT_MODEL", "claude-haiku-4-5")
    prompt = (
        "You route instructions to agents in an autonomous company. Decide which "
        "agent, if any, should act on the message below.\n\n"
        f"Agents:\n{_roster_lines(agents)}\n\n"
        f"Message: {text}\n\n"
        "Rules:\n"
        "- Pick the agent whose floor owns the work, even if the message never "
        "names an agent. Match on subject matter.\n"
        "- action=work when the person wants the job actually done.\n"
        "- action=research when they explicitly want only investigation, a plan, "
        "a draft, or options — not the finished thing.\n"
        "- action=none for anything that is a QUESTION rather than an "
        "instruction, plus status checks, greetings and chat. 'What can HERMES "
        "do?', 'is IRIS busy?', 'who handles books?' are all none — describing "
        "an agent is not commissioning work from it. When unsure, none.\n"
        "- The message may be in English, Hindi, or a mix. Understand intent, "
        "not keywords.\n"
        "- task: restate the actual job in one clear English sentence.\n\n"
        "Reply with only this, nothing else:\n"
        "AGENT: <agent key from the list, or none>\n"
        "ACTION: work | research | none\n"
        "TASK: <one sentence>\n"
        "REASON: <short>"
    )

    try:
        message_obj = client.messages.create(
            model=model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        reply = "".join(
            block.text for block in message_obj.content
            if getattr(block, "type", None) == "text"
        ).strip()
    except Exception:  # noqa: BLE001 - caller falls back to its own routing
        return None

    def field(key: str, default: str = "") -> str:
        found = re.search(rf"^{key}:\s*(.+)$", reply, re.MULTILINE | re.IGNORECASE)
        return found.group(1).strip() if found else default

    agent_id = field("AGENT", "none").lower().strip().strip(".")
    action = field("ACTION", "none").lower().strip().strip(".")
    if action not in _ACTIONS:
        action = "none"
    if agent_id not in agents or action == "none":
        return {"agent_id": None, "action": "none",
                "task": field("TASK"), "reason": field("REASON")}

    # Work is commissioned through the floor head, never handed straight to a
    # worker. A worker's task payload is a structured brief its head writes;
    # dispatching one directly would skip the brief and bypass the org chart.
    redirected_from = None
    if agents[agent_id].get("seat") == "worker":
        head = agents[agent_id].get("reports_to")
        if head in agents:
            redirected_from, agent_id = agent_id, head

    return {
        "agent_id": agent_id,
        "action": action,
        "task": field("TASK") or text,
        "reason": field("REASON"),
        "redirected_from": redirected_from,
    }


def describe(decision: dict[str, Any] | None) -> str:
    if not decision or not decision.get("agent_id"):
        return "no agent selected"
    return f"{decision['agent_id']} / {decision['action']}"

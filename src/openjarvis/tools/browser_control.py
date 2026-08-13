"""General page control in Vineet's real Chrome, via the ONE Browser Control extension.

Part 2 of a deliberately two-part design (Vineet's explicit instruction,
2026-08-12): simple "open a video / search and play something" requests stay
on the narrower PlayVideoTool + "ONE Ghost Agent" extension path. This tool
is only for genuine multi-step page work -- go to a site, read what's there,
click through, fill something in.

Thinking is done by NVIDIA Nemotron (the same "heavy tier" escalation the
agent runtime already uses -- see one_agents/runtime._resolve_planner_model),
not by the cloud model driving Ghost Agent itself, per Vineet's request to
use Nemotron for the intellectual work here.

SAFETY -- the commit gate. Navigating, reading, clicking ordinary links and
typing into fields all proceed freely. Anything that looks like it COMMITS
to something real (buy, pay, submit, send, delete, subscribe...) is refused
by the extension unless the command carries confirmed=True. This tool only
sets that flag when its own `confirmed` parameter was passed, which the
Ghost Agent is instructed to do ONLY after Vineet has said yes to that
specific named action. The check is enforced independently inside the
extension too, so a bug or a bad prompt here cannot silently commit
something on its own.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import Message, Role, ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_MAX_STEPS = 12
_COMMAND_TIMEOUT_SECONDS = 25.0

_PLANNER_PROMPT = """\
You are driving a real web browser to accomplish a task for Sir.

TASK: {task}

CURRENT PAGE
url: {url}
title: {title}

PAGE TEXT (truncated):
{text}

INTERACTIVE ELEMENTS (use the exact ref string):
{elements}

Reply with ONE json object and nothing else:
{{"action": "navigate"|"click"|"type"|"done"|"give_up",
  "url": "<for navigate>",
  "ref": "<for click/type>",
  "text": "<for type>",
  "submit": true|false,
  "answer": "<for done/give_up: what to tell Sir>",
  "why": "<one short sentence>"}}

Rules:
- Prefer clicking a real element over navigating to a guessed URL.
- Use "done" as soon as the task is actually accomplished, with the answer.
- Use "give_up" if the page makes the task impossible; explain why.
- Elements marked commit=true will be REFUSED unless Sir already confirmed.
"""


def _summarise_elements(elements: list[dict[str, Any]]) -> str:
    lines = []
    for el in elements[:60]:
        text = (el.get("text") or "").replace("\n", " ").strip()
        flag = " [COMMIT]" if el.get("commit") else ""
        lines.append(f"- {el.get('ref')}: <{el.get('tag')}> {text[:70]}{flag}")
    return "\n".join(lines) or "(no interactive elements found)"


@ToolRegistry.register("browse_web")
class BrowserControlTool(BaseTool):
    """Multi-step page control in Vineet's own logged-in Chrome."""

    tool_id = "browse_web"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browse_web",
            description=(
                "Do a multi-step task on a website in Sir's real, logged-in Chrome -- "
                "go to a page, read it, click through it, fill something in. Use this "
                "for anything that needs actually working through a site ('find X on "
                "this site and tell me', 'log into Y and check Z', 'fill this form'). "
                "Do NOT use this just to play or search for a video -- play_video is "
                "the right tool for that and is much faster. "
                "IMPORTANT: if this returns asking for confirmation of a specific "
                "action (buy/submit/send/delete), relay that to Sir in your reply and "
                "STOP -- only call this again with confirmed=true after Sir has "
                "explicitly said yes to that exact action."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "What to accomplish, in plain language. Include the starting URL if you know it.",
                    },
                    "start_url": {
                        "type": "string",
                        "description": "Optional URL to open first. Recommended when you know where the task starts.",
                    },
                    "confirmed": {
                        "type": "boolean",
                        "description": (
                            "Only set true when Sir has ALREADY explicitly approved a specific "
                            "commit-style action (buy/submit/send/delete) in the conversation. "
                            "Never set this speculatively."
                        ),
                    },
                },
                "required": ["task"],
            },
            category="browser",
            cost_estimate=0.0,
            timeout_seconds=180,
        )

    # -- extension plumbing --

    def _await(self, command_id: str) -> dict[str, Any] | None:
        from openjarvis.server.browser_control_bridge import pop_result

        deadline = time.time() + _COMMAND_TIMEOUT_SECONDS
        while time.time() < deadline:
            result = pop_result(command_id)
            if result is not None:
                return result
            time.sleep(0.15)
        return None

    def _think(self, task: str, page: dict[str, Any]) -> dict[str, Any]:
        """Ask Nemotron for the next action. Returns the parsed decision."""
        from openjarvis.engine.openai_compat_engines import NvidiaNimEngine

        model = os.environ.get("NEMOTRON_MODEL", "").strip()
        if not model or not os.environ.get("NVIDIA_API_KEY", "").strip():
            raise RuntimeError(
                "Nemotron isn't configured (NEMOTRON_MODEL + NVIDIA_API_KEY), so I can't "
                "reason about the page"
            )

        prompt = _PLANNER_PROMPT.format(
            task=task,
            url=page.get("url", ""),
            title=page.get("title", ""),
            text=(page.get("text") or "")[:2500],
            elements=_summarise_elements(page.get("elements") or []),
        )
        reply = NvidiaNimEngine().generate(
            [Message(role=Role.USER, content=prompt)],
            model=model,
            temperature=0.1,
            max_tokens=400,
        )
        raw = (reply.get("content") or "").strip()
        # Models frequently wrap JSON in prose or a ```json fence -- take the
        # outermost object rather than trusting a bare json.loads.
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            raise RuntimeError(f"Nemotron didn't return a decision I could parse: {raw[:200]}")
        return json.loads(raw[start : end + 1])

    def execute(self, **params: Any) -> ToolResult:
        from openjarvis.server.browser_control_bridge import (
            enqueue_click,
            enqueue_navigate,
            enqueue_read_page,
            enqueue_type,
            extension_is_live,
        )

        task = str(params.get("task") or "").strip()
        if not task:
            return ToolResult(tool_name=self.tool_id, content="No task was given.", success=False)
        confirmed = bool(params.get("confirmed"))
        start_url = str(params.get("start_url") or "").strip()

        if not extension_is_live():
            return ToolResult(
                tool_name=self.tool_id,
                content=(
                    "The ONE Browser Control extension isn't connected, Sir. Load it from "
                    "chrome://extensions (Developer mode -> Load unpacked -> "
                    "src/browser-control-extension) and make sure Chrome is running."
                ),
                success=False,
            )

        trail: list[str] = []

        if start_url:
            if self._await(enqueue_navigate(start_url)) is None:
                return ToolResult(
                    tool_name=self.tool_id,
                    content=f"The browser didn't respond when opening {start_url}.",
                    success=False,
                )
            trail.append(f"opened {start_url}")

        for _step in range(_MAX_STEPS):
            read = self._await(enqueue_read_page())
            if read is None or not read.get("success"):
                return ToolResult(
                    tool_name=self.tool_id,
                    content="Couldn't read the page. " + "; ".join(trail),
                    success=False,
                )
            page = read.get("data") or {}

            try:
                decision = self._think(task, page)
            except Exception as exc:  # noqa: BLE001
                return ToolResult(
                    tool_name=self.tool_id,
                    content=f"{exc}. Progress so far: {'; '.join(trail) or 'none'}",
                    success=False,
                )

            action = str(decision.get("action") or "").lower()

            if action == "done":
                answer = str(decision.get("answer") or "Task finished.")
                return ToolResult(
                    tool_name=self.tool_id,
                    content=f"{answer}\n\n(Steps: {'; '.join(trail) or 'read the page'})",
                    success=True,
                    metadata={"url": page.get("url"), "steps": trail},
                )
            if action == "give_up":
                return ToolResult(
                    tool_name=self.tool_id,
                    content=str(decision.get("answer") or "Couldn't complete that on this page.")
                    + f"\n\n(Steps: {'; '.join(trail) or 'read the page'})",
                    success=False,
                )

            if action == "navigate":
                url = str(decision.get("url") or "").strip()
                if not url:
                    trail.append("planner asked to navigate with no url; stopping")
                    break
                result = self._await(enqueue_navigate(url))
                trail.append(f"navigated to {url}")
            elif action == "click":
                ref = str(decision.get("ref") or "")
                result = self._await(enqueue_click(ref, confirmed=confirmed))
                trail.append(f"clicked {ref}")
            elif action == "type":
                ref = str(decision.get("ref") or "")
                text = str(decision.get("text") or "")
                submit = bool(decision.get("submit"))
                result = self._await(enqueue_type(ref, text, submit=submit, confirmed=confirmed))
                trail.append(f"typed into {ref}" + (" and submitted" if submit else ""))
            else:
                trail.append(f"planner returned unknown action {action!r}; stopping")
                break

            if result is None:
                return ToolResult(
                    tool_name=self.tool_id,
                    content=f"The browser stopped responding. Progress: {'; '.join(trail)}",
                    success=False,
                )
            # The commit gate fired inside the extension -- surface it as a
            # question for Sir rather than retrying or working around it.
            if not result.get("success") and result.get("detail") == "commit_confirmation_required":
                element = ((result.get("data") or {}).get("elementText")) or "that action"
                return ToolResult(
                    tool_name=self.tool_id,
                    content=(
                        f'This next step would commit something real -- "{element}" on '
                        f"{page.get('url')}. I've stopped and not done it. Tell Sir exactly "
                        "what it is and ask him to confirm; only if he explicitly says yes, "
                        "call browse_web again with the same task and confirmed=true."
                    ),
                    success=False,
                    metadata={"needs_confirmation": True, "element": element, "url": page.get("url")},
                )

        return ToolResult(
            tool_name=self.tool_id,
            content=f"Stopped after {_MAX_STEPS} steps without finishing. Progress: {'; '.join(trail)}",
            success=False,
        )


__all__ = ["BrowserControlTool"]

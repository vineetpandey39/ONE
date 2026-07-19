"""Route handlers for the OpenAI-compatible API server."""

from __future__ import annotations

import logging
import json
import os
import re
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from openjarvis.core.paths import get_config_dir
from openjarvis.core.types import Message, Role, ToolCall
from openjarvis.server.models import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    Choice,
    ChoiceMessage,
    ComplexityInfo,
    DeltaMessage,
    ModelListResponse,
    ModelObject,
    StreamChoice,
    UsageInfo,
)

router = APIRouter()


def _one_model_status(model: str | None = None) -> dict[str, Any]:
    engine = os.environ.get("ONE_ENGINE", "ollama").strip() or "ollama"
    router_model = (
        model
        or os.environ.get("ONE_ROUTER_MODEL")
        or os.environ.get("NEMOTRON_MODEL")
        or "llama3.1:8b"
    )
    nemotron_model = os.environ.get("NEMOTRON_MODEL", "").strip()
    nvidia_key = os.environ.get("NVIDIA_API_KEY", "").strip()
    nvidia_host = os.environ.get("NVIDIA_HOST", "https://integrate.api.nvidia.com").strip()
    image_provider = os.environ.get("ONE_IMAGE_PROVIDER", "openai").strip() or "openai"
    flux_url = os.environ.get("ONE_FLUX_URL", "http://127.0.0.1:8188").strip()
    flux_model = os.environ.get("ONE_FLUX_MODEL", "black-forest-labs/FLUX.1-schnell").strip()
    nemotron_ready = bool(
        (engine == "nvidia" or nemotron_model or "nemotron" in router_model.lower())
        and nvidia_key
    )
    route_map = [
        {"scope": "simple_chat", "model": router_model, "engine": engine},
        {"scope": "agent_status_and_queue", "model": "deterministic", "engine": "local-python"},
        {"scope": "alfa_scan", "model": "deterministic + optional local packaging", "engine": "local-python/ollama"},
        {"scope": "jobhunt", "model": nemotron_model or router_model, "engine": "nvidia" if nemotron_ready else engine},
        {"scope": "ia_scout_and_metadata", "model": nemotron_model or router_model, "engine": "nvidia" if nemotron_ready else engine},
        {"scope": "ia_image_generation", "model": flux_model if image_provider == "flux" else "gpt-image-2", "engine": image_provider},
        {"scope": "ia_video_generation", "model": "fal/Leonardo + ffmpeg", "engine": "tool-pipeline"},
    ]
    return {
        "engine": engine,
        "router_model": router_model,
        "agent": os.environ.get("ONE_AGENT", "react"),
        "nemotron_model": nemotron_model,
        "nemotron_ready": nemotron_ready,
        "nvidia": {
            "host": nvidia_host,
            "api_key_configured": bool(nvidia_key),
        },
        "image_generation": {
            "provider": image_provider,
            "flux_url": flux_url,
            "flux_model": flux_model,
            "flux_autostart": os.environ.get("ONE_FLUX_AUTOSTART", "false").lower() == "true",
        },
        "route_map": route_map,
    }


@router.get("/v1/one/status")
async def one_status():
    from openjarvis.one_agents.obsidian import obsidian_status, recent_memories
    from openjarvis.one_agents.runtime import AGENTS, list_jobs

    model_status = _one_model_status()
    return {
        "name": "ONE",
        "online": True,
        "model": model_status["router_model"],
        "model_status": model_status,
        "agents": [{"id": key, **value} for key, value in AGENTS.items()],
        "jobs": list_jobs(12),
        "obsidian": obsidian_status(),
        "memories": recent_memories(12),
    }


@router.get("/v1/one/model-status")
async def one_model_status():
    return _one_model_status()


@router.get("/v1/one/credential-vault")
async def one_credential_vault():
    from openjarvis.core.credentials import list_credential_vault

    return list_credential_vault()


@router.post("/v1/one/credential-vault")
async def one_save_credential(request: Request):
    from openjarvis.core.credentials import save_vault_credential

    payload = await request.json()
    section = str(payload.get("section") or "custom").strip()
    key = str(payload.get("key") or "").strip()
    value = str(payload.get("value") or "")
    if not key:
        raise HTTPException(status_code=400, detail="key is required")
    try:
        save_vault_credential(section, key, value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"saved": key, "section": section or "custom"}


@router.delete("/v1/one/credential-vault/{section}/{key}")
async def one_delete_credential(section: str, key: str):
    from openjarvis.core.credentials import delete_vault_credential

    try:
        delete_vault_credential(section, key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": key, "section": section}


@router.get("/v1/one/jobs")
async def one_jobs():
    from openjarvis.one_agents.runtime import list_jobs

    return {"jobs": list_jobs(30)}


@router.get("/v1/jobhunt/board")
async def jobhunt_board(limit: int = 50):
    from openjarvis.one_agents.jobhunt import jobhunt_board as build_jobhunt_board

    return build_jobhunt_board(limit)


@router.get("/v1/one/wake-events")
async def one_wake_events(limit: int = 10):
    from openjarvis.one_agents.wake import recent_wake_events

    return {"events": recent_wake_events(limit)}


@router.get("/v1/one/memory-graph")
async def one_memory_graph(limit: int = 80):
    from openjarvis.one_agents.obsidian import memory_graph

    return memory_graph(limit)


@router.post("/v1/one/obsidian")
async def one_connect_obsidian(request: Request):
    from openjarvis.one_agents.obsidian import set_obsidian_path

    payload = await request.json()
    try:
        return set_obsidian_path(str(payload.get("path", "")))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/v1/one/obsidian/search")
async def one_search_obsidian(q: str = "", limit: int = 8):
    from openjarvis.one_agents.obsidian import search_obsidian

    try:
        return {"results": search_obsidian(q, limit)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/v1/one/memory")
async def one_remember(request: Request):
    from openjarvis.one_agents.obsidian import remember_exchange

    payload = await request.json()
    try:
        return remember_exchange(str(payload.get("command", "")), str(payload.get("response", "")))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _one_agent_command(text: str) -> str | None:
    """Route explicit ONE agent commands without spending an LLM call."""
    clean = " ".join(text.strip().split())
    lowered = clean.lower()
    if not clean:
        return None

    # A check-in is identity-critical and should feel immediate. Keep it out
    # of the general-purpose model so ONE never invents a name, changes tone,
    # or emits internal reasoning for a simple greeting.
    # The previous [^a-z0-9]+ silently deleted Hindi script entirely before
    # comparison, so "TUM कैसे हो?" was reduced to just "tum" and could
    # never match any Hindi greeting no matter what was in the set below.
    # Explicitly keep the Devanagari block (ऀ-ॿ) alongside ASCII —
    # note this can't just be \w: Python's \w does NOT include Unicode
    # combining marks (category Mn/Mc), which is exactly what Devanagari
    # vowel signs (matras) are, so \w alone silently drops them and mangles
    # the text (verified: "कैसे" -> "क स" with \w, stays "कैसे" with the
    # explicit range below).
    check_in = re.sub(r"[^a-z0-9ऀ-ॿ]+", " ", lowered).strip()
    check_in = re.sub(r"\b(one|jarvis|jervis|jarvish)\b", " ", check_in)
    check_in = re.sub(r"\s+", " ", check_in).strip()

    # Confirmed live (2026-07-19, traces.db trace 1f8824c59abe4edc): Whisper
    # transcribed a real "Hey ONE, how are you?" as "Hey, when, how are
    # you?" -- misheard "ONE" as "when". The exact-match set this used to be
    # (`check_in in {...}`) doesn't match "hey when how are you" at all, so
    # it fell through to the full ReAct/LLM path, which took 78s and still
    # failed with "Maximum turns reached". A single STT slip shouldn't ever
    # cost a minute-plus round trip for a greeting. Switched both checks
    # from exact-set membership to substring containment: any stray word
    # Whisper adds or mishears around the core phrase (a wake-word
    # mis-transcription, "buddy"/"today"/filler words, etc.) no longer
    # matters as long as the distinctive phrase itself is in there
    # somewhere. This also makes the greeting recognize things like "so hey
    # one how are you doing today buddy" without listing every combination.
    up_phrases = ("are you up", "are you there", "wake up", "wakeup", "startup", "start up")
    if check_in == "online" or check_in == "you up" or any(p in check_in for p in up_phrases):
        return "Always online, Sir. What do you need?"

    greeting_phrases = (
        "how are you", "how you doing", "how r u", "how s it going", "you good",
        "kaise ho", "kaise hain", "kya haal", "kya chal raha",
        # Devanagari script — this is what faster-whisper actually outputs
        # for Hindi audio (confirmed from a real transcript in traces.db),
        # not always a Latin transliteration.
        "कैसे हो", "कैसे हैं", "क्या हाल",
    )
    bare_greetings = {"hi", "hello", "hey", "namaste", "नमस्ते"}
    if check_in in bare_greetings or any(p in check_in for p in greeting_phrases):
        # Shorter on purpose -- this is spoken aloud via TTS on every single
        # greeting, and the original 3-sentence version added several real
        # seconds of speaking time on top of an already-slow voice pipeline.
        return "Online and steady, Sir. What can I do for you?"

    from openjarvis.one_agents.runtime import AGENTS, enqueue_job, list_jobs

    def _match_agent_id(text: str) -> str | None:
        return next(
            (agent_id for agent_id, value in AGENTS.items() if re.search(rf"\b{re.escape(value['name'].lower())}\b", text)),
            None,
        )

    def _friendly_agent_status(agent_id: str, name: str) -> str:
        """Phrase one agent's latest run as a plain sentence — never a raw job ID or bare percent."""
        jobs = [job for job in list_jobs(30) if job["agent_id"] == agent_id]
        if not jobs:
            return f"{name} has not run yet."
        latest = jobs[0]
        status = latest["status"]
        if status == "running":
            return f"{name} is running right now, about {latest['progress']}% through."
        if status == "queued":
            return f"{name} is queued and hasn't started running yet."
        if status == "failed":
            return f"{name}'s last run failed. I have not retried it automatically — want me to queue it again?"
        if status != "completed":
            return f"{name} is currently {status}."
        try:
            result = json.loads(latest.get("result") or "{}")
        except json.JSONDecodeError:
            return f"{name} completed its last run, but the saved result could not be read."
        if agent_id == "alfa":
            top = result.get("top_opportunities") or []
            headline = top[0].get("title", "No qualified lead") if top else "No qualified lead"
            packaged = sum(1 for item in top if item.get("outreach_message"))
            mrr = result.get("mrr_pipeline_monthly", 0)
            mrr_part = f" Potential retainer pipeline is ${mrr:,} a month if those convert." if mrr else ""
            return (
                f"ALFA scanned {result.get('scanned', 0)} public posts and found {result.get('qualified', 0)} qualified "
                f"service opportunities. Estimated one-time pipeline is "
                f"${result.get('estimated_usd_low', 0):,}-${result.get('estimated_usd_high', 0):,}.{mrr_part} "
                f"{packaged} leads have a service, price, and outreach draft ready in the dashboard. "
                f"Top lead: {headline}. This is pipeline value, not earned revenue — nothing is sent until you approve it."
            )
        if agent_id == "jobhunt":
            new_briefs = result.get("new_briefs", 0)
            duplicates = result.get("duplicates", 0)
            skipped_old = result.get("skipped_old", 0)
            extra = f" and {skipped_old} older posting{'s' if skipped_old != 1 else ''}" if skipped_old else ""
            return (
                f"JOBHUNT reviewed the inbox and prepared {new_briefs} new opportunity brief"
                f"{'s' if new_briefs != 1 else ''}, skipping {duplicates} already-tracked duplicate"
                f"{'s' if duplicates != 1 else ''}{extra}. "
                "Everything is waiting in your review folder — nothing was applied or sent on its own."
            )
        return f"{name}'s last run completed successfully."

    status_agent = _match_agent_id(lowered)

    # Confirmed live (2026-07-19): "Why IA got failed?" named the agent but
    # used none of the keywords the status branch below checks for
    # ("fail"/"why"/"wrong"/"error"/"issue"/"problem" aren't status/update/
    # progress/etc), so it fell through the ReAct loop and hallucinated "the
    # memory backend is not configured" -- a real limitation elsewhere in
    # the system, but not the actual reason anything failed, and not
    # grounded in this agent's real job history at all. Every failed job
    # already has a real reason recorded (fail_job() writes it to the
    # `error` column) -- this answers directly from that instead of asking
    # the LLM to guess. Uses list_agent_jobs(), not list_jobs(), because a
    # busy agent (ALFA at 352+ jobs) crowds a quieter agent's failures clean
    # out of list_jobs()'s global recent-N window.
    failure_phrases = ("fail", "wrong", "error", "issue", "problem", "why")
    if status_agent and any(p in lowered for p in failure_phrases):
        from openjarvis.one_agents.runtime import list_agent_jobs

        name = AGENTS[status_agent]["name"]
        agent_jobs = list_agent_jobs(status_agent, 20)
        failed = [job for job in agent_jobs if job["status"] == "failed"]
        if not failed:
            return f"{name} has no failed runs on record, Sir."
        parts = []
        for job in failed[:5]:
            reason = (job.get("error") or "").strip() or "no error detail was recorded"
            # Some errors (e.g. an ffmpeg filter-graph failure) are raw
            # multi-line stack dumps -- fine to read on a screen, unbearable
            # for TTS to speak aloud. First line only, capped, since this
            # whole response is spoken.
            reason = reason.split("\n", 1)[0].strip()
            if len(reason) > 180:
                reason = reason[:177].rstrip() + "..."
            when = (job.get("updated_at") or "")[:16].replace("T", " ")
            parts.append(f"{when} -- {reason}" if when else reason)
        count_word = "failure" if len(parts) == 1 else "failures"
        return (
            f"{name}'s last {len(parts)} {count_word}, most recent first, Sir: "
            + "; then before that, ".join(parts)
        )

    if status_agent and re.search(
        r"\b(status|update|progress|found|find|result|results|lead|leads|opportunit|achiev|revenue)\w*\b", lowered
    ):
        return _friendly_agent_status(status_agent, AGENTS[status_agent]["name"])

    # Confirmed live (2026-07-19, traces.db traces 1f38a44b0264456c and
    # 125bd0a4a14b49ee): "How are the agents doing?" has no keyword this
    # function already checks for (no agent name, no "status"/"queue"/"job"/
    # "history", no dispatch verb), so it fell through to the full ReAct
    # loop every time. Direct repro testing (isolated agent.run() calls
    # against the real llama3.1:8b/Ollama, real tools, real bus) showed the
    # 8B model is simply unreliable here: sometimes it calls agent_network
    # stats correctly and narrates the real numbers, but other times -- same
    # code, same model, just normal LLM sampling variance -- it convinces
    # itself the tool "reached its polling limit" (a total fabrication; nothing
    # in this codebase rate-limits tool calls) and burns all 10 turns before
    # inventing an ungrounded answer. A collective agent-status question is
    # exactly the kind of deterministic, always-correct-if-computed-in-code
    # request the greeting fast path above already exists for -- so handle it
    # the same way instead of gambling on the ReAct loop every time.
    agents_collective_phrases = (
        "how are the agents", "how are agents", "how re the agents", "how re agents",
        "agents doing", "agent stats", "agents stats", "stats review",
        "agent status", "agents status", "status of the agents", "status of agents",
    )
    if not status_agent and any(p in check_in for p in agents_collective_phrases):
        from openjarvis.one_agents.runtime import agent_stats

        holistic = bool(re.search(r"\b(holistic|detail|deep dive|full|breakdown)\w*\b", lowered))
        stats = agent_stats()
        active = [s for s in stats if s["total_jobs"] > 0]
        idle = [s for s in stats if s["total_jobs"] == 0]
        if not active:
            return "No agent activity recorded yet, Sir."
        parts = []
        for s in active:
            common = max(s["status_counts"], key=s["status_counts"].get) if s["status_counts"] else "idle"
            if holistic:
                breakdown = ", ".join(f"{v} {k}" for k, v in s["status_counts"].items())
                duration = f", averaging {s['avg_duration_seconds']:.0f}s per job" if s["avg_duration_seconds"] else ""
                parts.append(f"{s['name']} has run {s['total_jobs']} jobs ({breakdown}){duration}")
            else:
                parts.append(f"{s['name']} is mostly {common} across {s['total_jobs']} jobs")
        summary = "; ".join(parts)
        idle_names = ", ".join(s["name"] for s in idle)
        idle_part = f" {idle_names} {'have' if len(idle) != 1 else 'has'} not run yet." if idle_names else ""
        return f"Agent status, Sir: {summary}.{idle_part}"

    obsidian_match = re.search(r"\b(?:search|find|look\s+in)\s+(?:my\s+)?obsidian(?:\s+for)?\s+(.+)", lowered)
    if obsidian_match:
        from openjarvis.one_agents.obsidian import search_obsidian

        try:
            findings = search_obsidian(obsidian_match.group(1), 2)
        except ValueError as exc:
            return str(exc)
        if not findings:
            return "I found no matching notes in your Obsidian memory."
        lines = [f"{item['title']}: {item['snippet'][:140]}" for item in findings]
        return "Obsidian memory found:\n" + "\n".join(lines)

    if re.search(r"\b(queue|job|history|status)\b", lowered):
        jobs = list_jobs(8)
        if not jobs:
            return "The ONE agent queue is empty."
        summary = "; ".join(
            f"{AGENTS.get(job['agent_id'], {}).get('name', job['agent_id'])} is {job['status']}"
            + (f" ({job['progress']}% done)" if job["status"] == "running" else "")
            for job in jobs
        )
        return f"Here's what's in the queue: {summary}."

    if re.search(r"\b(list|show|which)\b.*\bagents?\b", lowered):
        roster = ", ".join(value["name"] for value in AGENTS.values())
        return f"ONE agent network: {roster}."

    selected = _match_agent_id(lowered)
    has_dispatch_verb = bool(
        re.search(r"\b(activate|run|start|dispatch|ask|tell|prepare|plan|create|generate|publish|post)\b", lowered)
    )
    if not selected or not has_dispatch_verb:
        return None

    mode = "plan"
    publish_is_negated = bool(
        re.search(r"\b(do not|don't|dont|without)\s+(publish|post|publishing|posting)\b", lowered)
    )
    if re.search(r"\b(publish|post)\b", lowered) and not publish_is_negated:
        mode = "publish"
    elif re.search(r"\b(execute|generate|create|run)\b", lowered) and not re.search(r"\b(plan|draft|prepare)\b", lowered):
        mode = "execute"

    # Heavy tier is opt-in only — escalating to the cloud Nemotron model costs
    # NVIDIA NIM credits, so it must be asked for explicitly, not inferred.
    tier = "heavy" if re.search(r"\b(heavy|deep dive|think hard|escalate|use nemotron)\b", lowered) else "fast"

    job = enqueue_job(selected, clean, mode, tier)
    return (
        f"{AGENTS[selected]['name']} queued in {mode} mode"
        + (" on the heavy model" if tier == "heavy" else "")
        + f". Job ID: {job['id']}. I will not claim completion until its queue status confirms it."
    )


def _save_exchange_to_obsidian(user_text: str, assistant_text: str) -> None:
    """Best-effort: log a conversational turn into the Obsidian vault.

    This is what lets ONE "remember" Vineet's conversations over time —
    separate from the sqlite-backed semantic memory used for RAG context.
    Silent no-op if Obsidian isn't connected or the text is empty; never
    raises into the request path.
    """
    failure_markers = (
        "maximum turns reached without a final answer",
        "expected ':' or ']' after array element",
        "model did not return valid json",
    )
    cleaned_reply = assistant_text.strip()
    if (
        not user_text.strip()
        or not cleaned_reply
        or any(marker in cleaned_reply.lower() for marker in failure_markers)
    ):
        return
    try:
        from openjarvis.one_agents.obsidian import obsidian_status, remember_exchange

        if obsidian_status().get("connected"):
            remember_exchange(user_text, assistant_text)
    except Exception:
        logging.getLogger("openjarvis.server").debug(
            "Auto-save exchange to Obsidian failed", exc_info=True
        )


def _extract_response_content(response: Any) -> str:
    try:
        return response.choices[0].message.content or ""
    except Exception:
        return ""


def _wrap_stream_with_memory(response: StreamingResponse, user_text: str) -> StreamingResponse:
    """Re-emit an SSE stream byte-for-byte, then auto-save the full reply
    to Obsidian once the stream completes. Buffering happens as a side
    effect alongside the yield, never delaying or altering what the client
    receives.
    """
    original_iterator = response.body_iterator

    async def generate():
        collected: list[str] = []
        async for chunk in original_iterator:
            yield chunk
            try:
                text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
                for line in text.splitlines():
                    line = line.strip()
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    payload = json.loads(line[len("data: "):])
                    for choice in payload.get("choices", []):
                        piece = (choice.get("delta") or {}).get("content")
                        if piece:
                            collected.append(piece)
            except Exception:
                continue
        _save_exchange_to_obsidian(user_text, "".join(collected))

    response.body_iterator = generate()
    return response


def _one_command_response(model: str, content: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        model=model,
        choices=[Choice(message=ChoiceMessage(content=content))],
        usage=UsageInfo(),
    )


def _one_command_stream(model: str, content: str) -> StreamingResponse:
    async def generate():
        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        first = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(role="assistant", content=content))],
        )
        final = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(), finish_reason="stop")],
        )
        yield f"data: {json.dumps(first.model_dump())}\n\n"
        yield f"data: {json.dumps(final.model_dump())}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


def _to_messages(chat_messages) -> list[Message]:
    """Convert Pydantic ChatMessage objects to core Message objects."""
    messages = []
    for m in chat_messages:
        role = Role(m.role) if m.role in {r.value for r in Role} else Role.USER
        messages.append(
            Message(
                role=role,
                content=m.content or "",
                name=m.name,
                tool_call_id=m.tool_call_id,
            )
        )
    return messages


def _ensure_identity_prompt(messages: list[Message], app_config) -> list[Message]:
    """Prepend OpenJarvis's identity system prompt when the client omits one.

    The desktop UI's chat backend posts only user/assistant turns to
    ``/v1/chat/completions`` (see ``frontend/.../Chat/InputArea.tsx``), so
    nothing grounds the model's identity. Without a system prompt the model
    answers from its training identity (e.g. "I'm Claude", "I am Qwen"),
    which is what #540 reported. The CLI paths inject this via
    ``SystemPromptBuilder`` / ``BaseAgent``; the engine-direct server paths
    did not. This mirrors the agent fallback in ``agents/_stubs.py``.

    If any message already carries a system role, the caller has supplied
    their own grounding and we leave the list untouched (no double-prompting).

    Resolution of the identity text: ``app_config.agent.default_system_prompt``
    when a config is wired onto ``app.state``; otherwise fall back to
    ``load_config()``. Config resolution is wrapped so a broken/missing
    config degrades to "no injection" rather than crashing the endpoint, but
    the failure is logged (per REVIEW.md — never silently swallow).
    """
    if any(m.role == Role.SYSTEM for m in messages):
        return messages

    prompt = ""
    try:
        if app_config is not None:
            prompt = app_config.agent.default_system_prompt or ""
        else:
            from openjarvis.core.config import load_config

            prompt = load_config().agent.default_system_prompt or ""
    except Exception:
        logging.getLogger("openjarvis.server").debug(
            "Identity system prompt resolution failed; "
            "serving request without identity grounding",
            exc_info=True,
        )
        return messages

    if not prompt:
        return messages

    return [Message(role=Role.SYSTEM, content=prompt), *messages]


@router.post("/v1/chat/completions")
async def chat_completions(request_body: ChatCompletionRequest, request: Request):
    """Handle chat completion requests (streaming and non-streaming)."""
    engine = request.app.state.engine
    agent = getattr(request.app.state, "agent", None)
    model = request_body.model

    latest_user_text = next(
        (m.content for m in reversed(request_body.messages) if m.role == "user" and m.content),
        "",
    )
    deterministic_reply = _one_agent_command(latest_user_text)
    if deterministic_reply:
        _save_exchange_to_obsidian(latest_user_text, deterministic_reply)
        if request_body.stream:
            return _one_command_stream(model, deterministic_reply)
        return _one_command_response(model, deterministic_reply)

    # Inject memory context into messages before dispatching
    config = getattr(request.app.state, "config", None)
    memory_backend = getattr(request.app.state, "memory_backend", None)
    if (
        config is not None
        and memory_backend is not None
        and config.agent.context_from_memory
        and request_body.messages
    ):
        try:
            from openjarvis.tools.storage.context import ContextConfig, inject_context

            # Extract query from the last user message
            query_text = ""
            for m in reversed(request_body.messages):
                if m.role == "user" and m.content:
                    query_text = m.content
                    break

            if query_text:
                messages = _to_messages(request_body.messages)
                ctx_cfg = ContextConfig(
                    top_k=config.memory.context_top_k,
                    min_score=config.memory.context_min_score,
                    max_context_tokens=config.memory.context_max_tokens,
                )
                enriched = inject_context(
                    query_text,
                    messages,
                    memory_backend,
                    config=ctx_cfg,
                )
                # Rebuild request messages from enriched Message objects
                if len(enriched) > len(messages):
                    from openjarvis.server.models import ChatMessage

                    new_msgs = []
                    for msg in enriched:
                        new_msgs.append(
                            ChatMessage(
                                role=msg.role.value,
                                content=msg.content,
                                name=msg.name,
                                tool_call_id=getattr(msg, "tool_call_id", None),
                            )
                        )
                    request_body.messages = new_msgs
        except Exception:
            logging.getLogger("openjarvis.server").debug(
                "Memory context injection failed",
                exc_info=True,
            )

    # Also ground replies in Vineet's own Obsidian vault notes — a separate,
    # keyword-search store from the sqlite semantic memory above. Appended
    # onto the latest user message's own content (not a new system message)
    # so this can never suppress `_ensure_identity_prompt`'s grounding the
    # way an extra system-role message would (see that function's
    # "no double-prompting" guard).
    try:
        from openjarvis.one_agents.obsidian import obsidian_status, search_obsidian

        if latest_user_text and obsidian_status().get("connected"):
            obsidian_notes = search_obsidian(latest_user_text, limit=3)
            if obsidian_notes:
                snippet_lines = [
                    f"- {note['title']}: {note['snippet'][:220]}" for note in obsidian_notes
                ]
                memory_note = (
                    "\n\n[ONE memory — relevant notes from your Obsidian vault; "
                    "use naturally, don't cite this like a search result]\n"
                    + "\n".join(snippet_lines)
                )
                for m in reversed(request_body.messages):
                    if m.role == "user" and m.content:
                        m.content = m.content + memory_note
                        break
    except ValueError:
        pass
    except Exception:
        logging.getLogger("openjarvis.server").debug(
            "Obsidian context injection failed",
            exc_info=True,
        )

    # Run complexity analysis on the last user message
    complexity_info = None
    query_text_for_complexity = ""
    for m in reversed(request_body.messages):
        if m.role == "user" and m.content:
            query_text_for_complexity = m.content
            break
    if query_text_for_complexity:
        try:
            from openjarvis.learning.routing.complexity import (
                adjust_tokens_for_model,
                score_complexity,
            )

            cr = score_complexity(query_text_for_complexity)
            suggested = adjust_tokens_for_model(
                cr.suggested_max_tokens,
                model,
            )
            complexity_info = ComplexityInfo(
                score=cr.score,
                tier=cr.tier,
                suggested_max_tokens=suggested,
            )
            # Bump max_tokens when complexity suggests more than what
            # the client requested — never reduce below the request value.
            if suggested > request_body.max_tokens:
                request_body.max_tokens = suggested
        except Exception:
            logging.getLogger("openjarvis.server").debug(
                "Complexity analysis failed",
                exc_info=True,
            )

    # Confirmed live (2026-07-19): general/open-ended queries that fall
    # through every deterministic fast path above (_one_agent_command) were
    # landing in the local llama3.1:8b ReAct loop, which either hallucinated
    # an unrelated answer ("can you build a agent for me?" -> a fabricated
    # Obsidian vault path) or burned 60-120s before "Maximum turns reached
    # without a final answer." Per Vineet's explicit instruction: give
    # anything ONE's local model can't confidently handle a path to a real
    # cloud model instead of gambling on the local ReAct loop every time.
    # cloud_escalation_model (set once at server startup -- cli/serve.py) is
    # a fast cloud model (Claude Haiku, falling back to GPT-4o-mini). Routed
    # through _run_cloud_tool_loop's native function-calling (web_search +
    # get_current_time) so it can actually answer real-time/factual
    # questions ("how's the weather") instead of just replying faster with
    # the same "I don't have a tool for that" the local model gives. Falls
    # back to the local agent path on any failure (network down, rate
    # limited, etc.), and stays on the local agent entirely when no cloud
    # key is configured, so an offline-only setup is unaffected. Haiku over
    # Sonnet/Opus on purpose: latency-first fallback, not a reasoning-heavy
    # one.
    cloud_escalation_model = getattr(request.app.state, "cloud_escalation_model", None)

    if request_body.stream:
        # When the client passes `tools`, stream the model's raw
        # OpenAI-compat function-calling decision directly from the engine
        # (bypassing the agent) — the streaming mirror of the non-streaming
        # #454 fix.  Routing tools through the agent stream bridge ignored
        # `request_body.tools`, ran the agent's own tool loop, and
        # word-split generic filler content into fake token deltas, so the
        # caller's tool_calls were dropped entirely (the streaming analog of
        # #414).
        if request_body.tools:
            return _wrap_stream_with_memory(
                await _handle_stream_tools(
                    engine, model, request_body, complexity_info, app_config=config
                ),
                latest_user_text,
            )
        if cloud_escalation_model:
            try:
                return _wrap_stream_with_memory(
                    await _handle_cloud_escalation_stream(
                        engine,
                        cloud_escalation_model,
                        request_body,
                        complexity_info,
                        app_config=config,
                    ),
                    latest_user_text,
                )
            except Exception:
                logging.getLogger("openjarvis.server").warning(
                    "Cloud escalation stream to %s failed, falling back to local agent",
                    cloud_escalation_model,
                    exc_info=True,
                )
        # When no client tools were supplied (the desktop chat UI's normal
        # case) and an agent is configured, route through the agent instead
        # of the bare engine. The agent runs the real tool-execution loop
        # gated by `[agent] tools` in config.toml — the bare engine stream
        # below never executes tools at all, so a chat request like
        # "generate an image of X" would either get a flat refusal, or (if
        # tools were naively force-injected here) stream back an
        # unexecuted tool_call the frontend has no way to act on. See
        # `_handle_agent_stream` for the trade-off this implies (no
        # token-by-token typing for agent-routed turns).
        if agent is not None:
            return _wrap_stream_with_memory(
                await _handle_agent_stream(
                    agent,
                    model,
                    request_body,
                    complexity_info,
                    trace_store=getattr(request.app.state, "trace_store", None),
                    bus=getattr(request.app.state, "bus", None),
                ),
                latest_user_text,
            )
        return _wrap_stream_with_memory(
            await _handle_stream(
                engine,
                model,
                request_body,
                complexity_info,
                trace_store=getattr(request.app.state, "trace_store", None),
                app_config=config,
            ),
            latest_user_text,
        )

    # Non-streaming: cloud escalation first (see comment above), then agent
    # if available, otherwise direct engine call.
    #
    # EXCEPTION: when the client explicitly passed `tools`, they're asking
    # for raw OpenAI-compat function-calling — return the model's
    # tool_call decision verbatim. Routing through `_handle_agent` would
    # call `agent.run(input_text)`, which IGNORES `request_body.tools`,
    # runs the agent's own internal tool loop with its own (different)
    # tool spec, and returns only `result.content` — so the model's
    # tool_calls vanish and the user sees a generic acknowledgement
    # (e.g. "Understood. If you have another request...") that the
    # agent's re-prompted LLM produced. See #414.
    #
    # If a future caller needs agent orchestration WITH client-supplied
    # tools (e.g. injecting MCP tools through this endpoint and wanting
    # the agent to execute them), add an explicit opt-in header rather
    # than removing this guard — silent re-routing is what produced #414.
    if cloud_escalation_model and not request_body.tools:
        try:
            cloud_response = _handle_cloud_escalation(
                engine,
                cloud_escalation_model,
                request_body,
                complexity_info,
                app_config=config,
            )
            _save_exchange_to_obsidian(latest_user_text, _extract_response_content(cloud_response))
            return cloud_response
        except Exception:
            logging.getLogger("openjarvis.server").warning(
                "Cloud escalation to %s failed, falling back to local agent",
                cloud_escalation_model,
                exc_info=True,
            )

    if agent is not None and not request_body.tools:
        agent_response = _handle_agent(
            agent,
            model,
            request_body,
            complexity_info,
            trace_store=getattr(request.app.state, "trace_store", None),
            bus=getattr(request.app.state, "bus", None),
        )
        _save_exchange_to_obsidian(latest_user_text, _extract_response_content(agent_response))
        return agent_response

    bus = getattr(request.app.state, "bus", None)
    direct_response = _handle_direct(
        engine,
        model,
        request_body,
        bus=bus,
        complexity_info=complexity_info,
        app_config=config,
    )
    _save_exchange_to_obsidian(latest_user_text, _extract_response_content(direct_response))
    return direct_response


def _cloud_escalation_tools():
    """Tool instances the cloud escalation loop can call.

    Deliberately small and separate from the local agent's `[agent] tools`
    list in config.toml -- Claude/GPT rarely need more than one web_search
    call for a real-time factual question, and a smaller tool list keeps
    the round-trip fast.
    """
    from openjarvis.tools.datetime_tool import GetCurrentTimeTool
    from openjarvis.tools.web_search import WebSearchTool

    return [WebSearchTool(), GetCurrentTimeTool()]


def _run_cloud_tool_loop(
    engine,
    model: str,
    messages: list[Message],
    *,
    temperature: float,
    max_tokens: int,
    max_rounds: int = 3,
) -> dict[str, Any]:
    """Native function-calling loop for the cloud escalation model.

    NOT NativeReActAgent's text-based Thought/Action/Action-Input protocol.
    Confirmed live (2026-07-19) that Claude Haiku does not reliably follow
    that scaffolding -- it emitted its own "<function_calls>...
    </function_calls>" pseudo-text instead, which the ReAct parser never
    recognized as an action, so web_search never actually ran and the raw
    scaffolding leaked into the reply verbatim. Claude/GPT both have real
    native tool-calling already wired in engine/cloud.py
    (_convert_tools_to_anthropic converts OpenAI-format tool schemas to
    Anthropic's tool_use format, and _prepare_anthropic_messages round-trips
    tool_use/tool_result blocks correctly) -- this uses that directly via
    `engine.generate(messages, tools=...)`, the same mechanism
    `_handle_direct` already uses for client-supplied tools.
    """
    from openjarvis.tools._stubs import ToolExecutor

    tool_instances = _cloud_escalation_tools()
    tools_schema = [t.to_openai_function() for t in tool_instances]
    executor = ToolExecutor(tools=tool_instances)

    msgs = list(messages)
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    result: dict[str, Any] = {}
    for _round in range(max_rounds):
        result = engine.generate(
            msgs,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools_schema,
        )
        usage = result.get("usage", {})
        for k in total_usage:
            total_usage[k] += usage.get(k, 0)

        tool_calls = result.get("tool_calls") or []
        if not tool_calls:
            break

        msgs.append(
            Message(
                role=Role.ASSISTANT,
                content=result.get("content", ""),
                tool_calls=[
                    ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                    for tc in tool_calls
                ],
            )
        )
        for tc in tool_calls:
            tool_result = executor.execute(
                ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
            )
            msgs.append(
                Message(
                    role=Role.TOOL,
                    content=(tool_result.content or "")[:4000],
                    tool_call_id=tc["id"],
                )
            )

    result["usage"] = total_usage
    return result


def _handle_cloud_escalation(
    engine,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
    app_config=None,
) -> ChatCompletionResponse:
    """Non-streaming cloud escalation: native tool loop, then final answer."""
    messages = _to_messages(req.messages)
    messages = _ensure_identity_prompt(messages, app_config)
    result = _run_cloud_tool_loop(
        engine,
        model,
        messages,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
    )
    usage = result.get("usage", {})
    return ChatCompletionResponse(
        model=model,
        choices=[
            Choice(
                message=ChoiceMessage(role="assistant", content=result.get("content", "")),
                finish_reason=result.get("finish_reason", "stop"),
            )
        ],
        usage=UsageInfo(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        ),
        complexity=complexity_info,
    )


async def _handle_cloud_escalation_stream(
    engine,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
    app_config=None,
) -> StreamingResponse:
    """Streaming cloud escalation.

    The tool loop itself (0-2 rounds of a blocking `engine.generate` call)
    isn't token-streamed -- it resolves fully server-side first, same as
    the deterministic command replies below. Only the final answer is
    emitted as a single SSE chunk. True token-by-token streaming through a
    multi-turn native tool-calling loop is real added complexity for a
    result that, per the numbers already measured this session (a couple
    seconds end to end), the user won't perceive as non-streamed anyway.
    """
    messages = _to_messages(req.messages)
    messages = _ensure_identity_prompt(messages, app_config)
    result = _run_cloud_tool_loop(
        engine,
        model,
        messages,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
    )
    content = result.get("content", "")

    async def generate():
        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        first = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(role="assistant", content=content))],
        )
        final = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(), finish_reason="stop")],
        )
        yield f"data: {json.dumps(first.model_dump())}\n\n"
        yield f"data: {json.dumps(final.model_dump())}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


def _handle_direct(
    engine,
    model: str,
    req: ChatCompletionRequest,
    bus=None,
    complexity_info=None,
    app_config=None,
) -> ChatCompletionResponse:
    """Direct engine call without agent."""
    messages = _to_messages(req.messages)
    messages = _ensure_identity_prompt(messages, app_config)
    kwargs: dict[str, Any] = {}
    if req.tools:
        kwargs["tools"] = req.tools
    if bus:
        from openjarvis.telemetry.instrumented_engine import InstrumentedEngine
        from openjarvis.telemetry.wrapper import instrumented_generate

        # `app.state.engine` may already be an InstrumentedEngine (the
        # common case when telemetry is wired in). If we then wrap it
        # with `instrumented_generate`, BOTH layers fire a
        # TELEMETRY_RECORD per call:
        #
        #   - InstrumentedEngine.generate() publishes a FULL record
        #     (energy_joules, GPU stats, token_counting_version, ...).
        #   - instrumented_generate() publishes a BARE record (timing +
        #     tokens only; no energy meter, no version stamp).
        #
        # The doubled count was the dominant driver of the bimodal
        # Wh/token distribution on the public leaderboard.
        #
        # The fix below is NOT "unwrap and call instrumented_generate":
        # that would have replaced "doubled records" with "every
        # request emits only a bare record with no energy / no version",
        # which the leaderboard's `current_methodology_only=True` filter
        # would then drop entirely. Instead, when the engine is already
        # an InstrumentedEngine, skip the wrapper and call `generate`
        # directly — InstrumentedEngine publishes the full per-record
        # event itself with energy + version intact. Only fall back to
        # the lightweight wrapper for engines that aren't already
        # instrumented.
        if isinstance(engine, InstrumentedEngine):
            result = engine.generate(
                messages,
                model=model,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                **kwargs,
            )
        else:
            result = instrumented_generate(
                engine,
                messages,
                model=model,
                bus=bus,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                **kwargs,
            )
    else:
        result = engine.generate(
            messages,
            model=model,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            **kwargs,
        )
    content = result.get("content", "")
    usage = result.get("usage", {})

    choice_msg = ChoiceMessage(role="assistant", content=content)
    # Include tool calls if present
    tool_calls = result.get("tool_calls")
    if tool_calls:
        choice_msg.tool_calls = [
            {
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": tc.get("name", ""),
                    "arguments": tc.get("arguments", "{}"),
                },
            }
            for tc in tool_calls
        ]

    return ChatCompletionResponse(
        model=model,
        choices=[
            Choice(
                message=choice_msg,
                finish_reason=result.get("finish_reason", "stop"),
            )
        ],
        usage=UsageInfo(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        ),
        complexity=complexity_info,
    )


def _handle_agent(
    agent,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
    *,
    trace_store=None,
    bus=None,
) -> ChatCompletionResponse:
    """Run through agent.

    When *trace_store* is set, the agent run is wrapped in a
    ``TraceCollector`` (mirroring ``system/orchestrator.py``) so every
    completion records a ``Trace`` to ``traces.db``. Previously this endpoint
    called ``agent.run()`` raw, so the server never produced traces:
    ``traces.db`` stayed empty and spec_search's cold-start gate
    (``check_readiness``, min 20 traces) could never open.
    """
    from openjarvis.agents._stubs import AgentContext

    # Build context from prior messages
    ctx = AgentContext()
    if len(req.messages) > 1:
        prior = _to_messages(req.messages[:-1])
        for m in prior:
            ctx.conversation.add(m)

    # Last message is the input
    input_text = req.messages[-1].content if req.messages else ""

    # Override agent model for this request if the caller specified one
    original_model = agent._model
    if model:
        agent._model = model
    try:
        if trace_store is not None:
            from openjarvis.traces.collector import TraceCollector

            collector = TraceCollector(agent, store=trace_store, bus=bus)
            result = collector.run(input_text, context=ctx)
        else:
            result = agent.run(input_text, context=ctx)
    finally:
        agent._model = original_model

    usage = UsageInfo(
        prompt_tokens=result.metadata.get("prompt_tokens", 0),
        completion_tokens=result.metadata.get("completion_tokens", 0),
        total_tokens=result.metadata.get("total_tokens", 0),
    )

    # Include audio metadata if the agent produced audio (e.g. morning digest)
    audio_meta = None
    audio_path = result.metadata.get("audio_path", "")
    if audio_path:
        from pathlib import Path

        from openjarvis.server.models import AudioMeta

        if Path(audio_path).exists():
            audio_meta = AudioMeta(url="/api/digest/audio")

    return ChatCompletionResponse(
        model=model,
        choices=[
            Choice(
                message=ChoiceMessage(
                    role="assistant",
                    content=result.content,
                    audio=audio_meta,
                ),
                finish_reason="stop",
            )
        ],
        usage=usage,
        complexity=complexity_info,
    )


async def _handle_agent_stream(
    agent,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
    *,
    trace_store=None,
    bus=None,
):
    """Stream-shaped wrapper around the agent path.

    `_handle_stream` (the historical default for `stream:true`) streams
    straight from the engine and never executes tools — by design, per its
    own docstring. That meant a live chat request like "generate an image
    of X" always fell through to the model just refusing, since the agent
    (which runs the real tool-execution loop gated by `[agent] tools` in
    config.toml) was bypassed for every streaming turn. This wrapper runs
    the same `_handle_agent` call used by the non-streaming path — which
    blocks until the agent's full answer (including any tool calls) is
    ready — then emits that result as SSE chunks so the existing streaming
    frontend code keeps working unchanged.

    Trade-off, accepted deliberately: no token-by-token typing effect for
    agent-routed turns (the whole answer arrives in one chunk after the
    agent finishes) — chosen over a larger, riskier rewrite that would
    detect tool_calls mid-stream and execute them while preserving live
    token output.
    """
    response = _handle_agent(
        agent, model, req, complexity_info, trace_store=trace_store, bus=bus
    )
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    content = response.choices[0].message.content if response.choices else ""
    # Note: DeltaMessage has no `audio` field (only ChoiceMessage does), so
    # any audio metadata from an agent run (e.g. morning digest) doesn't
    # carry over here — out of scope for this fix, which targets text/tool
    # turns (image_generate, video_generate) specifically.

    async def generate():
        first_chunk = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(role="assistant", content=content))],
        )
        yield f"data: {first_chunk.model_dump_json()}\n\n"

        finish_chunk = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(), finish_reason="stop")],
        )
        finish_dict = json.loads(finish_chunk.model_dump_json())
        if response.usage is not None:
            finish_dict["usage"] = response.usage.model_dump()
        if complexity_info is not None:
            finish_dict["complexity"] = complexity_info.model_dump()
        yield f"data: {json.dumps(finish_dict)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


async def _handle_stream_tools(
    engine,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
    *,
    app_config=None,
):
    """Stream a raw OpenAI-compat function-calling response via SSE.

    Used when the client passes `tools` together with `stream:true`.  Sources
    tool_calls from ``engine.stream_full()`` (which forwards the tools to the
    backend and parses tool_calls out of the streamed response) and emits them
    as SSE deltas, bypassing the agent entirely.  This is the streaming mirror
    of the non-streaming ``_handle_direct`` tool path.

    Engines without a tool-aware ``stream_full`` override fall back to the
    base-class default (content tokens + a ``stop`` finish_reason, no
    tool_calls) — identical to the prior plain-stream behaviour, so this never
    regresses non-tool-capable engines.
    """
    from openjarvis.server.cloud_router import is_cloud_model

    messages = _to_messages(req.messages)
    messages = _ensure_identity_prompt(messages, app_config)
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    use_cloud = is_cloud_model(model)

    async def generate():
        # Send the role chunk first (OpenAI convention).
        first_chunk = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(role="assistant"))],
        )
        yield f"data: {first_chunk.model_dump_json()}\n\n"

        finish_reason = "stop"
        try:
            async for sc in engine.stream_full(
                messages,
                model=model,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                tools=req.tools,
            ):
                if sc.content:
                    content_chunk = ChatCompletionChunk(
                        id=chunk_id,
                        model=model,
                        choices=[StreamChoice(delta=DeltaMessage(content=sc.content))],
                    )
                    yield f"data: {content_chunk.model_dump_json()}\n\n"
                if sc.tool_calls:
                    tc_chunk = ChatCompletionChunk(
                        id=chunk_id,
                        model=model,
                        choices=[
                            StreamChoice(delta=DeltaMessage(tool_calls=sc.tool_calls))
                        ],
                    )
                    yield f"data: {tc_chunk.model_dump_json()}\n\n"
                if sc.finish_reason:
                    finish_reason = sc.finish_reason
        except Exception as exc:
            import logging

            logging.getLogger("openjarvis.server").error(
                "Tool stream error: %s",
                exc,
                exc_info=True,
            )
            error_chunk = ChatCompletionChunk(
                id=chunk_id,
                model=model,
                choices=[
                    StreamChoice(
                        delta=DeltaMessage(
                            content=f"\n\nError during generation: {exc}",
                        ),
                        finish_reason="stop",
                    )
                ],
            )
            yield f"data: {error_chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
            return

        import json as _json

        finish_data = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(), finish_reason=finish_reason)],
        )
        finish_dict = _json.loads(finish_data.model_dump_json())
        # Tag the finish chunk with the engine label, matching _handle_stream
        # so UI/telemetry consumers see the same field on the tools path.
        finish_dict.setdefault("telemetry", {})
        finish_dict["telemetry"]["engine"] = "cloud" if use_cloud else "ollama"
        if complexity_info is not None:
            finish_dict["complexity"] = complexity_info.model_dump()
        yield f"data: {_json.dumps(finish_dict)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


async def _handle_stream(
    engine,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
    *,
    trace_store=None,
    app_config=None,
):
    """Stream response using SSE format.

    This path streams straight from the engine, bypassing the agent /
    ``TraceCollector``. When *trace_store* is set we accumulate the streamed
    tokens and record a minimal ``Trace`` once the stream completes
    successfully — otherwise streamed chats (the desktop GUI's main path)
    would never populate ``traces.db``.
    """
    import time

    from openjarvis.server.cloud_router import (
        is_cloud_model,
        stream_cloud,
        stream_local,
    )

    messages = _to_messages(req.messages)
    messages = _ensure_identity_prompt(messages, app_config)
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    # Last user message — recorded as the trace query.
    query_text = ""
    for _m in reversed(req.messages):
        if _m.role == "user" and _m.content:
            query_text = _m.content
            break

    # Route directly to the right backend — bypasses engine routing entirely
    # so broken MultiEngine state can never misdirect requests.
    use_cloud = is_cloud_model(model)

    async def generate():
        started_at = time.time()
        full_content = ""
        # Send role chunk first
        first_chunk = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[
                StreamChoice(
                    delta=DeltaMessage(role="assistant"),
                )
            ],
        )
        yield f"data: {first_chunk.model_dump_json()}\n\n"

        try:
            # Cloud models → direct cloud API (reads keys from disk).
            # Local models → engine.stream() first so mock engines work in
            # tests.  Fall back to stream_local() only when the engine would
            # mis-route the request to a cloud backend (MultiEngine routing
            # confusion), which is detected by checking the routed engine's
            # is_cloud attribute.
            if use_cloud:
                token_iter = stream_cloud(
                    model, messages, req.temperature, req.max_tokens
                )
            else:
                # Use engine.stream() by default (preserves mock-engine
                # compatibility in tests).  Only fall back to stream_local()
                # when a real MultiEngine would mis-route the local model to a
                # cloud backend — detected via isinstance so mocks are not
                # accidentally matched.
                _use_local_fallback = False
                try:
                    from openjarvis.engine.multi import MultiEngine

                    _inner = getattr(engine, "_inner", engine)
                    if isinstance(_inner, MultiEngine):
                        _routed = _inner._engine_for(model)
                        if _routed is not None and getattr(_routed, "is_cloud", False):
                            _use_local_fallback = True
                except Exception:
                    pass
                if _use_local_fallback:
                    token_iter = stream_local(
                        model, messages, req.temperature, req.max_tokens
                    )
                else:
                    token_iter = engine.stream(
                        messages,
                        model=model,
                        temperature=req.temperature,
                        max_tokens=req.max_tokens,
                    )
            async for token in token_iter:
                full_content += token
                chunk = ChatCompletionChunk(
                    id=chunk_id,
                    model=model,
                    choices=[
                        StreamChoice(
                            delta=DeltaMessage(content=token),
                        )
                    ],
                )
                yield f"data: {chunk.model_dump_json()}\n\n"
        except Exception as exc:
            # Surface errors as a content chunk so the frontend can
            # display them instead of silently failing.
            import logging

            logging.getLogger("openjarvis.server").error(
                "Stream error: %s",
                exc,
                exc_info=True,
            )
            error_chunk = ChatCompletionChunk(
                id=chunk_id,
                model=model,
                choices=[
                    StreamChoice(
                        delta=DeltaMessage(
                            content=f"\n\nError during generation: {exc}",
                        ),
                        finish_reason="stop",
                    )
                ],
            )
            yield f"data: {error_chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
            return

        # Record a trace for the completed stream (best-effort; never breaks
        # the response). Mirrors the agent path so streamed chats also
        # populate traces.db.
        if trace_store is not None and full_content:
            from openjarvis.traces.collector import record_response_trace

            record_response_trace(
                trace_store,
                query=query_text,
                result=full_content,
                model=model,
                engine="cloud" if use_cloud else "ollama",
                started_at=started_at,
                ended_at=time.time(),
            )

        # Send finish chunk with usage data if available
        import json as _json

        finish_data = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[
                StreamChoice(
                    delta=DeltaMessage(),
                    finish_reason="stop",
                )
            ],
        )
        finish_dict = _json.loads(finish_data.model_dump_json())

        # Tag the finish chunk with the correct engine label.
        # We use the routing decision (use_cloud) directly rather than
        # unwrapping the engine chain, which can be in a broken state.
        finish_dict.setdefault("telemetry", {})
        finish_dict["telemetry"]["engine"] = "cloud" if use_cloud else "ollama"

        if complexity_info is not None:
            finish_dict["complexity"] = complexity_info.model_dump()

        yield f"data: {_json.dumps(finish_dict)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/v1/models")
async def list_models(request: Request) -> ModelListResponse:
    """List locally installed models (Ollama).

    Cloud models are not included here — they live in the Cloud Models tab
    of the UI and are selected there, not from this endpoint.
    """
    from openjarvis.server.cloud_router import is_cloud_model, list_local_models

    # Prefer engine.list_models() so mock engines work in tests.
    # Filter out any cloud model IDs that may appear via MultiEngine.
    # Fall back to direct Ollama query only when the engine returns nothing.
    engine = request.app.state.engine
    all_ids = engine.list_models()
    model_ids = [m for m in all_ids if not is_cloud_model(m)]
    if not model_ids:
        model_ids = await list_local_models()

    return ModelListResponse(
        data=[ModelObject(id=mid) for mid in model_ids],
    )


@router.post("/v1/models/pull")
async def pull_model(request: Request):
    """Pull / download a model from the Ollama registry."""
    body = await request.json()
    model_name = body.get("model", "").strip()
    if not model_name:
        raise HTTPException(status_code=400, detail="'model' field is required")

    engine = request.app.state.engine
    engine_name = getattr(request.app.state, "engine_name", "")
    # Only Ollama supports pulling
    if engine_name != "ollama" and getattr(engine, "engine_id", "") != "ollama":
        raise HTTPException(
            status_code=501,
            detail="Model pulling is only supported with the Ollama engine",
        )

    import httpx as _httpx

    host = getattr(engine, "_host", "http://localhost:11434")
    client = _httpx.Client(base_url=host, timeout=600.0)
    try:
        resp = client.post(
            "/api/pull",
            json={"name": model_name, "stream": False},
        )
        resp.raise_for_status()
    except (_httpx.ConnectError, _httpx.TimeoutException) as exc:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {exc}")
    except _httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Ollama error: {exc.response.text[:300]}",
        )
    finally:
        client.close()

    return {"status": "ok", "model": model_name}


@router.delete("/v1/models/{model_name:path}")
async def delete_model(model_name: str, request: Request):
    """Delete a model from Ollama."""
    engine = request.app.state.engine
    engine_name = getattr(request.app.state, "engine_name", "")
    if engine_name != "ollama" and getattr(engine, "engine_id", "") != "ollama":
        raise HTTPException(status_code=501, detail="Only supported with Ollama engine")

    import httpx as _httpx

    host = getattr(engine, "_host", "http://localhost:11434")
    client = _httpx.Client(base_url=host, timeout=30.0)
    try:
        resp = client.request(
            "DELETE",
            "/api/delete",
            json={"name": model_name},
        )
        resp.raise_for_status()
    except (_httpx.ConnectError, _httpx.TimeoutException) as exc:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {exc}")
    except _httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Ollama error: {exc.response.text[:300]}",
        )
    finally:
        client.close()

    return {"status": "deleted", "model": model_name}


@router.post("/v1/cloud/reload")
async def reload_cloud_engine(request: Request):
    """Hot-reload cloud API keys and (re-)initialize the cloud engine.

    Called by the desktop app immediately after the user saves a cloud API
    key so that cloud models become available without a full app restart.
    """
    import os

    # Re-read ~/.openjarvis/cloud-keys.env and update the running process env.
    keys_path = get_config_dir() / "cloud-keys.env"
    if keys_path.exists():
        for raw_line in keys_path.read_text().splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

    # Try to build a fresh CloudEngine.
    try:
        from openjarvis.engine.cloud import CloudEngine
        from openjarvis.engine.multi import MultiEngine

        cloud = CloudEngine()
        if not cloud.health():
            return {
                "status": "no_cloud",
                "message": "No cloud models available (check API keys)",
            }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

    # Locate the innermost engine, working through InstrumentedEngine layers.
    outer = request.app.state.engine
    inner = getattr(outer, "_inner", outer)

    if isinstance(inner, MultiEngine):
        # Replace or insert the cloud entry in the existing MultiEngine.
        new_engines = [(k, e) for k, e in inner._engines if k != "cloud"]
        new_engines.append(("cloud", cloud))
        inner._engines = new_engines
        inner._refresh_map()
    else:
        # Wrap the existing engine (which may be security-wrapped) with a new
        # MultiEngine that includes the cloud engine.
        engine_name = getattr(request.app.state, "engine_name", "local")
        new_multi = MultiEngine([(engine_name, inner), ("cloud", cloud)])
        if hasattr(outer, "_inner"):
            outer._inner = new_multi
        else:
            request.app.state.engine = new_multi
        request.app.state.engine_name = "multi"

    return {"status": "ok", "message": "Cloud engine reloaded"}


@router.get("/v1/savings")
async def savings(request: Request):
    """Return savings summary compared to cloud providers.

    Only includes telemetry from the current server session so that
    counters start at zero each time a new model + agent is launched.
    """
    from openjarvis.core.config import DEFAULT_CONFIG_DIR
    from openjarvis.server.savings import compute_savings, savings_to_dict
    from openjarvis.telemetry.aggregator import TelemetryAggregator

    db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
    if not db_path.exists():
        empty = compute_savings(0, 0, 0)
        return savings_to_dict(empty)

    session_start = getattr(request.app.state, "session_start", None)

    agg = TelemetryAggregator(db_path)
    try:
        # current_methodology_only excludes pre-fix legacy rows from
        # the leaderboard's per-token efficiency numerator/denominator
        # — see the comment on _time_filter for the bimodal-Wh/token
        # background.
        summary = agg.summary(since=session_start, current_methodology_only=True)
        # Exclude cloud model tokens from savings — only local
        # inference counts toward cost savings.
        _cloud_prefixes = (
            "gpt-",
            "o1-",
            "o3-",
            "o4-",
            "claude-",
            "gemini-",
            "openrouter/",
        )
        local_models = [
            m
            for m in summary.per_model
            if not any(m.model_id.startswith(p) for p in _cloud_prefixes)
        ]
        result = compute_savings(
            prompt_tokens=sum(m.prompt_tokens for m in local_models),
            completion_tokens=sum(m.completion_tokens for m in local_models),
            total_calls=sum(m.call_count for m in local_models),
            session_start=session_start if session_start else 0.0,
            prompt_tokens_evaluated=sum(
                m.prompt_tokens_evaluated for m in local_models
            ),
        )
        return savings_to_dict(result)
    finally:
        agg.close()


@router.post("/v1/telemetry/reset")
async def reset_telemetry():
    """Clear all stored telemetry records.

    Useful after updating token-counting methodology — clears
    historical records that were computed under the old rules so
    that the savings dashboard and leaderboard submissions start
    fresh with corrected values.
    """
    from openjarvis.core.config import DEFAULT_CONFIG_DIR
    from openjarvis.telemetry.aggregator import TelemetryAggregator

    db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
    if not db_path.exists():
        return {"status": "ok", "records_cleared": 0}

    agg = TelemetryAggregator(db_path)
    try:
        count = agg.clear()
    finally:
        agg.close()
    return {"status": "ok", "records_cleared": count}


@router.get("/v1/info")
async def server_info(request: Request):
    """Return server configuration: model, agent, engine."""
    agent = getattr(request.app.state, "agent", None)
    agent_id = getattr(agent, "agent_id", None) if agent else None
    # Fall back to configured agent name if agent didn't instantiate
    if agent_id is None:
        agent_id = getattr(request.app.state, "agent_name", None)
    return {
        "model": getattr(request.app.state, "model", ""),
        "agent": agent_id,
        "engine": getattr(request.app.state, "engine_name", ""),
    }


@router.get("/health")
async def health(request: Request):
    """Health check endpoint."""
    engine = request.app.state.engine
    healthy = engine.health()
    if not healthy:
        raise HTTPException(status_code=503, detail="Engine unhealthy")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Channel endpoints
# ---------------------------------------------------------------------------


@router.get("/v1/channels")
async def list_channels(request: Request):
    """List available messaging channels."""
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        return {"channels": [], "message": "Channel bridge not configured"}
    channels = bridge.list_channels()
    return {"channels": channels, "status": bridge.status().value}


@router.post("/v1/channels/send")
async def channel_send(request: Request):
    """Send a message to a channel."""
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        raise HTTPException(status_code=503, detail="Channel bridge not configured")

    body = await request.json()
    channel_name = body.get("channel", "")
    content = body.get("content", "")
    conversation_id = body.get("conversation_id", "")

    if not channel_name or not content:
        raise HTTPException(
            status_code=400,
            detail="'channel' and 'content' are required",
        )

    ok = bridge.send(channel_name, content, conversation_id=conversation_id)
    if not ok:
        raise HTTPException(status_code=502, detail="Failed to send message")
    return {"status": "sent", "channel": channel_name}


@router.get("/v1/channels/status")
async def channel_status(request: Request):
    """Return channel bridge connection status."""
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        return {"status": "not_configured"}
    return {"status": bridge.status().value}


# ---------------------------------------------------------------------------
# Security scan endpoint
# ---------------------------------------------------------------------------


@router.get("/v1/security/scan")
async def security_scan():
    """Run a read-only security environment audit and return findings."""
    from openjarvis.cli.scan_cmd import PrivacyScanner

    scanner = PrivacyScanner()
    results = scanner.run_all()
    return {
        "has_warnings": any(r.status == "warn" for r in results),
        "has_failures": any(r.status == "fail" for r in results),
        "findings": [
            {
                "name": r.name,
                "status": r.status,
                "message": r.message,
                "platform": r.platform,
            }
            for r in results
        ],
    }


__all__ = ["router"]

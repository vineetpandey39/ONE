"""Extended API routes for agents, workflows, memory, traces, etc."""

from __future__ import annotations

import inspect
import hashlib
import hmac
import json
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from openjarvis.speech.normalize import normalize_one_transcript

logger = logging.getLogger(__name__)

# ---- Request/Response models ----


class AgentCreateRequest(BaseModel):
    agent_type: str
    tools: Optional[List[str]] = None
    agent_id: Optional[str] = None


class AgentMessageRequest(BaseModel):
    message: str


class MemoryStoreRequest(BaseModel):
    content: str
    metadata: Optional[Dict[str, Any]] = None


class MemorySearchRequest(BaseModel):
    query: str
    top_k: int = 5


class MemoryIndexRequest(BaseModel):
    path: str


class BudgetLimitsRequest(BaseModel):
    max_tokens_per_day: Optional[int] = None
    max_requests_per_hour: Optional[int] = None


class FeedbackScoreRequest(BaseModel):
    trace_id: str
    score: float
    source: str = "api"


class OptimizeRunRequest(BaseModel):
    benchmark: str
    max_trials: int = 20
    optimizer_model: str = "claude-sonnet-4-6"
    max_samples: int = 50


class AlfaOpportunityActionRequest(BaseModel):
    url: str


class AlfaOutreachRequest(BaseModel):
    url: str
    channel: str = "manual"
    client_contact: str = ""
    client_name: str = ""


class AlfaResponseRequest(BaseModel):
    url: str
    response_text: str


class AlfaPaymentRequest(BaseModel):
    url: str
    amount: int
    reference: str
    payment_link: str = ""


class AlfaDeliveryRequest(BaseModel):
    url: str
    allow_unpaid: bool = False


class AlfaCompleteRequest(BaseModel):
    url: str
    activate_retainer: bool = False


# ---- Agent routes ----

agents_router = APIRouter(prefix="/v1/agents", tags=["agents"])


@agents_router.get("")
async def list_agents(request: Request):
    """List available agent types and running agents."""
    registered = []
    try:
        import openjarvis.agents  # noqa: F401 — side-effect registration
        from openjarvis.core.registry import AgentRegistry

        for key in sorted(AgentRegistry.keys()):
            cls = AgentRegistry.get(key)
            registered.append(
                {
                    "key": key,
                    "class": cls.__name__,
                    "accepts_tools": getattr(cls, "accepts_tools", False),
                }
            )
    except Exception as exc:
        logger.warning("Failed to list registered agents: %s", exc)

    running = []
    try:
        from openjarvis.tools.agent_tools import _SPAWNED_AGENTS

        running = [{"id": k, **v} for k, v in _SPAWNED_AGENTS.items()]
    except ImportError:
        pass

    return {"registered": registered, "running": running}


@agents_router.post("")
async def create_agent(req: AgentCreateRequest, request: Request):
    """Spawn a new agent."""
    try:
        from openjarvis.tools.agent_tools import AgentSpawnTool

        tool = AgentSpawnTool()
        params = {"agent_type": req.agent_type}
        if req.tools:
            params["tools"] = ",".join(req.tools)
        if req.agent_id:
            params["agent_id"] = req.agent_id
        result = tool.execute(**params)
        if not result.success:
            raise HTTPException(status_code=400, detail=result.content)
        return {
            "status": "created",
            "content": result.content,
            "metadata": result.metadata,
        }
    except ImportError:
        raise HTTPException(status_code=501, detail="Agent tools not available")


@agents_router.delete("/{agent_id}")
async def kill_agent(agent_id: str, request: Request):
    """Kill a running agent."""
    try:
        from openjarvis.tools.agent_tools import AgentKillTool

        tool = AgentKillTool()
        result = tool.execute(agent_id=agent_id)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.content)
        return {"status": "stopped", "agent_id": agent_id}
    except ImportError:
        raise HTTPException(status_code=501, detail="Agent tools not available")


@agents_router.post("/{agent_id}/message")
async def message_agent(agent_id: str, req: AgentMessageRequest, request: Request):
    """Send a message to a running agent."""
    try:
        from openjarvis.tools.agent_tools import AgentSendTool

        tool = AgentSendTool()
        result = tool.execute(agent_id=agent_id, message=req.message)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.content)
        return {"status": "sent", "content": result.content}
    except ImportError:
        raise HTTPException(status_code=501, detail="Agent tools not available")


# ---- Memory routes ----

memory_router = APIRouter(prefix="/v1/memory", tags=["memory"])


def _get_memory_backend(request: Request):
    """Return the app-level memory backend, falling back to a fresh SQLiteMemory.

    Raises ``HTTPException(503)`` with an actionable message when the backend
    cannot be built because the mandatory ``openjarvis_rust`` extension is not
    installed in the serving venv. This is deliberately distinct from a benign
    "memory not configured" case (which returns ``None``): a missing native
    extension must fail loudly, never silently degrade (#502).
    """
    backend = getattr(request.app.state, "memory_backend", None)
    if backend is None:
        from openjarvis.tools.storage._stubs import MemoryBackendUnavailable

        try:
            from openjarvis.tools.storage.sqlite import SQLiteMemory

            backend = SQLiteMemory()
        except MemoryBackendUnavailable as exc:
            # The native extension is missing — surface a loud, actionable error
            # rather than a misleading "no backend" / silent no-op.
            logger.error("%s", exc)
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception:
            # Memory is genuinely unconfigured for a benign reason — preserve
            # the existing graceful "no backend" behaviour.
            return None
    return backend


@memory_router.post("/store")
async def memory_store(req: MemoryStoreRequest, request: Request):
    """Store content in memory."""
    backend = _get_memory_backend(request)
    if backend is None:
        # Memory is intentionally disabled; report it honestly instead of a
        # 200 that silently discards the write (#502).
        raise HTTPException(status_code=503, detail="Memory is not configured")
    try:
        backend.store(req.content, metadata=req.metadata or {})
        return {"status": "stored"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@memory_router.post("/search")
async def memory_search(req: MemorySearchRequest, request: Request):
    """Search memory for relevant content."""
    backend = _get_memory_backend(request)
    if backend is None:
        return {"results": []}
    try:
        results = backend.retrieve(req.query, top_k=req.top_k)
        items = [
            {
                "content": r.content,
                "score": getattr(r, "score", 0.0),
                "metadata": getattr(r, "metadata", {}),
            }
            for r in results
        ]
        return {"results": items}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@memory_router.get("/stats")
async def memory_stats(request: Request):
    """Get memory backend statistics."""
    backend = _get_memory_backend(request)
    if backend is None:
        return {"entries": 0, "backend": "none", "status": "not_configured"}
    try:
        return {
            "entries": backend.count(),
            "backend": getattr(backend, "backend_id", "unknown"),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@memory_router.get("/config")
async def memory_config(request: Request):
    """Return current memory configuration.

    Reports memory as *unavailable* (rather than falsely claiming
    ``backend_type: sqlite``) when the native ``openjarvis_rust`` extension is
    missing, so the UI can show the real cause instead of a healthy-looking
    config that backs a silent no-op (#502).
    """
    try:
        config = getattr(request.app.state, "config", None)
        if config is None:
            from openjarvis.core.config import load_config

            config = load_config()
        backend = getattr(request.app.state, "memory_backend", None)
        available = True
        detail: Optional[str] = None
        if backend is None:
            from openjarvis.tools.storage._stubs import MemoryBackendUnavailable

            try:
                from openjarvis.tools.storage.sqlite import SQLiteMemory

                backend = SQLiteMemory()
            except MemoryBackendUnavailable as exc:
                available = False
                detail = str(exc)
            except Exception:
                # Benign: cannot construct a probe backend here, but the
                # configured default is still what would be used.
                pass
        return {
            "backend_type": (
                backend.backend_id
                if backend is not None
                else config.memory.default_backend
            ),
            "available": available,
            "detail": detail,
            "context_top_k": config.memory.context_top_k,
            "context_min_score": config.memory.context_min_score,
            "context_max_tokens": config.memory.context_max_tokens,
            "context_from_memory": config.agent.context_from_memory,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@memory_router.post("/index")
async def memory_index(req: MemoryIndexRequest, request: Request):
    """Index files from a path into memory."""
    try:
        import os
        from pathlib import Path

        from openjarvis.security.file_policy import is_sensitive_file
        from openjarvis.tools.storage.ingest import ingest_path

        target = Path(req.path).expanduser().resolve()
        if not target.exists():
            raise HTTPException(status_code=404, detail=f"Path not found: {req.path}")

        # Sandbox: when workspace roots are configured via OPENJARVIS_WORKSPACE
        # (os.pathsep-separated), only allow indexing inside them. This endpoint
        # must not become an arbitrary-filesystem read primitive over the API.
        workspace = os.environ.get("OPENJARVIS_WORKSPACE", "").strip()
        if workspace:
            roots = [
                Path(d).expanduser().resolve()
                for d in workspace.split(os.pathsep)
                if d.strip()
            ]
            if not any(
                target == root or root in target.parents for root in roots
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Path is outside the allowed workspace directories.",
                )
        # Never ingest sensitive files (.env, private keys, credentials, ...).
        if target.is_file() and is_sensitive_file(target):
            raise HTTPException(
                status_code=403, detail="Refusing to index a sensitive file."
            )

        backend = _get_memory_backend(request)
        if backend is None:
            raise HTTPException(status_code=503, detail="Memory is not configured")

        chunks = ingest_path(target)
        stored = 0
        for chunk in chunks:
            metadata = {"source": getattr(chunk, "source", str(target))}
            if hasattr(chunk, "metadata") and chunk.metadata:
                metadata.update(chunk.metadata)
            backend.store(chunk.content, metadata=metadata)
            stored += 1

        result = {"status": "indexed", "chunks_indexed": stored}
        if stored == 0:
            # "indexed" must never silently mean "stored nothing". Surface why
            # so a folder of short notes doesn't look like a successful no-op
            # (#502 follow-up).
            result["note"] = (
                "no content was indexed — the path contained no readable "
                "documents with indexable text"
            )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---- Traces routes ----

traces_router = APIRouter(prefix="/v1/traces", tags=["traces"])


def _serialise_trace(trace) -> dict:
    """Convert a Trace dataclass to a frontend-friendly dict."""
    import datetime
    from dataclasses import asdict

    d = asdict(trace)
    d["id"] = d.pop("trace_id", "")
    started = d.pop("started_at", 0.0)
    d["created_at"] = (
        datetime.datetime.fromtimestamp(started, tz=datetime.timezone.utc).isoformat()
        if started
        else None
    )
    dur = d.pop("total_latency_seconds", 0.0)
    d["duration_ms"] = round(dur * 1000)
    for step in d.get("steps", []):
        st = step.get("step_type")
        if hasattr(st, "value"):
            step["step_type"] = st.value
    return d


@traces_router.get("")
async def list_traces(request: Request, limit: int = 20):
    """List recent traces."""
    try:
        store = getattr(request.app.state, "trace_store", None)
        if store is None:
            return {"traces": []}
        traces = store.list_traces(limit=limit)
        items = [_serialise_trace(t) for t in traces]
        return {"traces": items}
    except Exception as exc:
        return {"traces": [], "error": str(exc)}


@traces_router.get("/{trace_id}")
async def get_trace(trace_id: str, request: Request):
    """Get a specific trace by ID."""
    try:
        store = getattr(request.app.state, "trace_store", None)
        if store is None:
            raise HTTPException(status_code=404, detail="Trace not found")
        trace = store.get(trace_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="Trace not found")
        return _serialise_trace(trace)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---- Telemetry routes ----

telemetry_router = APIRouter(prefix="/v1/telemetry", tags=["telemetry"])


@telemetry_router.get("/stats")
async def telemetry_stats(request: Request):
    """Get aggregated telemetry statistics."""
    try:
        from dataclasses import asdict

        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.telemetry.aggregator import TelemetryAggregator

        db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
        if not db_path.exists():
            return {"total_requests": 0, "total_tokens": 0}

        session_start = getattr(request.app.state, "session_start", None)
        agg = TelemetryAggregator(db_path)
        try:
            stats = agg.summary(since=session_start)
            d = asdict(stats)
            d.pop("per_model", None)
            d.pop("per_engine", None)
            d["total_requests"] = d.pop("total_calls", 0)
            return d
        finally:
            agg.close()
    except Exception as exc:
        return {"error": str(exc)}


@telemetry_router.get("/energy")
async def telemetry_energy(request: Request):
    """Get energy monitoring data."""
    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.telemetry.aggregator import TelemetryAggregator

        db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
        if not db_path.exists():
            return {
                "total_energy_j": 0,
                "energy_per_token_j": 0,
                "avg_power_w": 0,
                "cpu_temp_c": None,
                "gpu_temp_c": None,
            }

        session_start = getattr(request.app.state, "session_start", None)
        agg = TelemetryAggregator(db_path)
        try:
            stats = agg.summary(since=session_start)
            total_energy = stats.total_energy_joules
            total_tokens = stats.total_tokens
            total_latency = stats.total_latency
            return {
                "total_energy_j": total_energy,
                "energy_per_token_j": (
                    total_energy / total_tokens if total_tokens > 0 else 0
                ),
                "avg_power_w": (
                    total_energy / total_latency if total_latency > 0 else 0
                ),
                "cpu_temp_c": None,
                "gpu_temp_c": None,
            }
        finally:
            agg.close()
    except Exception as exc:
        return {"error": str(exc)}


# ---- Skills routes ----

skills_router = APIRouter(prefix="/v1/skills", tags=["skills"])


@skills_router.get("")
async def list_skills(request: Request):
    """List installed skills."""
    try:
        from openjarvis.core.registry import SkillRegistry

        skills = []
        for key in sorted(SkillRegistry.keys()):
            skills.append({"name": key})
        return {"skills": skills}
    except Exception as exc:
        logger.warning("Failed to list skills: %s", exc)
        return {"skills": []}


@skills_router.post("")
async def install_skill(request: Request):
    """Install a skill (placeholder)."""
    return {
        "status": "not_implemented",
        "message": "Use TOML files in ~/.openjarvis/skills/",
    }


@skills_router.delete("/{skill_name}")
async def remove_skill(skill_name: str, request: Request):
    """Remove a skill (placeholder)."""
    return {
        "status": "not_implemented",
        "message": "Skill removal not yet supported via API",
    }


# ---- Sessions routes ----

sessions_router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


@sessions_router.get("")
async def list_sessions(request: Request, limit: int = 20):
    """List active sessions."""
    try:
        from openjarvis.sessions.store import SessionStore

        store = SessionStore()
        sessions = store.recent(limit=limit)
        items = [s.to_dict() if hasattr(s, "to_dict") else str(s) for s in sessions]
        return {"sessions": items}
    except Exception as exc:
        return {"sessions": [], "error": str(exc)}


@sessions_router.get("/{session_id}")
async def get_session(session_id: str, request: Request):
    """Get a specific session."""
    try:
        from openjarvis.sessions.store import SessionStore

        store = SessionStore()
        session = store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return session.to_dict() if hasattr(session, "to_dict") else {"id": session_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---- Budget routes ----

budget_router = APIRouter(prefix="/v1/budget", tags=["budget"])

_budget_limits: Dict[str, Any] = {
    "max_tokens_per_day": None,
    "max_requests_per_hour": None,
}
_budget_usage: Dict[str, int] = {
    "tokens_today": 0,
    "requests_this_hour": 0,
}


@budget_router.get("")
async def get_budget(request: Request):
    """Get current budget usage and limits."""
    return {"limits": _budget_limits, "usage": _budget_usage}


@budget_router.put("/limits")
async def set_budget_limits(req: BudgetLimitsRequest, request: Request):
    """Update budget limits."""
    if req.max_tokens_per_day is not None:
        _budget_limits["max_tokens_per_day"] = req.max_tokens_per_day
    if req.max_requests_per_hour is not None:
        _budget_limits["max_requests_per_hour"] = req.max_requests_per_hour
    return {"status": "updated", "limits": _budget_limits}


# ---- Prometheus metrics ----

metrics_router = APIRouter(tags=["metrics"])


@metrics_router.get("/metrics")
async def prometheus_metrics(request: Request):
    """Prometheus-compatible metrics endpoint."""
    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.telemetry.aggregator import TelemetryAggregator

        db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
        if not db_path.exists():
            from starlette.responses import PlainTextResponse

            return PlainTextResponse("# no telemetry data\n", media_type="text/plain")

        agg = TelemetryAggregator(db_path)
        stats = agg.summary()

        lines = [
            "# HELP openjarvis_requests_total Total requests processed",
            "# TYPE openjarvis_requests_total counter",
            f"openjarvis_requests_total {stats.get('total_requests', 0)}",
            "# HELP openjarvis_tokens_total Total tokens generated",
            "# TYPE openjarvis_tokens_total counter",
            f"openjarvis_tokens_total {stats.get('total_tokens', 0)}",
            "# HELP openjarvis_latency_avg_ms Average latency in milliseconds",
            "# TYPE openjarvis_latency_avg_ms gauge",
            f"openjarvis_latency_avg_ms {stats.get('avg_latency_ms', 0)}",
        ]
        from starlette.responses import PlainTextResponse

        return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain")
    except Exception as exc:
        logger.warning("Failed to collect Prometheus metrics: %s", exc)
        from starlette.responses import PlainTextResponse

        return PlainTextResponse("# No metrics available\n", media_type="text/plain")


# ---- WebSocket streaming routes ----

websocket_router = APIRouter(tags=["websocket"])


def _record_ws_trace(
    trace_store,
    *,
    query: str,
    result: str,
    model: str,
    started_at: float,
    ended_at: float,
) -> None:
    """Record a trace for a completed WebSocket chat (best-effort)."""
    if trace_store is None or not result:
        return
    from openjarvis.traces.collector import record_response_trace

    record_response_trace(
        trace_store,
        query=query,
        result=result,
        model=model,
        started_at=started_at,
        ended_at=ended_at,
    )


@websocket_router.websocket("/v1/chat/stream")
async def websocket_chat_stream(websocket: WebSocket):
    """Stream chat responses over a WebSocket connection.

    Accepts JSON messages of the form::

        {"message": "...", "model": "...", "agent": "..."}

    Sends back JSON chunks::

        {"type": "chunk", "content": "..."}   -- per-token streaming
        {"type": "done",  "content": "..."}   -- final assembled response
        {"type": "error", "detail": "..."}    -- on failure
    """
    from openjarvis.server.auth_middleware import websocket_authorized

    expected_key = getattr(websocket.app.state, "api_key", "")
    if not websocket_authorized(websocket, expected_key):
        # 1008 = policy violation; reject before accepting the connection.
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                await websocket.send_json(
                    {"type": "error", "detail": "Invalid JSON"},
                )
                continue

            message = data.get("message")
            if not message:
                await websocket.send_json(
                    {"type": "error", "detail": "Missing 'message' field"},
                )
                continue

            model = data.get("model") or getattr(
                websocket.app.state,
                "model",
                "default",
            )
            engine = getattr(websocket.app.state, "engine", None)
            if engine is None:
                await websocket.send_json(
                    {"type": "error", "detail": "No engine configured"},
                )
                continue

            messages = [{"role": "user", "content": message}]

            # This WS path streams straight from the engine (no agent /
            # TraceCollector), so record the interaction directly once it
            # finishes — otherwise WebSocket chats never reach traces.db.
            import time as _time

            trace_store = getattr(websocket.app.state, "trace_store", None)
            _ws_started_at = _time.time()

            try:
                # Prefer streaming if the engine supports it
                stream_fn = getattr(engine, "stream", None)
                if stream_fn is not None and (
                    inspect.isasyncgenfunction(stream_fn) or callable(stream_fn)
                ):
                    full_content = ""
                    try:
                        gen = stream_fn(messages, model=model)
                        # Handle both async and sync generators
                        if inspect.isasyncgen(gen):
                            async for token in gen:
                                full_content += token
                                await websocket.send_json(
                                    {"type": "chunk", "content": token},
                                )
                        else:
                            # Sync generator — iterate in a thread to avoid
                            # blocking the event loop
                            for token in gen:
                                full_content += token
                                await websocket.send_json(
                                    {"type": "chunk", "content": token},
                                )
                    except TypeError:
                        # stream() didn't return an iterable; fall back to
                        # generate()
                        result = engine.generate(messages, model=model)
                        content = (
                            result.get("content", "")
                            if isinstance(
                                result,
                                dict,
                            )
                            else str(result)
                        )
                        full_content = content
                        await websocket.send_json(
                            {"type": "chunk", "content": content},
                        )
                    await websocket.send_json(
                        {"type": "done", "content": full_content},
                    )
                    _record_ws_trace(
                        trace_store,
                        query=message,
                        result=full_content,
                        model=model,
                        started_at=_ws_started_at,
                        ended_at=_time.time(),
                    )
                else:
                    # No stream method — single-shot generate
                    result = engine.generate(messages, model=model)
                    content = (
                        result.get("content", "")
                        if isinstance(
                            result,
                            dict,
                        )
                        else str(result)
                    )
                    await websocket.send_json(
                        {"type": "chunk", "content": content},
                    )
                    await websocket.send_json(
                        {"type": "done", "content": content},
                    )
                    _record_ws_trace(
                        trace_store,
                        query=message,
                        result=content,
                        model=model,
                        started_at=_ws_started_at,
                        ended_at=_time.time(),
                    )
            except WebSocketDisconnect:
                raise
            except Exception as exc:
                await websocket.send_json(
                    {"type": "error", "detail": str(exc)},
                )
    except WebSocketDisconnect:
        pass  # Client disconnected — nothing to clean up


# ---- Learning routes ----

learning_router = APIRouter(prefix="/v1/learning", tags=["learning"])


@learning_router.get("/stats")
async def learning_stats(request: Request):
    """Return learning system statistics across all sub-policies."""
    result: Dict[str, Any] = {}

    # Skill discovery
    try:
        from openjarvis.learning.agents.skill_discovery import SkillDiscovery

        discovery = SkillDiscovery()
        result["skill_discovery"] = {
            "available": True,
            "discovered_count": len(discovery.discovered_skills),
        }
    except Exception as exc:
        logger.warning("Failed to load skill discovery stats: %s", exc)
        result["skill_discovery"] = {"available": False}

    return result


@learning_router.get("/policy")
async def learning_policy(request: Request):
    """Return current routing policy configuration."""
    result: Dict[str, Any] = {}

    # Load config and extract learning section
    try:
        from openjarvis.core.config import load_config

        config = load_config()
        lc = config.learning
        result["enabled"] = lc.enabled
        result["update_interval"] = lc.update_interval
        result["auto_update"] = lc.auto_update
        result["routing"] = {
            "policy": lc.routing.policy,
            "min_samples": lc.routing.min_samples,
        }
        result["intelligence"] = {
            "policy": lc.intelligence.policy,
        }
        result["agent"] = {
            "policy": lc.agent.policy,
        }
        result["metrics"] = {
            "accuracy_weight": lc.metrics.accuracy_weight,
            "latency_weight": lc.metrics.latency_weight,
            "cost_weight": lc.metrics.cost_weight,
            "efficiency_weight": lc.metrics.efficiency_weight,
        }
    except Exception as exc:
        logger.warning("Failed to load learning config: %s", exc)
        result["enabled"] = False
        result["routing"] = {"policy": "heuristic", "min_samples": 5}
        result["intelligence"] = {"policy": "none"}
        result["agent"] = {"policy": "none"}
        result["metrics"] = {}

    return result


# ---- Speech routes ----

speech_router = APIRouter(prefix="/v1/speech", tags=["speech"])


@speech_router.post("/transcribe")
async def transcribe_speech(request: Request):
    """Transcribe uploaded audio to text."""
    from fastapi.concurrency import run_in_threadpool

    backend = getattr(request.app.state, "speech_backend", None)
    if backend is None:
        raise HTTPException(status_code=501, detail="Speech backend not configured")

    form = await request.form()
    audio_file = form.get("file")
    if audio_file is None:
        raise HTTPException(status_code=400, detail="Missing 'file' field")

    audio_bytes = await audio_file.read()
    language = form.get("language")

    # Detect format from filename
    filename = getattr(audio_file, "filename", "audio.wav")
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "wav"

    try:
        # Confirmed: this call previously ran synchronously inside an async
        # handler, blocking FastAPI's entire event loop (single worker, per
        # config.toml) for the full duration of a CPU-bound Whisper call --
        # every other request (status polls, wake events, other users'
        # transcriptions) stalled behind it. /native-record already used
        # run_in_threadpool correctly; this brings /transcribe in line.
        result = await run_in_threadpool(
            backend.transcribe, audio_bytes, format=ext, language=language or None
        )
    except Exception as exc:
        logger.exception("Local speech transcription failed")
        raise HTTPException(status_code=422, detail=f"Local transcription failed: {type(exc).__name__}") from exc
    return {
        "text": normalize_one_transcript(result.text),
        "language": result.language,
        "confidence": result.confidence,
        "duration_seconds": result.duration_seconds,
    }


@speech_router.get("/health")
async def speech_health(request: Request):
    """Check if a speech backend is available."""
    backend = getattr(request.app.state, "speech_backend", None)
    if backend is None:
        return {"available": False, "reason": "No speech backend configured"}
    return {
        "available": backend.health(),
        "backend": backend.backend_id,
    }


@speech_router.post("/warmup")
async def speech_warmup(request: Request):
    """Preload local STT in the background so first-command latency is low."""
    import asyncio

    from fastapi.concurrency import run_in_threadpool

    backend = getattr(request.app.state, "speech_backend", None)
    if backend is None:
        raise HTTPException(status_code=501, detail="Speech backend not configured")
    warmup = getattr(backend, "warmup", None)
    if warmup is None:
        return {"accepted": False, "reason": "Backend does not support warmup"}
    asyncio.create_task(run_in_threadpool(warmup))
    return {"accepted": True}


@speech_router.get("/devices")
async def speech_devices():
    """List native Windows capture devices without browser permissions."""
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise HTTPException(status_code=501, detail="Native audio capture is not installed") from exc

    hostapis = sd.query_hostapis()
    candidates = []
    # Some USB devices expose an audio terminal descriptor PortAudio's WASAPI
    # backend can't name (raises PortAudioError: "GetNameFromCategory:
    # usbTerminalGUID = ..."). A single bad device can crash a bulk
    # sd.query_devices() call even when we only care about the Realtek mic,
    # so enumerate one index at a time and skip whichever device errors.
    device_count = 0
    try:
        device_count = len(sd.query_devices())
    except Exception:
        try:
            device_count = sd.query_devices().__len__()
        except Exception:
            device_count = 0
    all_devices = []
    if device_count:
        for index in range(device_count):
            try:
                all_devices.append(sd.query_devices(index))
            except Exception:
                continue
    else:
        try:
            all_devices = list(sd.query_devices())
        except Exception:
            all_devices = []
    for index, device in enumerate(all_devices):
        if int(device.get("max_input_channels", 0)) < 1:
            continue
        name = " ".join(str(device.get("name", "Microphone")).split())
        host_name = str(hostapis[int(device.get("hostapi", 0))].get("name", "Windows"))
        priority = {"Windows WASAPI": 0, "Windows DirectSound": 1, "MME": 2}.get(host_name, 3)
        if name in {"Microsoft Sound Mapper - Input", "Primary Sound Capture Driver"}:
            priority += 10
        candidates.append({
            "index": index,
            "name": name,
            "host_api": host_name,
            "priority": priority,
            "sample_rate": int(device.get("default_samplerate", 44100)),
        })
    try:
        system_default = int(sd.default.device[0])
    except (TypeError, IndexError):
        system_default = int(sd.default.device)
    default_name = next((item["name"] for item in candidates if item["index"] == system_default), "")
    best_by_name = {}
    for item in sorted(candidates, key=lambda value: (value["priority"], value["index"])):
        best_by_name.setdefault(item["name"].lower(), item)
    physical_markers = ("microphone", "mic ", "rode", "usb audio", "headset")
    excluded_markers = ("virtual", "mapper", "primary sound", "stereo mix", "line in")
    devices = [
        item for item in best_by_name.values()
        if item["host_api"] == "Windows WASAPI"
        and any(marker in item["name"].lower() for marker in physical_markers)
        and not any(marker in item["name"].lower() for marker in excluded_markers)
    ]
    if not devices:
        devices = [
            item for item in best_by_name.values()
            if any(marker in item["name"].lower() for marker in physical_markers)
            and not any(marker in item["name"].lower() for marker in excluded_markers)
        ]
    default_device = next(
        (item["index"] for item in devices if item["name"].lower() == default_name.lower()),
        devices[0]["index"] if devices else system_default,
    )
    return {"devices": devices, "default_device": int(default_device)}


@speech_router.post("/native-record")
async def native_record(request: Request):
    """Capture one command, stopping shortly after the speaker goes quiet."""
    from fastapi.concurrency import run_in_threadpool

    backend = getattr(request.app.state, "speech_backend", None)
    if backend is None:
        raise HTTPException(status_code=501, detail="Speech backend not configured")
    payload = await request.json()
    duration = max(3.0, min(float(payload.get("duration", 5.0)), 8.0))
    device = payload.get("device")
    device = int(device) if device is not None else None

    def capture_and_transcribe():
        import io
        import math
        import time
        import wave

        import numpy as np
        import sounddevice as sd

        from openjarvis.one_agents.wake import pause_wake_listener, resume_wake_listener

        def open_capture(target_device):
            # Confirmed live (2026-07-19): a plain blocking sd.rec() for the
            # full fixed `duration` was the single biggest latency source in
            # the whole voice pipeline -- a 2-second "Hey ONE, how are you"
            # still made the user wait out the entire 5s window before
            # transcription even started, on top of STT + TTS time. Stream
            # in small blocks instead (same technique wake.py's clap
            # detector already uses) and stop as soon as sustained silence
            # follows real speech, so a short command finishes in ~1-2s
            # instead of always paying the full ceiling. `duration` remains
            # a hard safety-net ceiling for longer commands.
            info = sd.query_devices(target_device, "input")
            sample_rate = int(info.get("default_samplerate", 44100))
            blocksize = max(256, int(sample_rate * 0.05))  # ~50ms blocks
            silence_hang_blocks = max(1, int(0.7 / 0.05))  # ~700ms of silence to stop
            max_blocks = max(1, int(duration / 0.05))

            chunks: list[np.ndarray] = []
            noise_floor = 0.01
            speech_started = False
            silence_run = 0
            calibration_blocks = 4  # ~200ms to estimate the room's noise floor

            with sd.InputStream(
                device=target_device, samplerate=sample_rate, channels=1,
                dtype="float32", blocksize=blocksize,
            ) as stream:
                for i in range(max_blocks):
                    frame, _overflowed = stream.read(blocksize)
                    mono = frame[:, 0]
                    chunks.append(mono.copy())
                    rms = float(math.sqrt(float(np.mean(mono * mono)) + 1e-12))

                    if i < calibration_blocks:
                        noise_floor = noise_floor * 0.5 + rms * 0.5
                        continue

                    speech_threshold = max(0.018, noise_floor * 4.0)
                    if rms >= speech_threshold:
                        speech_started = True
                        silence_run = 0
                    elif speech_started:
                        silence_run += 1
                        if silence_run >= silence_hang_blocks:
                            break
                    else:
                        # Still waiting for speech to start -- let the noise
                        # floor drift slowly in case ambient level changes.
                        noise_floor = noise_floor * 0.98 + rms * 0.02

            raw = np.concatenate(chunks).reshape(-1, 1) if chunks else np.zeros((0, 1), dtype=np.float32)
            return raw, sample_rate

        pause_wake_listener()
        try:
            try:
                raw, sample_rate = open_capture(device)
            except Exception:
                # Querying a device by index can succeed while actually opening
                # a stream on it still fails: WASAPI rebuilds its endpoint
                # table when a stream binds, and a sibling USB device with an
                # unrecognized audio-terminal descriptor (PortAudioError:
                # "GetNameFromCategory: usbTerminalGUID = ...") can trip that
                # rebuild even though the requested device itself is fine.
                # Retry once on whatever sounddevice considers the system
                # default input, which often resolves via a different host
                # API path that avoids the same crash.
                fallback_device = None
                try:
                    fallback_device = int(sd.default.device[0])
                except Exception:
                    fallback_device = None
                if fallback_device is None or fallback_device == device:
                    raise
                raw, sample_rate = open_capture(fallback_device)
        finally:
            resume_wake_listener()
        audio = np.asarray(raw[:, 0], dtype=np.float32)
        audio -= float(np.mean(audio))
        max_rms = float(np.sqrt(np.mean(np.square(audio)) + 1e-12))
        max_peak = float(np.max(np.abs(audio)))
        # Analog external microphones often arrive through the Realtek jack
        # at a very low level. Normalize only upward and cap amplification so
        # Whisper receives intelligible speech without clipping room noise.
        if 0.0001 < max_peak < 0.35:
            audio *= min(20.0, 0.35 / max_peak)
        frames = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)
        captured_seconds = len(frames) / sample_rate
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(frames.tobytes())
        transcription_started = time.perf_counter()
        result = backend.transcribe(output.getvalue(), format="wav", language=None)
        return result, captured_seconds, (time.perf_counter() - transcription_started) * 1000, max_rms, max_peak

    try:
        result, captured_seconds, transcription_ms, max_rms, max_peak = await run_in_threadpool(capture_and_transcribe)
    except Exception as exc:
        logger.exception("Native microphone capture failed")
        raise HTTPException(status_code=422, detail=f"Native microphone failed: {type(exc).__name__}") from exc
    return {
        "text": normalize_one_transcript(result.text),
        "language": result.language,
        "confidence": result.confidence,
        "duration_seconds": result.duration_seconds,
        "captured_seconds": round(captured_seconds, 3),
        "transcription_ms": round(transcription_ms, 1),
        "max_rms": round(max_rms, 5),
        "max_peak": round(max_peak, 5),
    }


# ---- Feedback routes ----

feedback_router = APIRouter(prefix="/v1/feedback", tags=["feedback"])


@feedback_router.post("")
async def submit_feedback(req: FeedbackScoreRequest, request: Request):
    """Submit feedback for a trace."""
    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.traces.store import TraceStore

        db_path = DEFAULT_CONFIG_DIR / "traces.db"
        if not db_path.exists():
            raise HTTPException(status_code=404, detail="No trace database")

        store = TraceStore(db_path)
        updated = store.update_feedback(req.trace_id, req.score)
        store.close()

        if not updated:
            raise HTTPException(
                status_code=404, detail=f"Trace '{req.trace_id}' not found"
            )
        return {"status": "recorded", "trace_id": req.trace_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@feedback_router.get("/stats")
async def feedback_stats(request: Request):
    """Get feedback statistics."""
    return {"total": 0, "mean_score": 0.0}


# ---- Optimize routes ----

optimize_router = APIRouter(prefix="/v1/optimize", tags=["optimize"])


@optimize_router.get("/runs")
async def list_optimize_runs(request: Request):
    """List optimization runs."""
    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.learning.optimize.store import OptimizationStore

        db_path = DEFAULT_CONFIG_DIR / "optimize.db"
        if not db_path.exists():
            return {"runs": []}

        store = OptimizationStore(db_path)
        runs = store.list_runs()
        store.close()
        return {"runs": runs}
    except Exception as exc:
        logger.warning("Failed to list optimization runs: %s", exc)
        return {"runs": []}


@optimize_router.get("/runs/{run_id}")
async def get_optimize_run(run_id: str, request: Request):
    """Get optimization run details."""
    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.learning.optimize.store import OptimizationStore

        db_path = DEFAULT_CONFIG_DIR / "optimize.db"
        if not db_path.exists():
            return {"run_id": run_id, "status": "not_found"}

        store = OptimizationStore(db_path)
        run = store.get_run(run_id)
        store.close()

        if run is None:
            return {"run_id": run_id, "status": "not_found"}

        return {
            "run_id": run.run_id,
            "status": run.status,
            "benchmark": run.benchmark,
            "trials": len(run.trials),
            "best_trial_id": (run.best_trial.trial_id if run.best_trial else None),
        }
    except Exception as exc:
        logger.warning("Failed to get optimization run %s: %s", run_id, exc)
        return {"run_id": run_id, "status": "not_found"}


@optimize_router.post("/runs")
async def start_optimize_run(req: OptimizeRunRequest, request: Request):
    """Start a new optimization run."""
    return {"status": "started", "run_id": "placeholder"}


# ---- ALFA revenue-opportunity routes ----

alfa_router = APIRouter(prefix="/v1/alfa", tags=["alfa"])


@alfa_router.get("")
async def list_alfa_opportunities(status: str | None = None, limit: int = 20):
    """List ALFA's packaged leads (service definition, pricing, outreach draft).

    `status` filters by approval_status: pending_review | approved | dismissed.
    Omit to get everything, newest/highest-scoring first.
    """
    from openjarvis.one_agents.alfa import list_opportunities

    try:
        opportunities = list_opportunities(status=status, limit=limit)
        return {"opportunities": opportunities, "count": len(opportunities)}
    except Exception as exc:
        logger.warning("Failed to list ALFA opportunities: %s", exc)
        return {"opportunities": [], "count": 0}


@alfa_router.get("/pipeline")
async def alfa_pipeline(stage: str | None = None, limit: int = 50):
    """Return the complete lead-to-revenue pipeline and honest totals."""
    from openjarvis.one_agents.revenue import list_pipeline

    return list_pipeline(stage=stage, limit=limit)


@alfa_router.get("/artifact")
async def alfa_artifact(url: str, kind: str):
    from openjarvis.one_agents.revenue import get_artifact

    try:
        path = get_artifact(url, kind)
        return FileResponse(path, media_type="text/markdown", filename=path.name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@alfa_router.post("/approve")
async def approve_alfa_opportunity(req: AlfaOpportunityActionRequest):
    """Approve a packaged lead. This does NOT send the outreach message —
    it only confirms the offer/pricing and hands the lead to BETA to produce
    a concrete delivery plan. The outreach draft still needs to be copied
    and sent by Vineet.
    """
    from openjarvis.one_agents.revenue import approve_outreach

    try:
        opportunity = approve_outreach(req.url)
        return {"status": "outreach_approved", "opportunity": opportunity}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Failed to approve ALFA opportunity %s: %s", req.url, exc)
        raise HTTPException(status_code=500, detail="Failed to approve opportunity") from exc


@alfa_router.post("/dismiss")
async def dismiss_alfa_opportunity(req: AlfaOpportunityActionRequest):
    """Dismiss a lead ALFA surfaced (not worth pursuing)."""
    from openjarvis.one_agents.revenue import mark_lost

    try:
        updated = mark_lost(req.url)
    except ValueError:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return {"status": "dismissed", "opportunity": updated}


@alfa_router.post("/outreach-sent")
async def alfa_outreach_sent(req: AlfaOutreachRequest):
    from openjarvis.one_agents.revenue import record_outreach

    try:
        opportunity = record_outreach(req.url, req.channel, req.client_contact, req.client_name)
        return {"status": "contacted", "opportunity": opportunity}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@alfa_router.post("/response")
async def alfa_record_response(req: AlfaResponseRequest):
    from openjarvis.one_agents.revenue import record_response

    try:
        opportunity = record_response(req.url, req.response_text)
        return {"status": opportunity["pipeline_stage"], "opportunity": opportunity}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@alfa_router.post("/prepare-deal")
async def alfa_prepare_deal(req: AlfaOpportunityActionRequest):
    from openjarvis.one_agents.revenue import prepare_deal

    try:
        opportunity = prepare_deal(req.url)
        return {"status": "proposal_ready", "opportunity": opportunity}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@alfa_router.post("/payment")
async def alfa_record_payment(req: AlfaPaymentRequest):
    """Record verified payment, then queue BETA delivery automatically."""
    from openjarvis.one_agents.revenue import record_payment

    try:
        result = record_payment(req.url, req.amount, req.reference, req.payment_link)
        return {"status": "delivery_queued", **result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@alfa_router.post("/payment-webhook")
async def alfa_payment_webhook(request: Request):
    """Provider-neutral signed hook for n8n or a payment-provider adapter."""
    secret = os.environ.get("ALFA_PAYMENT_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="ALFA_PAYMENT_WEBHOOK_SECRET is not configured")
    body = await request.body()
    supplied = request.headers.get("x-one-signature", "")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid payment webhook signature")
    try:
        payload = json.loads(body)
        from openjarvis.one_agents.revenue import record_payment

        result = record_payment(
            str(payload["url"]), int(payload["amount"]), str(payload["reference"]), str(payload.get("payment_link", ""))
        )
        return {"status": "delivery_queued", **result}
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@alfa_router.post("/start-delivery")
async def alfa_start_delivery(req: AlfaDeliveryRequest):
    from openjarvis.one_agents.revenue import start_delivery

    try:
        return {"status": "delivery_queued", **start_delivery(req.url, req.allow_unpaid)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@alfa_router.post("/complete")
async def alfa_complete_delivery(req: AlfaCompleteRequest):
    from openjarvis.one_agents.revenue import complete_delivery

    try:
        opportunity = complete_delivery(req.url, req.activate_retainer)
        return {"status": opportunity["pipeline_stage"], "opportunity": opportunity}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def include_all_routes(app) -> None:
    """Include all extended API routers in a FastAPI app."""
    from openjarvis.server.approval_routes import (
        router as approval_router,  # noqa: PLC0415
    )

    app.include_router(approval_router)
    app.include_router(agents_router)
    app.include_router(memory_router)
    app.include_router(traces_router)
    app.include_router(telemetry_router)
    app.include_router(skills_router)
    app.include_router(sessions_router)
    app.include_router(budget_router)
    app.include_router(metrics_router)
    app.include_router(websocket_router)
    app.include_router(learning_router)
    app.include_router(speech_router)
    app.include_router(feedback_router)
    app.include_router(optimize_router)
    app.include_router(alfa_router)

    # Agent Manager routes (if available)
    try:
        if hasattr(app.state, "agent_manager") and app.state.agent_manager:
            from openjarvis.server.agent_manager_routes import (  # noqa: PLC0415
                create_agent_manager_router,
            )

            (
                agents_r,
                templates_r,
                global_r,
                tools_r,
                sendblue_r,
            ) = create_agent_manager_router(app.state.agent_manager)
            app.include_router(agents_r)
            app.include_router(templates_r)
            app.include_router(global_r)
            app.include_router(tools_r)
            app.include_router(sendblue_r)
    except ImportError:
        pass

    # WebSocket bridge for real-time agent events
    try:
        from openjarvis.core.events import get_event_bus
        from openjarvis.server.ws_bridge import create_ws_router

        ws_router = create_ws_router(get_event_bus())
        app.include_router(ws_router)
    except Exception:
        logger.debug("WebSocket bridge not available", exc_info=True)


__all__ = [
    "include_all_routes",
    "agents_router",
    "memory_router",
    "traces_router",
    "telemetry_router",
    "skills_router",
    "sessions_router",
    "budget_router",
    "metrics_router",
    "websocket_router",
    "learning_router",
    "speech_router",
    "feedback_router",
    "optimize_router",
    "alfa_router",
]

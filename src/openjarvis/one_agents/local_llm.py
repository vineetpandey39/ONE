"""Which local model runs which job, CPU-only, walking the installed fleet instead of one hardcoded name.

The machine has a small GPU that is nearly full, so every call here runs on the CPU and unloads
right after. Small structured jobs (chapter names, tags, hashtags) go to the small fast models;
anything that needs real multilingual strength goes to the large ones. If a model is missing or its
answer cannot be used, the next installed model is tried before the caller falls back to plain text.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Callable

OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")

# Preference order per kind of job. Only models that are actually installed are used.
LADDERS = {
    "short": ("ministral-3:3b", "phi4-mini", "ibm/granite4.1:3b", "qwen3:8b", "qwen3.5:9b", "llama3.1:8b"),
    "multilingual": ("qwen3.5:9b", "qwen3:8b", "llama3.1:8b", "ministral-3:3b"),
}
ENV_OVERRIDE = {"short": "ONE_SEO_MODEL", "multilingual": "ONE_TRANSLATE_MODEL"}


def installed(fetch: Callable[[str], dict] | None = None) -> list[str]:
    try:
        if fetch:
            return [m["name"] for m in fetch("/api/tags").get("models", [])]
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=3) as r:
            return [m["name"] for m in json.loads(r.read()).get("models", [])]
    except Exception:  # noqa: BLE001 - no Ollama means no models, not a crash
        return []


def ladder(kind: str, names: list[str] | None = None) -> list[str]:
    """Installed models for this kind of job, best first. An env override goes first but must be installed."""
    have = names if names is not None else installed()
    order = [os.environ[ENV_OVERRIDE[kind]]] if os.environ.get(ENV_OVERRIDE[kind]) else []
    order += list(LADDERS[kind])
    ready = [m for m in dict.fromkeys(order) if m in have or f"{m}:latest" in have]
    return ready


def options(temperature: float, num_ctx: int) -> dict:
    """CPU-only unless ONE_LLM_ALLOW_GPU=1: a model loaded onto this machine's nearly full 8 GB GPU took the
    whole system down once."""
    opts: dict = {"temperature": temperature, "num_ctx": num_ctx}
    if os.environ.get("ONE_LLM_ALLOW_GPU") != "1":
        opts.update(num_gpu=0, num_thread=int(os.environ.get("ONE_LLM_THREADS", "8")))
    return opts


def chat_json(model: str, system: str, payload: dict, *, temperature: float, num_ctx: int, timeout: int = 1800) -> dict:
    body = {"model": model, "stream": False, "think": False, "format": "json", "keep_alive": 0,
            "options": options(temperature, num_ctx),
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]}
    req = urllib.request.Request(OLLAMA + "/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(json.loads(r.read())["message"]["content"])


def run(kind: str, system: str, payload: dict, *, temperature: float = 0.2, num_ctx: int = 8192,
        chat: Callable[..., dict] = chat_json, names: list[str] | None = None) -> dict:
    """Try each installed model for this kind of job until one returns parseable JSON."""
    models = ladder(kind, names)
    if not models:
        raise RuntimeError(f"no installed local model for {kind} work")
    last: Exception | None = None
    for model in models:
        try:
            return chat(model, system, payload, temperature=temperature, num_ctx=num_ctx)
        except Exception as exc:  # noqa: BLE001 - walk to the next model
            last = exc
    raise RuntimeError(f"every local model failed for {kind} work: {type(last).__name__}: {last}")

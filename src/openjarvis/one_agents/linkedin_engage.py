"""LinkedIn Engagement Desk plumbing: ARES briefs, five workers act, one file remembers.

The decisions (what is worth commenting on, what a safe comment is, who may write and who must review, how many per
day) live in floors/floor_03_growth/lib (engage_*.py, decorum.py) and engage/policy.json. This file is only the
plumbing that needs ONE's runtime: the LAO tool, Sanjeevani, the model voices, stages and the cycle file. It never
imports runtime.py; the runtime hands in what it owns.

One cycle = one pass through the desk, kept in a single JSON file so a restart or a busy head loses nothing:

  hunt     ARES -> ORION (find)  -> QUILL (write) -> THEMIS (vet) -> NUNTIUS (deliver) -> ARES (file)
  replies  ARES -> HESTIA (triage) -> QUILL (write) -> THEMIS (vet) -> NUNTIUS (deliver) -> ARES (file)

Safety shape, in the order it matters
  1. Nothing is sent unless the policy mode is "auto". In "shadow" (the default) every draft is found, written, vetted
     and recorded, and nothing leaves the building.
  2. A comment is sent only if THEMIS cleared it (code rulebook AND a reviewer from a different model family) and
     NUNTIUS re-verifies the seal and re-runs the rulebook immediately before sending.
  3. Caps, gaps, quiet hours and the author cooldown are enforced from the ledger, not from a prompt.
  4. A send that may have posted is never retried (status "unknown").
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

from openjarvis.one_agents import floors_bridge, linkedin_growth

FLOOR = "floor_03_growth"
ENGAGE_PROCESS = "LinkedIn Engage - Comment"
DRAFT_PROCESS = "LinkedIn Engage - Draft"
END_MARKER_INSTRUCTION = " After the JSON, on its own final line, write exactly: ===ENGAGE_END==="
MARKERS = {"[linkedin-engage-hunt]": "hunt", "[linkedin-engage-replies]": "replies"}
BRAND = "linkedin_engage"
STAGES = {"hunt": ["new", "hunted", "drafted", "vetted", "delivered"],
          "replies": ["new", "triaged", "drafted", "vetted", "delivered"]}
LEGS = {"hunt": ["orion", "quill", "themis", "nuntius"], "replies": ["hestia", "quill", "themis", "nuntius"]}
CYCLE_MAX_AGE = 12 * 3600


class Libs:
    def __init__(self) -> None:
        self.policy = floors_bridge.load(FLOOR, "engage_policy")
        self.hunt = floors_bridge.load(FLOOR, "engage_hunt")
        self.voice = floors_bridge.load(FLOOR, "engage_voice")
        self.models = floors_bridge.load(FLOOR, "engage_models")
        self.decorum = floors_bridge.load(FLOOR, "decorum")

    @property
    def ready(self) -> bool:
        return all((self.policy, self.hunt, self.voice, self.models, self.decorum))


def libs() -> Libs | None:
    bundle = Libs()
    return bundle if bundle.ready else None


# --------------------------------------------------------------------------- files

def engage_dir(home: Path) -> Path:
    path = linkedin_growth.agent_dir(home) / "engage"
    (path / "cycles").mkdir(parents=True, exist_ok=True)
    (path / "inbox").mkdir(parents=True, exist_ok=True)
    return path


def kind_of_task(task: str) -> str:
    low = (task or "").lower()
    return next((kind for marker, kind in MARKERS.items() if marker in low), "")


def is_engage_payload(payload: dict[str, Any]) -> bool:
    return payload.get("brand") == BRAND


def _now(now: float | None) -> float:
    return time.time() if now is None else now


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(path: Path, value: Any) -> None:
    bundle = libs()
    if bundle is not None:
        bundle.policy.save_json(path, value)
    else:  # pragma: no cover - libs missing means the desk cannot run; still never half-write
        path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")


def load_cycle(home: Path, cycle_id: str) -> dict[str, Any]:
    return _load(engage_dir(home) / "cycles" / f"{cycle_id}.json", {})


def save_cycle(home: Path, cycle: dict[str, Any]) -> None:
    _save(engage_dir(home) / "cycles" / f"{cycle['id']}.json", cycle)


def comments_ledger(home: Path) -> list[dict[str, Any]]:
    return _load(engage_dir(home) / "comments.json", [])


def handled(home: Path) -> dict[str, float]:
    return _load(engage_dir(home) / "handled.json", {})


def mark_handled(home: Path, urn: str, now: float) -> None:
    rows = handled(home)
    rows[urn] = now
    _save(engage_dir(home) / "handled.json", {k: v for k, v in rows.items() if now - float(v) < 90 * 86400})


# --------------------------------------------------------------------------- ARES side

def next_worker(cycle: dict[str, Any]) -> str:
    """The worker ARES should brief next, or '' when the cycle is finished."""
    order = STAGES[cycle["kind"]]
    stage = cycle.get("stage", "new")
    if stage == "delivered" or stage not in order:
        return ""
    return LEGS[cycle["kind"]][order.index(stage)]


def begin_cycle(kind: str, home: Path, *, job_id: str, now: float | None = None) -> dict[str, Any]:
    """Start a cycle, or resume the newest unfinished one of this kind (a busy head never loses work)."""
    at = _now(now)
    folder = engage_dir(home) / "cycles"
    for path in sorted(folder.glob("*.json"), reverse=True):
        old = _load(path, {})
        if old.get("kind") == kind and old.get("stage") != "delivered" and at - float(old.get("created", 0)) < CYCLE_MAX_AGE:
            old["resumed"] = True
            return old
    cycle_id = f"{kind}-{time.strftime('%Y%m%d-%H%M%S', time.gmtime(at))}-{hashlib.sha1(job_id.encode()).hexdigest()[:6]}"
    n = len(list(folder.glob(f"{kind}-*.json")))
    cycle = {"id": cycle_id, "kind": kind, "stage": "new", "created": at, "n": n, "origin_job": job_id, "notes": []}
    save_cycle(home, cycle)
    return cycle


def desk_blocked(now: float | None = None) -> str:
    """Why the head must not start or continue a leg right now ('' when it may)."""
    bundle = libs()
    if bundle is None:
        return "Floor 3 engagement modules could not be loaded"
    policy = bundle.policy.load_policy()
    if bundle.policy.in_post_window(policy, now):
        return "ARES is reserved for the 17:30 LinkedIn post"
    return ""


def close(cycle: dict[str, Any], reason: str) -> None:
    cycle["stage"] = "delivered"
    cycle["closed_reason"] = reason


# --------------------------------------------------------------------------- ORION

def run_hunt(cycle: dict[str, Any], home: Path, *, search: Callable[[list[str]], list[dict[str, Any]]],
             now: float | None = None) -> dict[str, Any]:
    """Find acceptable fresh posts. Reports a thin catch as thin; never pads with stale posts."""
    at = _now(now)
    bundle = libs()
    policy = bundle.policy.load_policy()
    rows = comments_ledger(home)
    if bundle.policy.shadow_remaining(rows, policy) == 0 and not bundle.policy.posting_enabled(policy) \
            and int(policy.get("shadow_comments_before_review", 0)) > 0:
        close(cycle, "shadow quota reached: waiting for the Chairman to review the drafts and switch the desk to auto")
        return cycle
    verdict = bundle.policy.allowance(rows, policy, kind="comment", now=at)
    if bundle.policy.posting_enabled(policy) and not verdict["ok"] and verdict["reason"] != "minimum gap":
        close(cycle, f"nothing to hunt for: {verdict['reason']}")
        return cycle

    queries = bundle.hunt.build_queries(policy, cycle=int(cycle.get("n", 0)))
    try:
        hits = search(queries)
        search_error = ""
    except Exception as exc:  # noqa: BLE001 - a dead search is reported, not hidden
        hits, search_error = [], f"{type(exc).__name__}: {exc}"[:200]
    web = bundle.hunt.from_hits(hits)
    inbox_file = engage_dir(home) / "inbox" / "links.txt"
    inbox = bundle.hunt.from_inbox(inbox_file.read_text(encoding="utf-8") if inbox_file.is_file() else "")

    seen = set(handled(home)) | {r.get("target", "") for r in rows}
    cooldown = policy["limits"]["same_author_cooldown_days"] * 86400
    recent_authors = {r.get("author_slug", "") for r in rows
                      if r.get("kind") == "comment" and r.get("status") in {"posted", "shadow"}
                      and at - float(r.get("ts", 0)) < cooldown and r.get("author_slug")}
    unique: dict[str, dict[str, Any]] = {}
    for cand in inbox + web:  # the inbox is the fresh source, so it wins a tie
        unique.setdefault(cand["urn"], cand)
    judged = [bundle.hunt.judge(c, policy, niche_of=bundle.policy.niche_of, blocked_topic=bundle.policy.blocked_topic,
                                seen_urns=seen, recent_authors=recent_authors, now=at) for c in unique.values()]
    chosen = bundle.hunt.select(judged, limit=int(os.environ.get("ONE_ENGAGE_PER_CYCLE", "4")))
    reasons: dict[str, int] = {}
    for item in judged:
        for reason in item["reasons"]:
            key = reason.split(":")[0]
            reasons[key] = reasons.get(key, 0) + 1
    cycle["search"] = {"queries": queries, "hits": len(hits), "web_posts": len(web), "inbox_posts": len(inbox),
                       "judged": len(judged), "rejected_for": reasons, "error": search_error}
    cycle["candidates"] = chosen
    if chosen:
        cycle["stage"] = "hunted"
    else:
        close(cycle, "no fresh, on-niche, safe posts this cycle" + (f" (search error: {search_error})" if search_error else ""))
    return cycle


# --------------------------------------------------------------------------- QUILL

def run_write(cycle: dict[str, Any], voices: dict[str, Callable[[str], str]]) -> dict[str, Any]:
    """Draft one comment/reply per item with the writer voice the roster picks. Never judges its own work."""
    bundle = libs()
    policy = bundle.policy.load_policy()
    replies = cycle["kind"] == "replies"
    items = cycle.get("to_reply" if replies else "candidates") or []
    fixes = cycle.get("fix") or None  # set by THEMIS for the single rework pass
    if fixes:
        items = [i for i in items if i["id"] in fixes]
    if not items:
        close(cycle, "nothing to write")
        return cycle
    ids = [i["id"] for i in items]
    prompt = (bundle.voice.reply_prompt(items, policy, fixes) if replies
              else bundle.voice.comment_prompt(items, policy, fixes))
    tried: list[str] = []
    drafts: dict[str, dict[str, str]] = {}
    writer = ""
    while True:
        pairing = bundle.models.plan([v for v in voices if v not in tried], policy)
        if not pairing["ok"]:
            cycle.setdefault("notes", []).append(pairing["reason"])
            break
        writer = pairing["writer"]
        try:
            raw = voices[writer](prompt)
        except Exception as exc:  # noqa: BLE001 - one voice failing sends us to the next
            cycle.setdefault("notes", []).append(f"{writer} failed: {type(exc).__name__}: {str(exc)[:120]}")
            tried.append(writer)
            continue
        drafts = bundle.voice.parse_drafts(raw, ids, field="reply" if replies else "comment")
        if drafts:
            break
        cycle.setdefault("notes", []).append(f"{writer} returned nothing usable")
        tried.append(writer)
    if not drafts:
        close(cycle, "no writer produced a usable draft" if writer else "no writer and independent reviewer are reachable")
        return cycle
    cycle["writer"] = writer
    cycle["drafts"] = {i: {**d, "writer": writer} for i, d in drafts.items()}
    cycle["stage"] = "drafted"
    return cycle


# --------------------------------------------------------------------------- THEMIS

def _item_for(cycle: dict[str, Any], item_id: str) -> dict[str, Any]:
    pool = cycle.get("to_reply" if cycle["kind"] == "replies" else "candidates") or []
    return next((i for i in pool if i["id"] == item_id), {})


def run_vet(cycle: dict[str, Any], voices: dict[str, Callable[[str], str]]) -> dict[str, Any]:
    """Code rulebook, then an independent reviewer. A draft is cleared only if both say yes."""
    bundle = libs()
    policy = bundle.policy.load_policy()
    replies = cycle["kind"] == "replies"
    kind = "reply" if replies else "comment"
    invite = policy["replies"]["invite_dm_phrase"]
    writer = cycle.get("writer", "")
    reviewer = bundle.models.pick_reviewer(list(voices), policy, writer)
    results: list[dict[str, Any]] = []
    survivors: list[dict[str, str]] = []
    for item_id, draft in (cycle.get("drafts") or {}).items():
        item = _item_for(cycle, item_id)
        if "text" not in draft:
            results.append({"id": item_id, "cleared": False, "stage": "writer", "reasons": [draft.get("skip", "skipped")]})
            continue
        code = bundle.decorum.check_comment(
            draft["text"], post_text=item.get("comment" if replies else "text", ""), kind=kind, invite_phrase=invite,
            min_words=10 if replies else 14, max_words=60 if replies else 75, specific=not replies)
        results.append({"id": item_id, "text": draft["text"], "code": code})
        if code["ok"]:
            survivors.append({"id": item_id, "post": item.get("comment" if replies else "text", ""), "comment": draft["text"]})
    reviews: dict[str, dict[str, str]] = {}
    review_note = ""
    if survivors and reviewer:
        try:
            raw = voices[reviewer](bundle.decorum.review_prompt(survivors))
            reviews = bundle.decorum.parse_review(raw, [s["id"] for s in survivors])
        except Exception as exc:  # noqa: BLE001 - a reviewer that fails means HOLD, never "approve by default"
            review_note = f"reviewer {reviewer} failed: {type(exc).__name__}: {str(exc)[:120]}"
    elif survivors:
        review_note = "no reviewer from a different model family is reachable"
    vetted = []
    for row in results:
        if "code" not in row:
            vetted.append(row)
            continue
        item = _item_for(cycle, row["id"])
        decision = bundle.decorum.decide(row["code"], reviews.get(row["id"]))
        if not decision["cleared"] and decision["stage"] == "review" and review_note:
            decision["reasons"] = [review_note]  # say what actually went wrong, not "none was available"
        target = item.get("urn") or item.get("post_urn", "")
        entry = {"id": row["id"], "kind": kind, "target": target, "author": item.get("author") or item.get("commenter", ""),
                 "author_slug": item.get("author_slug", ""), "text": row["text"], "cleared": decision["cleared"],
                 "stage": decision["stage"], "reasons": decision["reasons"], "writer": writer, "reviewer": reviewer,
                 "parent_comment": item.get("parent_comment", ""), "posted_ts": item.get("posted_ts", 0)}
        if decision["cleared"]:
            entry["seal"] = bundle.decorum.seal(kind, target + "|" + entry["parent_comment"], row["text"])
        vetted.append(entry)
    cycle["vetted"] = vetted
    cycle["reviewer"] = reviewer
    if review_note:
        cycle.setdefault("notes", []).append(review_note)
    if any(v.get("cleared") for v in vetted):
        cycle["stage"] = "vetted"
        return cycle
    # Nothing cleared. A draft refused for tone or content can be rewritten once, with the exact reasons; one refused
    # because no independent reviewer answered cannot be fixed by writing again, so that closes the cycle.
    fixable = {v["id"]: v["reasons"] for v in vetted
               if not v.get("cleared") and v.get("reasons")
               and (v.get("stage") == "code" or (v.get("stage") == "review" and not review_note))}
    if fixable and int(cycle.get("attempt", 0)) < 1:
        cycle["attempt"] = 1
        cycle["fix"] = fixable
        cycle["held_first_pass"] = vetted
        cycle["stage"] = "triaged" if replies else "hunted"
        cycle.setdefault("notes", []).append("THEMIS held every draft; one rework pass requested")
    else:
        close(cycle, "THEMIS held every draft")
    return cycle


# --------------------------------------------------------------------------- NUNTIUS

def run_deliver(cycle: dict[str, Any], home: Path, *, send: Callable[[dict[str, Any]], dict[str, Any]],
                now: float | None = None) -> dict[str, Any]:
    """Send what THEMIS cleared, inside the caps - or, in shadow mode, record it and send nothing."""
    bundle = libs()
    policy = bundle.policy.load_policy()
    auto = bundle.policy.posting_enabled(policy)
    invite = policy["replies"]["invite_dm_phrase"]
    ledger_path = engage_dir(home) / "comments.json"
    outcomes = []
    for item in cycle.get("vetted") or []:
        at = _now(now)
        base = {"kind": item.get("kind", "comment"), "cycle": cycle["id"], "target": item.get("target", ""),
                "author": item.get("author", ""), "author_slug": item.get("author_slug", ""),
                "text": item.get("text", ""), "writer": item.get("writer", ""), "reviewer": item.get("reviewer", "")}
        if not item.get("cleared"):
            outcomes.append({**base, "status": "held", "reasons": item.get("reasons", [])})
            if base["kind"] == "comment" and base["target"]:
                mark_handled(home, base["target"], at)
            continue
        kind = item["kind"]
        seal_target = item["target"] + "|" + item.get("parent_comment", "")
        recheck = bundle.decorum.check_comment(
            item["text"], post_text=(_item_for(cycle, item["id"]).get("comment" if kind == "reply" else "text", "")),
            kind=kind, invite_phrase=invite, min_words=10 if kind == "reply" else 14,
            max_words=60 if kind == "reply" else 75, specific=kind != "reply")
        if not bundle.decorum.seal_ok(kind, seal_target, item["text"], item.get("seal", "")) or not recheck["ok"]:
            outcomes.append({**base, "status": "held", "reasons": ["seal or rulebook re-check failed before sending"]})
            continue
        if kind == "comment" and at - float(item.get("posted_ts", at)) > policy["limits"]["max_post_age_hours"] * 3600:
            outcomes.append({**base, "status": "held", "reasons": ["post went stale before sending"]})
            continue
        if not auto:
            outcomes.append({**base, "status": "shadow", "reasons": ["desk is in shadow mode: vetted, recorded, not sent"]})
            if kind == "comment":
                mark_handled(home, base["target"], at)
            continue
        if kind == "reply" and not item.get("parent_comment"):
            outcomes.append({**base, "status": "manual", "reasons": ["no comment URN (inbox source): post this reply by hand"]})
            continue
        allow = bundle.policy.allowance(comments_ledger(home), policy, kind=kind, author=base["author_slug"], now=at)
        if not allow["ok"]:
            outcomes.append({**base, "status": "deferred", "reasons": [allow["reason"]]})
            continue
        try:
            sent = send(item)
        except Exception as exc:  # noqa: BLE001 - after a start attempt the outcome is unknown; never retry blindly
            sent = {"status": "unknown", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        status = sent.get("status", "unknown")
        outcomes.append({**base, "status": status, "lao_job": sent.get("lao_job", ""),
                         "comment_urn": sent.get("comment_urn", ""), "reasons": [sent["error"]] if sent.get("error") else []})
        if status in {"posted", "unknown"} and kind == "comment":
            mark_handled(home, base["target"], at)
    for outcome in outcomes:
        bundle.policy.record(ledger_path, outcome, now=now)
    cycle["delivered"] = outcomes
    cycle["stage"] = "delivered"
    return cycle


# --------------------------------------------------------------------------- HESTIA

def _classify(text: str, bundle: Libs, policy: dict[str, Any]) -> tuple[str, str]:
    """(verdict, label): verdict is 'answer' or 'skip'. Abuse, spam and promotion are never answered."""
    probe = bundle.decorum.check_comment(text, kind="comment", min_words=1, max_words=400, specific=False)
    problems = " ".join(probe["problems"])
    if "abusive" in problems or "explicit" in problems or "violent" in problems:
        return "skip", "abuse"
    if "self-promotion" in problems or "link or domain" in problems or "email or phone" in problems:
        return "skip", "spam"
    if "accusatory" in problems:
        return "skip", "hostile"
    if bundle.policy.blocked_topic(text, policy):
        return "skip", "sensitive"
    words = len(re.findall(r"[A-Za-z']+", text))
    if "?" in text or re.match(r"(?i)\s*(how|what|why|can|could|should|which|where|any)\b", text):
        return "answer", "question"
    if words >= 7:
        return "answer", "thought"
    return "skip", "praise-only"


def run_triage(cycle: dict[str, Any], home: Path, *, read_api: Callable[[], list[dict[str, Any]]] | None,
               now: float | None = None) -> dict[str, Any]:
    """Collect comments on the Chairman's own recent posts (API if allowed, else the reply inbox) and triage them."""
    at = _now(now)
    bundle = libs()
    policy = bundle.policy.load_policy()
    gathered: list[dict[str, Any]] = []
    source = "inbox"
    if read_api is not None:
        try:
            gathered = read_api()
            source = "api"
        except Exception as exc:  # noqa: BLE001 - fall back to the inbox, say so
            cycle.setdefault("notes", []).append(f"API read failed: {type(exc).__name__}: {str(exc)[:120]}")
    inbox_file = engage_dir(home) / "inbox" / "replies.txt"
    if inbox_file.is_file():
        for line in inbox_file.read_text(encoding="utf-8").splitlines():
            parts = [p.strip() for p in line.split("|", 2)]
            if len(parts) == 3 and parts[0] and parts[2] and not line.lstrip().startswith("#"):
                gathered.append({"post_urn": parts[0], "commenter": parts[1], "comment": parts[2], "parent_comment": "",
                                 "post_title": "", "created_ts": at})
    done = {r.get("source_id") for r in comments_ledger(home) if r.get("kind") == "reply"}
    window = policy["replies"]["answer_within_hours"] * 3600
    answer, skipped = [], []
    for row in gathered:
        sid = hashlib.sha1(f"{row.get('post_urn')}|{row.get('commenter')}|{row.get('comment')}".encode("utf-8")).hexdigest()[:12]
        if sid in done or at - float(row.get("created_ts") or at) > window:
            continue
        verdict, label = _classify(row.get("comment", ""), bundle, policy)
        entry = {**row, "id": sid, "label": label}
        (answer if verdict == "answer" else skipped).append(entry)
    cycle["triage"] = {"source": source, "seen": len(gathered), "answer": len(answer), "skipped": [
        {"id": s["id"], "label": s["label"]} for s in skipped]}
    cycle["to_reply"] = answer[: int(os.environ.get("ONE_ENGAGE_REPLIES_PER_CYCLE", "6"))]
    if cycle["to_reply"]:
        cycle["stage"] = "triaged"
    else:
        close(cycle, "no comment on the Chairman's posts needs a reply right now")
    return cycle


# --------------------------------------------------------------------------- voices (the four models)

def _http_json(url: str, body: dict[str, Any], *, headers: dict[str, str] | None = None, timeout: float = 600) -> dict[str, Any]:
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def voice_qwen(prompt: str) -> str:
    """Local Qwen through Ollama, CPU only (a model on this machine's 8 GB GPU took the whole system down once)."""
    base = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
    model = os.environ.get("ONE_ENGAGE_LOCAL_MODEL", "qwen3.5:9b")
    options = {"temperature": 0.4, "num_ctx": 8192, "num_predict": 900, "num_gpu": 0,
               "num_thread": int(os.environ.get("ONE_LLM_THREADS", "8"))}
    data = _http_json(base + "/api/chat", {"model": model, "stream": False, "think": False, "options": options,
                                           "messages": [{"role": "user", "content": prompt}]}, timeout=900)
    return str((data.get("message") or {}).get("content") or "")


def voice_nemotron(prompt: str) -> str:
    key = os.environ.get("NVIDIA_API_KEY", "").strip()
    model = os.environ.get("NEMOTRON_MODEL", "").strip()
    if not key or not model:
        raise RuntimeError("Nemotron is not configured")
    host = os.environ.get("NVIDIA_HOST", "https://integrate.api.nvidia.com").rstrip("/")
    data = _http_json(host + "/v1/chat/completions", {"model": model, "temperature": 0.4, "max_tokens": 900,
                                                      "messages": [{"role": "user", "content": prompt}]},
                      headers={"Authorization": f"Bearer {key}"}, timeout=180)
    return str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")


def voice_claude_cli(prompt: str) -> str:
    """The Claude CLI in one-shot, no-tools mode, from a scratch folder so it can touch nothing of ours."""
    exe = shutil.which(os.environ.get("ONE_CLAUDE_CLI", "claude"))
    if not exe:
        raise RuntimeError("Claude CLI not found")
    import tempfile
    with tempfile.TemporaryDirectory() as scratch:
        # The prompt goes in on stdin: --disallowedTools is variadic and would swallow a positional prompt.
        done = subprocess.run([exe, "-p", "--max-turns", "1", "--output-format", "text",
                               "--disallowedTools", "Bash,Edit,Write,Read,WebFetch,WebSearch"],
                              input=prompt, capture_output=True, text=True, timeout=240, cwd=scratch)
    if done.returncode != 0:
        raise RuntimeError(f"claude exited {done.returncode}: {done.stderr[:160]}")
    return done.stdout


def voice_chatgpt(tool: Any, roots: tuple[Path, ...], heartbeat: Callable[[], None]) -> Callable[[str], str]:
    """ChatGPT through the desk's own LAO process, "LinkedIn Engage - Draft".

    It is separate from the daily post's draft process on purpose: that one waits for the post's own end markers
    and would "nudge" ChatGPT forever for an answer that does not contain them (seen 2026-11-07).
    """
    def call(prompt: str) -> str:
        started = tool.execute(action="start", mode="publish", process_name=DRAFT_PROCESS, scope="production",
                               confirm_publish=True,
                               input_args={"prompt": prompt + END_MARKER_INSTRUCTION, "chatgptCredentialAssetName": "chatgptLogin"})
        if not started.success:
            raise RuntimeError(f"LAO refused the ChatGPT draft: {str(started.content)[:200]}")
        lao_job = str(((started.metadata or {}).get("job") or {}).get("id") or "")
        if not lao_job:
            raise RuntimeError("LAO returned no job id for the ChatGPT draft")
        status, _ = linkedin_growth._poll(tool, DRAFT_PROCESS, lao_job, max_wait=420.0, poll=10.0,
                                          sleep=time.sleep, heartbeat=heartbeat)
        found = linkedin_growth._find_artifact(roots, lao_job, "linkedin_engage_draft.json") if status == "Successful" else None
        raw = ""
        if found:
            try:
                raw = str(json.loads(found.read_text(encoding="utf-8"))[0].get("output") or "")
            except (OSError, ValueError, IndexError, AttributeError):
                raw = ""
        if not raw:
            raise RuntimeError(f"no ChatGPT draft artifact ({status})")
        return raw
    return call


def available_voices(tool: Any, roots: tuple[Path, ...], heartbeat: Callable[[], None]) -> dict[str, Callable[[str], str]]:
    """Only voices that look reachable right now. Cheap checks; a voice that then fails is skipped by the callers."""
    voices: dict[str, Callable[[str], str]] = {}
    try:
        with urllib.request.urlopen(os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/tags", timeout=3) as r:
            names = [m.get("name", "") for m in json.loads(r.read()).get("models", [])]
        if any(n.startswith(os.environ.get("ONE_ENGAGE_LOCAL_MODEL", "qwen3.5:9b").split(":")[0]) for n in names):
            voices["qwen_local"] = voice_qwen
    except Exception:  # noqa: BLE001 - no Ollama, no local voice
        pass
    if os.environ.get("NVIDIA_API_KEY", "").strip() and os.environ.get("NEMOTRON_MODEL", "").strip():
        voices["nemotron"] = voice_nemotron
    if shutil.which(os.environ.get("ONE_CLAUDE_CLI", "claude")) and os.environ.get("ONE_ENGAGE_ALLOW_CLAUDE_CLI", "1") == "1":
        voices["claude_cli"] = voice_claude_cli
    if tool is not None:
        voices["chatgpt_lao"] = voice_chatgpt(tool, roots, heartbeat)
    return voices


# --------------------------------------------------------------------------- LAO send / read

def lao_send(tool: Any, roots: tuple[Path, ...], item: dict[str, Any], *, attach: Callable[[str], None],
             heartbeat: Callable[[], None], dry_run: bool = False, max_wait: float = 300.0,
             sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Start the LAO comment process for one cleared item and wait for its terminal status. Never retries."""
    args = {"postUrn": item["target"], "text": item["text"], "parentComment": item.get("parent_comment", "")}
    if dry_run:
        args["dryRun"] = "true"
    started = tool.execute(action="start", mode="publish", process_name=ENGAGE_PROCESS, scope="production",
                           confirm_publish=True, input_args=args)
    if not started.success:
        return {"status": "failed", "error": f"LAO refused to start: {str(started.content)[:200]}"}
    lao_job = str(((started.metadata or {}).get("job") or {}).get("id") or "")
    if not lao_job:
        return {"status": "unknown", "error": "LAO returned no job id"}
    attach(lao_job)
    status, last = linkedin_growth._poll(tool, ENGAGE_PROCESS, lao_job, max_wait=max_wait, poll=6.0, sleep=sleep,
                                         heartbeat=heartbeat)
    receipt: dict[str, Any] = {}
    found = linkedin_growth._find_artifact(roots, lao_job, "linkedin_engage_receipt.json")
    if found:
        receipt = _load(found, {})
    if status == "Successful" and receipt.get("status") in {"posted", "dry_run"}:
        return {"status": "posted" if receipt["status"] == "posted" else "shadow", "lao_job": lao_job,
                "comment_urn": receipt.get("comment_urn", "")}
    error = ""
    try:
        probe = tool.execute(action="status", process_name=ENGAGE_PROCESS, scope="production", job_id=lao_job, include_logs=True)
        text = json.dumps((probe.metadata if probe.success else last) or {}, default=str)
        for needle in ("token expired", "401", "requires the credential username", "throttled", "Unknown workflow action"):
            if needle in text:
                error = needle
                break
    except Exception:  # noqa: BLE001
        pass
    # "token expired" and "throttled" are raised before anything is sent; anything else may have posted.
    certain_not_posted = error in {"token expired", "requires the credential username", "throttled", "Unknown workflow action"}
    return {"status": "failed" if certain_not_posted else "unknown", "lao_job": lao_job,
            "error": f"LAO {status}" + (f": {error}" if error else "")}


def digest(cycle: dict[str, Any], policy_mode: str) -> str:
    """Three lines for the Chairman: what the desk did this cycle."""
    kind = cycle["kind"]
    delivered = cycle.get("delivered") or []
    counts: dict[str, int] = {}
    for row in delivered:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    head = f"LinkedIn desk ({kind}, mode {policy_mode}): "
    if cycle.get("closed_reason") and not delivered:
        return head + cycle["closed_reason"] + "."
    parts = ", ".join(f"{n} {s}" for s, n in sorted(counts.items())) or "nothing delivered"
    lines = [head + parts + "."]
    for row in delivered[:5]:
        lines.append(f"- [{row['status']}] {row.get('author') or 'post'}: {row['text'][:140]}")
    return "\n".join(lines)

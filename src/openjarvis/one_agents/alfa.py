"""ALFA: zero-paid-API recurring revenue agent.

ALFA does four things now, in order:
  1. Scout public forums (Reddit, Hacker News) for paid service requests.
  2. Score and classify each request into a service category.
  3. Package the top leads into an actual sellable offer: a plain-language
     service definition, a build plan, one-time + monthly-retainer pricing,
     and a ready-to-send outreach draft.
  4. Wait for human approval (never auto-sends anything — outreach involves
     contacting a stranger and quoting a price, which ``config.toml``'s
     safety rules require a human to confirm) and, once approved, hands the
     lead to BETA so a concrete delivery/build plan gets produced.

Packaging is done with the local Ollama model already running for ONE so it
costs nothing and never leaves the machine. If the model is unreachable or
returns something unparsable, a deterministic template fills in instead —
ALFA must never crash a scheduled scan because the LLM step failed.
"""

from __future__ import annotations

import html
import json
import os
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx


USER_AGENT = "ONE-ALFA/1.0 (local opportunity scout; contact: local-user)"
BUYER_TERMS = re.compile(r"\b(hiring|looking for|need(?:ing)?|seeking|wanted|paid|budget)\b", re.I)
SELLER_TERMS = re.compile(r"\[(?:for hire|offer)\]|\bavailable for work\b|\bmy portfolio\b", re.I)
SENSITIVE_OR_LOW_TRUST = re.compile(r"\b(adult|18\+|erotic|smut|casino|gambling|crypto pump|account rental|fake review)\b", re.I)
NON_SERVICE_JOB = re.compile(r"\b(full[- ]time|monthly salary|apply here|permanent position|employee benefits)\b", re.I)
UNPAID = re.compile(r"\b(volunteer|unpaid|free software|open source project needs help)\b", re.I)

# Service categories ALFA can classify a lead into. "range" is the fallback
# one-time USD estimate used when no explicit budget is mentioned in the post.
SERVICES: dict[str, dict[str, Any]] = {
    "blog-writing": {"terms": ("blog", "article", "copywriter", "content writer", "seo writer"), "range": (120, 700)},
    "video-editing": {"terms": ("video editor", "reels editor", "short form", "youtube editor", "premiere pro"), "range": (150, 900)},
    "design": {"terms": ("graphic designer", "logo", "thumbnail", "canva", "brand design", "ui designer"), "range": (100, 800)},
    "web-services": {"terms": ("website", "wordpress", "shopify", "web developer", "landing page", "frontend"), "range": (300, 2200)},
    "automation": {
        "terms": (
            "automation", "n8n", "zapier", "ai agent", "workflow", "scraping",
            "chatbot", "ai chatbot", "gpt", "openai", "llm", "voice assistant",
            "rag", "make.com", "integromat", "api integration", "crm automation",
        ),
        "range": (350, 2500),
    },
    "admin-support": {"terms": ("virtual assistant", "data entry", "research assistant", "customer support", "email management"), "range": (100, 700)},
    "lead-generation": {"terms": ("lead generation", "appointment setting", "cold email", "outreach", "sales leads"), "range": (250, 1500)},
    "delivery-operations": {"terms": ("delivery coordinator", "dispatch", "logistics support", "order fulfillment", "ecommerce assistant"), "range": (180, 1000)},
}

# Plain-language labels + a sane default build plan per category, used as the
# deterministic fallback when the LLM packaging step is unavailable.
SERVICE_LABELS: dict[str, dict[str, Any]] = {
    "blog-writing": {"label": "Blog & SEO content writing", "steps": ["Confirm topic, tone, and word count", "Draft and edit the piece", "Run an SEO/readability pass", "Deliver in Google Docs/Markdown with one revision round"]},
    "video-editing": {"label": "Short-form video editing", "steps": ["Get raw footage/brief and reference style", "Rough cut + sound/caption pass", "Color and pacing polish", "Export and deliver in requested format"]},
    "design": {"label": "Graphic / brand design", "steps": ["Collect brand assets and references", "Produce 2-3 concept directions", "Refine the chosen direction", "Deliver final files (source + export formats)"]},
    "web-services": {"label": "Website / landing page build", "steps": ["Confirm pages, content, and stack", "Build and connect domain/hosting", "QA on mobile + desktop", "Launch and hand over admin access"]},
    "automation": {"label": "AI automation / agent build", "steps": ["Map the manual workflow being replaced", "Build the automation/agent using ONE's existing agent runtime", "Test against real inputs and edge cases", "Deploy, document, and hand over with a usage guide"]},
    "admin-support": {"label": "Virtual assistant / admin support", "steps": ["Agree on scope and weekly hours", "Set up shared tools/access", "Run the first week as a trial", "Review and confirm ongoing cadence"]},
    "lead-generation": {"label": "Lead generation & outreach", "steps": ["Define ideal customer profile", "Build/verify a targeted contact list", "Launch outreach sequence", "Report replies and qualified leads weekly"]},
    "delivery-operations": {"label": "Delivery / logistics coordination", "steps": ["Map current order/dispatch flow", "Set up tracking and coordination process", "Run a pilot batch", "Hand over a documented SOP"]},
}

# ALFA is biased toward AI-automation/agent-build work because that is the
# service Vineet (via ONE) is actually best positioned to deliver. Other
# categories still qualify but score lower, so automation leads surface first.
HIGH_FIT_SERVICES = {"automation", "web-services", "lead-generation"}

REDDIT_FEEDS = {
    "Reddit r/forhire": "https://www.reddit.com/r/forhire/new/.rss",
    "Reddit r/freelance_forhire": "https://www.reddit.com/r/freelance_forhire/new/.rss",
}
HN_QUERIES = ("looking for freelancer", "hiring writer", "need video editor", "need website help", "hire automation", "need ai agent", "need chatbot")

# How many of the top-scoring leads get a full LLM-generated offer package
# (service definition, pricing, outreach draft) per scan. Kept small because
# this is a local model call per lead and ALFA runs on a background worker.
PACKAGE_TOP_N = 5


def _home() -> Path:
    return Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".openjarvis"))


class _ClosingConnection(sqlite3.Connection):
    """Commit/rollback like sqlite3's context manager, then release the file."""

    def __exit__(self, exc_type, exc_value, traceback):
        result = super().__exit__(exc_type, exc_value, traceback)
        self.close()
        return result


def _db() -> sqlite3.Connection:
    path = _home() / "alfa_opportunities.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30, factory=_ClosingConnection)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS opportunities (
            url TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            service TEXT NOT NULL,
            score INTEGER NOT NULL,
            budget_min INTEGER NOT NULL,
            budget_max INTEGER NOT NULL,
            currency TEXT NOT NULL,
            published_at TEXT NOT NULL,
            discovered_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new'
        )
        """
    )
    _migrate(db)
    db.commit()
    return db


# Columns added after the original schema. Each is additive and optional so
# older databases upgrade in place without losing any existing leads.
_NEW_COLUMNS: dict[str, str] = {
    "service_definition": "TEXT NOT NULL DEFAULT ''",
    "build_steps": "TEXT NOT NULL DEFAULT ''",        # JSON list
    "one_time_price": "INTEGER NOT NULL DEFAULT 0",
    "retainer_price": "INTEGER NOT NULL DEFAULT 0",     # suggested USD/month
    "retainer_pitch": "TEXT NOT NULL DEFAULT ''",
    "outreach_message": "TEXT NOT NULL DEFAULT ''",
    "approval_status": "TEXT NOT NULL DEFAULT 'pending_review'",  # pending_review | approved | dismissed
    "delivery_job_id": "TEXT NOT NULL DEFAULT ''",
}


def _migrate(db: sqlite3.Connection) -> None:
    existing = {row["name"] for row in db.execute("PRAGMA table_info(opportunities)").fetchall()}
    for column, ddl in _NEW_COLUMNS.items():
        if column not in existing:
            try:
                db.execute(f"ALTER TABLE opportunities ADD COLUMN {column} {ddl}")
            except sqlite3.OperationalError:
                pass  # Another worker already added it.


def _clean(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", html.unescape(value or ""))
    return " ".join(value.split())


def _parse_date(value: str) -> datetime:
    value = (value or "").strip()
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def _reddit_items(client: httpx.Client) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    failures: list[str] = []
    atom = {"a": "http://www.w3.org/2005/Atom"}
    for source, url in REDDIT_FEEDS.items():
        try:
            response = client.get(url)
            if response.status_code == 429:
                time.sleep(5)
                response = client.get(url)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            for entry in root.findall("a:entry", atom):
                link = entry.find("a:link", atom)
                items.append({
                    "source": source,
                    "title": _clean(entry.findtext("a:title", default="", namespaces=atom)),
                    "summary": _clean(entry.findtext("a:content", default="", namespaces=atom)),
                    "url": link.attrib.get("href", "") if link is not None else "",
                    "published_at": entry.findtext("a:updated", default="", namespaces=atom),
                })
        except Exception as exc:
            failures.append(f"{source}: {type(exc).__name__}")
        time.sleep(1.2)
    return items, failures


def _hn_items(client: httpx.Client) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    failures: list[str] = []
    for query in HN_QUERIES:
        url = f"https://hn.algolia.com/api/v1/search_by_date?tags=ask_hn&hitsPerPage=30&query={quote_plus(query)}"
        try:
            response = client.get(url)
            response.raise_for_status()
            for hit in response.json().get("hits", []):
                object_id = str(hit.get("objectID", ""))
                items.append({
                    "source": "Hacker News",
                    "title": _clean(hit.get("title") or hit.get("story_title") or ""),
                    "summary": _clean(hit.get("story_text") or hit.get("comment_text") or ""),
                    "url": f"https://news.ycombinator.com/item?id={object_id}",
                    "published_at": hit.get("created_at", ""),
                })
        except Exception as exc:
            failures.append(f"Hacker News ({query}): {type(exc).__name__}")
    return items, failures


def _classify(text: str) -> tuple[str, tuple[int, int]] | None:
    lowered = text.lower()
    matches = [
        (name, data)
        for name, data in SERVICES.items()
        if any(term in lowered for term in data["terms"])
    ]
    if not matches:
        return None
    name, data = matches[0]
    return name, data["range"]


def _budget(title: str, body: str, fallback: tuple[int, int]) -> tuple[int, int, str, bool]:
    text = title if re.search(r"(?:\$|£|€|usd\s*)\s*[0-9]", title, re.I) else body
    currency = "USD"
    if "£" in text:
        currency = "GBP"
    elif "€" in text:
        currency = "EUR"
    values = []
    pattern = r"(?:\$|£|€|usd\s*)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*([kK]?)"
    for raw, suffix in re.findall(pattern, text, re.I):
        try:
            value = float(raw.replace(",", ""))
            values.append(int(value * 1000 if suffix else value))
        except ValueError:
            continue
    values = [value for value in values if 5 <= value <= 100000]
    if not values:
        return fallback[0], fallback[1], currency, False
    if len(values) == 1:
        value = values[0]
        return value, max(value, int(value * 1.35)), currency, True
    return min(values), max(values), currency, True


def _score(raw: dict[str, Any], cutoff: datetime) -> dict[str, Any] | None:
    title = raw["title"]
    body = raw["summary"]
    combined = f"{title} {body}"
    published = _parse_date(raw["published_at"])
    if (not raw["url"] or published < cutoff or SELLER_TERMS.search(combined)
            or SENSITIVE_OR_LOW_TRUST.search(combined) or NON_SERVICE_JOB.search(combined) or UNPAID.search(combined)):
        return None
    if raw["source"] == "Hacker News" and not BUYER_TERMS.search(title):
        return None
    if not BUYER_TERMS.search(combined) and "[hiring]" not in combined.lower():
        return None
    classified = _classify(combined)
    if not classified:
        return None
    service, fallback = classified
    low, high, currency, explicit = _budget(title, body, fallback)
    score = 35 + (22 if explicit else 0) + (15 if published > datetime.now(timezone.utc) - timedelta(days=1) else 8)
    score += 12 if len(body) > 180 else 5
    score += 10 if raw["source"].startswith("Reddit") and "[hiring]" in title.lower() else 5
    # ALFA is biased toward leads it (via ONE/Vineet) is actually positioned
    # to deliver — AI automation/agent-build work, plus the web/lead-gen work
    # that pairs well with it — so those surface to the top of the brief.
    if service in HIGH_FIT_SERVICES:
        score += 15
    return {
        "source": raw["source"], "title": title[:500], "summary": body[:1800], "url": raw["url"],
        "service": service, "score": min(score, 100), "budget_min": low, "budget_max": high,
        "currency": currency, "published_at": published.isoformat(),
    }


# ---------------------------------------------------------------------------
# Offer packaging — turn a raw lead into something that can actually be sold
# ---------------------------------------------------------------------------


def _fallback_package(item: dict[str, Any]) -> dict[str, Any]:
    """Deterministic offer package used when the local LLM is unreachable."""
    meta = SERVICE_LABELS.get(item["service"], {"label": item["service"].replace("-", " ").title(), "steps": [
        "Confirm scope and acceptance criteria", "Build the deliverable", "Review and revise once", "Deliver and hand over",
    ]})
    one_time = item["budget_max"] if item["budget_max"] else max(item["budget_min"], 150)
    retainer = max(49, round(one_time * 0.2 / 10) * 10)
    return {
        "service_definition": f"{meta['label']} for: {item['title'][:90]}",
        "build_steps": list(meta["steps"]),
        "one_time_price": int(one_time),
        "retainer_price": int(retainer),
        "retainer_pitch": (
            f"After delivery, offer a ${retainer}/month care plan to keep it updated, monitored, and improved — "
            "turns a one-off gig into recurring revenue."
        ),
        "outreach_message": (
            f"Hi — saw your post about \"{item['title'][:80]}\". I build exactly this kind of "
            f"{meta['label'].lower()} work. I can deliver it for ${item['budget_min']:,}-${item['budget_max']:,} "
            "depending on final scope, with a quick turnaround. Happy to share examples or hop on a 10-minute call "
            "to confirm scope — also offer an optional monthly care plan afterward if you want it kept up to date. "
            "Let me know if you'd like to move forward."
        ),
    }


def _ollama_chat(prompt: str, *, num_predict: int = 500, timeout: float = 60) -> str:
    response = httpx.post(
        os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/chat",
        json={
            "model": os.environ.get("ONE_ROUTER_MODEL", "qwen3.5:2b"),
            "stream": False,
            "think": False,
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": 0.4, "num_predict": num_predict},
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json().get("message", {}).get("content", "").strip()


def _extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if fence:
        text = fence.group(1).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _package_opportunity(item: dict[str, Any]) -> dict[str, Any]:
    """Generate a sellable offer for one lead: definition, build plan, pricing,
    a retainer upsell, and a ready-to-send outreach draft.

    Always returns a complete package — falls back to a deterministic
    template on any LLM/network failure so a scheduled scan never crashes.
    """
    fallback = _fallback_package(item)
    prompt = (
        "You are a productized-service consultant helping a solo operator who builds AI automation, "
        "websites, and freelance deliverables turn a single forum post into a sellable offer.\n\n"
        f"Forum post title: {item['title']}\n"
        f"Forum post body: {item['summary'][:900]}\n"
        f"Detected service category: {item['service']}\n"
        f"Estimated one-time budget range: {item['currency']} {item['budget_min']}-{item['budget_max']}\n\n"
        "Reply with ONLY a JSON object (no prose, no markdown fences) with exactly these keys:\n"
        '  "service_definition": one sentence describing the concrete deliverable in plain language\n'
        '  "build_steps": a list of 4-6 short steps to actually build and deliver it\n'
        '  "one_time_price": an integer USD price within or slightly above the budget range\n'
        '  "retainer_price": an integer USD monthly price (roughly 15-25% of one_time_price) for an ongoing '
        "care/maintenance/improvement plan after delivery\n"
        '  "retainer_pitch": one sentence pitching that monthly plan as a natural upsell after delivery\n'
        '  "outreach_message": a ready-to-send, friendly, specific, non-salesy reply (90-150 words) to this exact post, '
        "proposing the one-time price and mentioning the optional monthly plan, ending with a clear next step\n"
    )
    try:
        raw = _ollama_chat(prompt)
        parsed = _extract_json(raw)
        if not parsed:
            return fallback
        package = {
            "service_definition": str(parsed.get("service_definition") or fallback["service_definition"])[:400],
            "build_steps": [str(step)[:200] for step in (parsed.get("build_steps") or fallback["build_steps"])][:8] or fallback["build_steps"],
            "one_time_price": int(parsed.get("one_time_price") or fallback["one_time_price"]),
            "retainer_price": int(parsed.get("retainer_price") or fallback["retainer_price"]),
            "retainer_pitch": str(parsed.get("retainer_pitch") or fallback["retainer_pitch"])[:400],
            "outreach_message": str(parsed.get("outreach_message") or fallback["outreach_message"])[:1500],
        }
        return package
    except Exception:
        return fallback


def _save(opportunities: list[dict[str, Any]]) -> tuple[int, int]:
    now = datetime.now(timezone.utc).isoformat()
    new_count = 0
    with _db() as db:
        db.execute("UPDATE opportunities SET status = 'archived' WHERE status = 'new'")
        for item in opportunities:
            existed = db.execute("SELECT 1 FROM opportunities WHERE url = ?", (item["url"],)).fetchone()
            db.execute(
                """INSERT INTO opportunities
                (url, source, title, summary, service, score, budget_min, budget_max, currency, published_at,
                 discovered_at, service_definition, build_steps, one_time_price, retainer_price, retainer_pitch,
                 outreach_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET source=excluded.source, title=excluded.title, summary=excluded.summary,
                service=excluded.service, score=excluded.score, budget_min=excluded.budget_min,
                budget_max=excluded.budget_max, currency=excluded.currency, published_at=excluded.published_at,
                status='new',
                service_definition=CASE WHEN excluded.service_definition != '' THEN excluded.service_definition ELSE opportunities.service_definition END,
                build_steps=CASE WHEN excluded.build_steps != '' THEN excluded.build_steps ELSE opportunities.build_steps END,
                one_time_price=CASE WHEN excluded.one_time_price != 0 THEN excluded.one_time_price ELSE opportunities.one_time_price END,
                retainer_price=CASE WHEN excluded.retainer_price != 0 THEN excluded.retainer_price ELSE opportunities.retainer_price END,
                retainer_pitch=CASE WHEN excluded.retainer_pitch != '' THEN excluded.retainer_pitch ELSE opportunities.retainer_pitch END,
                outreach_message=CASE WHEN excluded.outreach_message != '' THEN excluded.outreach_message ELSE opportunities.outreach_message END
                """,
                (
                    item["url"], item["source"], item["title"], item["summary"], item["service"], item["score"],
                    item["budget_min"], item["budget_max"], item["currency"], item["published_at"], now,
                    item.get("service_definition", ""), json.dumps(item.get("build_steps", [])),
                    int(item.get("one_time_price", 0)), int(item.get("retainer_price", 0)),
                    item.get("retainer_pitch", ""), item.get("outreach_message", ""),
                ),
            )
            new_count += 0 if existed else 1
        total = db.execute("SELECT COUNT(*) FROM opportunities WHERE status = 'new'").fetchone()[0]
    return new_count, total


def _report(opportunities: list[dict[str, Any]], failures: list[str], new_count: int, total: int, mrr_pipeline: int) -> Path:
    folder = _home() / "alfa"
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    path = folder / f"ALFA-{now.strftime('%Y-%m-%d-%H%M%S')}.md"
    top = sorted(opportunities, key=lambda item: (-item["score"], item["published_at"]))[:12]
    usd_low = sum(item["budget_min"] for item in top if item["currency"] == "USD")
    usd_high = sum(item["budget_max"] for item in top if item["currency"] == "USD")
    lines = [
        "# ALFA Revenue Opportunity Brief", "", f"Generated: {now.isoformat(timespec='seconds')}",
        f"Qualified this scan: {len(opportunities)}", f"New unique leads: {new_count}",
        f"All-time local lead history: {total}", f"Indicative USD pipeline: ${usd_low:,}-${usd_high:,}",
        f"Potential monthly retainer (MRR) pipeline from packaged leads: ${mrr_pipeline:,}/mo", "",
        "> Pipeline value is an estimate, not earned revenue. Every outreach draft below needs your review and",
        "> approval in the ONE dashboard before anything is sent — ALFA never contacts a lead on its own.", "",
    ]
    for index, item in enumerate(top, 1):
        lines.extend([
            f"## {index}. {item['title']}", "", f"- Source: {item['source']}", f"- Service: {item['service']}",
            f"- Fit score: {item['score']}/100", f"- Estimated value: {item['currency']} {item['budget_min']:,}-{item['budget_max']:,}",
            f"- Published: {item['published_at']}", f"- Link: {item['url']}", "", item["summary"][:600], "",
        ])
        if item.get("service_definition"):
            lines.append(f"**Offer:** {item['service_definition']}")
        if item.get("build_steps"):
            lines.append("**Build plan:**")
            lines.extend(f"  {step_index}. {step}" for step_index, step in enumerate(item["build_steps"], 1))
        if item.get("one_time_price"):
            retainer_note = f" + ${item.get('retainer_price', 0)}/mo retainer after delivery" if item.get("retainer_price") else ""
            lines.append(f"**Suggested price:** ${item['one_time_price']:,}{retainer_note}")
        if item.get("outreach_message"):
            lines.extend(["**Draft outreach (needs your approval to send):**", "", f"> {item['outreach_message']}", ""])
        lines.append("")
    if failures:
        lines.extend(["## Source health", "", *[f"- {failure}" for failure in failures]])
    report_text = "\n".join(lines)
    path.write_text(report_text, encoding="utf-8")
    (folder / "latest.json").write_text(json.dumps({"generated_at": now.isoformat(), "opportunities": top}, indent=2), encoding="utf-8")
    try:
        from openjarvis.one_agents.obsidian import obsidian_status

        memory = obsidian_status()
        if memory["connected"]:
            vault_folder = Path(memory["path"]) / "Agents" / "ALFA" / "Opportunity Briefs"
            vault_folder.mkdir(parents=True, exist_ok=True)
            (vault_folder / path.name).write_text(report_text, encoding="utf-8")
    except Exception:
        pass
    return path


def run_alfa_scan() -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=25) as client:
        reddit, reddit_failures = _reddit_items(client)
        hn, hn_failures = _hn_items(client)
    raw = reddit + hn
    deduped = {item["url"]: item for item in raw if item.get("url")}
    qualified = [scored for item in deduped.values() if (scored := _score(item, cutoff))]
    qualified.sort(key=lambda item: (-item["score"], item["published_at"]))

    # Package the top leads into real, sellable offers (service definition,
    # build plan, pricing, retainer upsell, outreach draft). The rest stay as
    # plain leads — packaging every qualified post would be slow for no
    # benefit since only the top ones get surfaced anyway.
    for item in qualified[:PACKAGE_TOP_N]:
        item.update(_package_opportunity(item))

    new_count, total = _save(qualified)
    top = qualified[:12]
    mrr_pipeline = sum(item.get("retainer_price", 0) for item in top if item["currency"] == "USD")
    report = _report(qualified, reddit_failures + hn_failures, new_count, total, mrr_pipeline)
    return {
        "agent": "ALFA", "mode": "revenue-scout", "scanned": len(deduped), "qualified": len(qualified),
        "new_leads": new_count, "history_total": total,
        "estimated_usd_low": sum(x["budget_min"] for x in top if x["currency"] == "USD"),
        "estimated_usd_high": sum(x["budget_max"] for x in top if x["currency"] == "USD"),
        "mrr_pipeline_monthly": mrr_pipeline,
        "report": str(report), "top_opportunities": top,
        "source_failures": reddit_failures + hn_failures,
    }


# ---------------------------------------------------------------------------
# Approval + delivery handoff — the API layer (api_routes.py) calls these
# ---------------------------------------------------------------------------


def _opportunity_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    try:
        data["build_steps"] = json.loads(data.get("build_steps") or "[]")
    except json.JSONDecodeError:
        data["build_steps"] = []
    return data


def list_opportunities(status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """List leads for the dashboard, newest/highest-scoring first."""
    with _db() as db:
        if status:
            rows = db.execute(
                "SELECT * FROM opportunities WHERE approval_status = ? ORDER BY score DESC, discovered_at DESC LIMIT ?",
                (status, max(1, min(limit, 100))),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM opportunities ORDER BY score DESC, discovered_at DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
    return [_opportunity_to_dict(row) for row in rows]


def get_opportunity(url: str) -> dict[str, Any] | None:
    with _db() as db:
        row = db.execute("SELECT * FROM opportunities WHERE url = ?", (url,)).fetchone()
    return _opportunity_to_dict(row) if row else None


def set_approval(url: str, status: str, delivery_job_id: str = "") -> dict[str, Any] | None:
    if status not in {"pending_review", "approved", "dismissed"}:
        raise ValueError(f"Invalid approval status: {status}")
    with _db() as db:
        changed = db.execute(
            "UPDATE opportunities SET approval_status = ?, delivery_job_id = CASE WHEN ? != '' THEN ? ELSE delivery_job_id END WHERE url = ?",
            (status, delivery_job_id, delivery_job_id, url),
        ).rowcount
        if not changed:
            return None
        row = db.execute("SELECT * FROM opportunities WHERE url = ?", (url,)).fetchone()
    return _opportunity_to_dict(row) if row else None


def approve_and_dispatch(url: str) -> dict[str, Any]:
    """Mark a lead approved and hand it to BETA to produce a concrete
    delivery plan/scaffold. ALFA still does not send anything itself — the
    outreach draft remains for the human to copy and send. This only
    triggers ONE's own internal delivery-planning step.
    """
    opportunity = get_opportunity(url)
    if opportunity is None:
        raise ValueError("Opportunity not found")

    from openjarvis.one_agents.runtime import enqueue_job

    build_steps = opportunity.get("build_steps") or []
    steps_text = "; ".join(build_steps) if build_steps else "Define scope, build, test, deliver."
    task = (
        f"Approved client lead — produce a concrete delivery plan and any starter scaffold/checklist needed.\n"
        f"Lead: {opportunity['title']}\n"
        f"Service: {opportunity['service']} — {opportunity.get('service_definition', '')}\n"
        f"Agreed build plan: {steps_text}\n"
        f"Quoted price: ${opportunity.get('one_time_price', 0):,} one-time"
        + (f" + ${opportunity['retainer_price']:,}/mo retainer" if opportunity.get("retainer_price") else "")
        + f"\nSource post: {opportunity['url']}\n"
        "Produce a step-by-step delivery checklist with estimated time per step and what ONE/Vineet needs to "
        "prepare before starting."
    )
    job = enqueue_job("beta", task, mode="execute")
    updated = set_approval(url, "approved", delivery_job_id=job["id"])
    return {"opportunity": updated, "delivery_job": job}


def dismiss_opportunity(url: str) -> dict[str, Any] | None:
    return set_approval(url, "dismissed")

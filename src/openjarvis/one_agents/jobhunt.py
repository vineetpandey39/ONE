"""JOBHUNT: approval-gated job search support for ONE.

This agent does not scrape job boards, auto-apply, or send email. It turns
user-provided job alerts/JDs into ranked opportunities, tailored resume notes,
outreach drafts, and a durable tracker that the family can review each day.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TRACKER_COLUMNS = [
    "opportunity_id",
    "date_found",
    "source",
    "company",
    "role",
    "location",
    "job_url",
    "posted_date",
    "fit_score",
    "status",
    "resume_version",
    "email_status",
    "applied_status",
    "next_action",
    "last_touched",
    "notes",
]

QA_KEYWORDS = {
    "qa",
    "quality",
    "automation",
    "selenium",
    "cypress",
    "playwright",
    "api testing",
    "postman",
    "testng",
    "jira",
    "agile",
    "scrum",
    "lead",
    "manager",
    "manual",
    "regression",
    "uat",
    "sql",
}

PO_KEYWORDS = {
    "product owner",
    "product manager",
    "backlog",
    "roadmap",
    "user story",
    "acceptance criteria",
    "stakeholder",
    "prioritization",
    "scrum",
    "agile",
    "analytics",
    "requirements",
}


def _home() -> Path:
    return Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".openjarvis"))


def _vault_root() -> Path:
    try:
        from openjarvis.one_agents.obsidian import obsidian_status

        memory = obsidian_status()
        if memory.get("connected") and memory.get("path"):
            return Path(memory["path"])
    except Exception:
        pass
    return _home().parent / "ONE Vault"


def _agent_dir() -> Path:
    path = _vault_root() / "Agents" / "JOBHUNT"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _inbox_dir() -> Path:
    path = _agent_dir() / "Inbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _briefs_dir() -> Path:
    path = _agent_dir() / "Opportunity Briefs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resume_dir() -> Path:
    path = _agent_dir() / "Resume Drafts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _tracker_path() -> Path:
    path = _agent_dir() / "job_tracker.csv"
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=TRACKER_COLUMNS).writeheader()
    return path


def _read_tracker() -> list[dict[str, str]]:
    path = _tracker_path()
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_tracker(rows: list[dict[str, str]]) -> None:
    with _tracker_path().open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRACKER_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in TRACKER_COLUMNS})


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:70] or "job"


def _opportunity_id(company: str, role: str, url: str, body: str) -> str:
    stable = "|".join([company.lower(), role.lower(), url.lower(), body[:500].lower()])
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]


def _extract_field(patterns: list[str], text: str, default: str = "") -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return " ".join(match.group(1).strip().split())
    return default


def _source_from_path(path: Path) -> str:
    name = path.name.lower()
    if "naukri" in name:
        return "Naukri"
    if "linkedin" in name or "linked-in" in name:
        return "LinkedIn"
    if "gmail" in name or "alert" in name:
        return "Gmail alert"
    return "Manual JD"


def _parse_jobs_from_text(path: Path, text: str) -> list[dict[str, Any]]:
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*---+\s*\n", text) if chunk.strip()]
    if not chunks:
        chunks = [text.strip()]
    jobs: list[dict[str, Any]] = []
    for chunk in chunks:
        role = _extract_field(
            [
                r"^(?:role|title|job title)\s*[:\-]\s*(.+)$",
                r"^(.+?(?:QA|Quality|Automation|Product Owner|Product Manager).+?)$",
            ],
            chunk,
            "QA / Product Opportunity",
        )
        company = _extract_field([r"^(?:company|employer)\s*[:\-]\s*(.+)$"], chunk, "Unknown company")
        location = _extract_field([r"^(?:location|city)\s*[:\-]\s*(.+)$"], chunk, "Gurgaon / NCR / Remote")
        posted_date = _extract_field([r"^(?:posted|posted date|date)\s*[:\-]\s*(.+)$"], chunk, "")
        url = _extract_field([r"(https?://\S+)"], chunk, "")
        jobs.append(
            {
                "source": _source_from_path(path),
                "company": company,
                "role": role,
                "location": location,
                "posted_date": posted_date,
                "job_url": url,
                "description": chunk,
            }
        )
    return jobs


def _load_inbox_jobs() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for path in sorted(_inbox_dir().glob("*")):
        if path.is_dir() or path.suffix.lower() not in {".txt", ".md", ".json", ".csv"}:
            continue
        if path.name.lower() == "readme.md":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if path.suffix.lower() == ".json":
            data = json.loads(text or "[]")
            items = data if isinstance(data, list) else data.get("jobs", [])
            for item in items:
                if isinstance(item, dict):
                    item.setdefault("source", _source_from_path(path))
                    item.setdefault("description", item.get("jd", "") or item.get("job_description", ""))
                    jobs.append(item)
            continue
        if path.suffix.lower() == ".csv":
            for item in csv.DictReader(text.splitlines()):
                item.setdefault("source", _source_from_path(path))
                item.setdefault("description", item.get("jd", "") or item.get("job_description", ""))
                jobs.append(dict(item))
            continue
        jobs.extend(_parse_jobs_from_text(path, text))
    return jobs


def _score(job: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    text = " ".join(str(job.get(key, "")) for key in ("role", "description", "location")).lower()
    qa_hits = sorted(keyword for keyword in QA_KEYWORDS if keyword in text)
    po_hits = sorted(keyword for keyword in PO_KEYWORDS if keyword in text)
    score = min(100, 35 + len(qa_hits) * 4 + len(po_hits) * 4)
    if "gurgaon" in text or "gurugram" in text or "remote" in text or "ncr" in text:
        score += 8
    if "lead" in text or "manager" in text or "senior" in text:
        score += 7
    return min(score, 100), qa_hits, po_hits


def _tailoring_notes(job: dict[str, Any], qa_hits: list[str], po_hits: list[str]) -> str:
    role = str(job.get("role", "this role"))
    company = str(job.get("company", "the company"))
    skills = ", ".join((qa_hits + po_hits)[:12]) or "QA leadership, Agile delivery, and testing discipline"
    return (
        f"Tailor the resume for {role} at {company} around: {skills}.\n\n"
        "Recommended resume edits:\n"
        "- Keep the resume truthful: only reorder, emphasize, and quantify real experience.\n"
        "- Put QA leadership, automation testing, Agile ceremonies, release quality, and stakeholder handling in the top summary.\n"
        "- Add a compact Product Owner bridge if the JD mentions backlog, requirements, user stories, or acceptance criteria.\n"
        "- Mirror exact JD keywords in skills and project bullets where they match real experience.\n"
        "- Add a one-line maternity/career-break neutral positioning only if needed: available to join and actively upskilling in AI, PO, and automation testing.\n"
    )


def _email_draft(job: dict[str, Any], qa_hits: list[str], po_hits: list[str]) -> str:
    role = str(job.get("role", "the open role"))
    company = str(job.get("company", "your team"))
    skills = ", ".join((qa_hits + po_hits)[:8]) or "QA leadership, automation testing, Agile delivery"
    return (
        f"Subject: Application for {role} - QA Lead / Product Ownership fit\n\n"
        "Dear Hiring Team,\n\n"
        f"I hope you are doing well. I came across the {role} opening at {company} and wanted to share my profile for your consideration.\n\n"
        f"My background aligns with the role through hands-on experience in {skills}. I have led QA activities across planning, execution, defect triage, stakeholder coordination, and release readiness, and I am currently strengthening my AI, Product Owner, and automation testing capabilities to contribute more deeply across quality and product delivery.\n\n"
        "I would be grateful if you could review my resume for this opportunity. I am available for a discussion at your convenience and would be happy to share more details about relevant projects and responsibilities.\n\n"
        "Warm regards,\n"
        "[Candidate Name]\n"
        "[Phone] | [Email] | [LinkedIn]\n"
    )


def _write_brief(job: dict[str, Any], fit_score: int, qa_hits: list[str], po_hits: list[str]) -> Path:
    now = datetime.now().astimezone()
    oid = str(job["opportunity_id"])
    safe = _slug(f"{job.get('company', '')}-{job.get('role', '')}-{oid}")
    brief = _briefs_dir() / f"{now.strftime('%Y-%m-%d')}-{safe}.md"
    resume = _resume_dir() / f"{now.strftime('%Y-%m-%d')}-{safe}-resume-notes.md"
    resume.write_text(_tailoring_notes(job, qa_hits, po_hits), encoding="utf-8")
    lines = [
        "# JOBHUNT Opportunity Brief",
        "",
        f"Generated: {now.isoformat(timespec='seconds')}",
        f"Opportunity ID: {oid}",
        f"Company: {job.get('company', '')}",
        f"Role: {job.get('role', '')}",
        f"Location: {job.get('location', '')}",
        f"Source: {job.get('source', '')}",
        f"Posted date: {job.get('posted_date', '')}",
        f"URL: {job.get('job_url', '')}",
        f"Fit score: {fit_score}/100",
        "",
        "> Review gate: JOBHUNT prepares this package only. It must not apply, send email, or represent the candidate without explicit approval for that specific action.",
        "",
        "## Matched Signals",
        "",
        f"- QA/testing: {', '.join(qa_hits) if qa_hits else 'No strong QA keywords found'}",
        f"- Product owner: {', '.join(po_hits) if po_hits else 'No strong PO keywords found'}",
        "",
        "## Resume Tailoring Notes",
        "",
        _tailoring_notes(job, qa_hits, po_hits),
        "",
        "## Outreach Draft",
        "",
        "```text",
        _email_draft(job, qa_hits, po_hits),
        "```",
        "",
        "## Original JD",
        "",
        str(job.get("description", ""))[:4000],
        "",
    ]
    brief.write_text("\n".join(lines), encoding="utf-8")
    return brief


def _is_recent(posted_date: str) -> bool:
    if not posted_date.strip():
        return True
    normalized = posted_date.strip().lower()
    if any(token in normalized for token in ("today", "just now", "hour", "day")):
        match = re.search(r"(\d+)\s*day", normalized)
        return not match or int(match.group(1)) <= 15
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%b %d, %Y", "%d %b %Y"):
        try:
            value = datetime.strptime(posted_date.strip(), fmt).replace(tzinfo=timezone.utc)
            return value >= datetime.now(timezone.utc) - timedelta(days=15)
        except ValueError:
            continue
    return True


def run_jobhunt_scan() -> dict[str, Any]:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    existing_rows = _read_tracker()
    existing_ids = {row["opportunity_id"] for row in existing_rows if row.get("opportunity_id")}
    new_rows = existing_rows[:]
    briefs: list[str] = []
    skipped_old = 0
    duplicate_count = 0
    loaded = _load_inbox_jobs()
    for job in loaded:
        if not _is_recent(str(job.get("posted_date", ""))):
            skipped_old += 1
            continue
        description = str(job.get("description", "") or job.get("jd", "") or "")
        oid = _opportunity_id(
            str(job.get("company", "")),
            str(job.get("role", job.get("title", ""))),
            str(job.get("job_url", job.get("url", ""))),
            description,
        )
        if oid in existing_ids:
            duplicate_count += 1
            continue
        job["opportunity_id"] = oid
        fit_score, qa_hits, po_hits = _score(job)
        if fit_score < int(os.environ.get("JOBHUNT_MIN_FIT_SCORE", "55")):
            continue
        brief = _write_brief(job, fit_score, qa_hits, po_hits)
        briefs.append(str(brief))
        new_rows.append(
            {
                "opportunity_id": oid,
                "date_found": now,
                "source": str(job.get("source", "")),
                "company": str(job.get("company", "")),
                "role": str(job.get("role", job.get("title", ""))),
                "location": str(job.get("location", "")),
                "job_url": str(job.get("job_url", job.get("url", ""))),
                "posted_date": str(job.get("posted_date", "")),
                "fit_score": str(fit_score),
                "status": "draft_ready",
                "resume_version": Path(brief).name.replace(".md", "-resume-notes.md"),
                "email_status": "draft_ready_review_required",
                "applied_status": "not_applied_review_required",
                "next_action": "Review brief, tailor resume, then manually apply/send after approval.",
                "last_touched": now,
                "notes": "Prepared by JOBHUNT from local inbox alert/JD.",
            }
        )
        existing_ids.add(oid)
    _write_tracker(new_rows)
    latest = {
        "agent": "JOBHUNT",
        "mode": "approval-gated-job-search",
        "loaded": len(loaded),
        "new_briefs": len(briefs),
        "duplicates": duplicate_count,
        "skipped_old": skipped_old,
        "tracker": str(_tracker_path()),
        "briefs": briefs,
        "inbox": str(_inbox_dir()),
    }
    (_agent_dir() / "latest.json").write_text(json.dumps(latest, indent=2), encoding="utf-8")
    return latest

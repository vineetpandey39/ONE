"""Evidence-backed local assets and repeatable measurement, without external sends."""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def audience_assets(payload):
    root = Path(payload.get("run_dir") or "")
    source = root / "book.md"
    if not payload.get("run_dir") or not source.is_file():
        raise ValueError("LEDA needs an existing manuscript; it must not invent a reader resource")
    manuscript = source.read_text(encoding="utf-8")
    title = str(payload["title"])
    headings = [h.strip() for h in re.findall(r"^#{1,3}\s+(.+)$", manuscript, re.M)
                if re.search(r"chapter\s+\d", h, re.I)][:12]
    if not headings:
        raise ValueError("No chapter headings found for the source-backed reader worksheet")
    out = root / "marketing"
    out.mkdir(exist_ok=True)
    worksheet = [f"# {title}: Reader Companion", "", "A worksheet for your own reading notes.", ""]
    for heading in headings:
        worksheet.extend([f"## {heading}", "", "- Key takeaway:", "- Question to revisit:",
                          "- One idea to apply or discuss:", ""])
    path = out / "reader-companion.md"
    path.write_text("\n".join(worksheet), encoding="utf-8")
    draft = out / "reader-email-draft.md"
    draft.write_text(f"Subject: Your reading companion for {title}\n\n"
                     f"Here is a chapter-by-chapter notes worksheet for {title}. "
                     "Use it to capture takeaways and questions as you read.\n\n"
                     "Delivery is held until an approved sender, consented recipient list, "
                     "and working unsubscribe mechanism are configured.\n", encoding="utf-8")
    result = {"title_id": title, "status": "ASSETS_READY_DELIVERY_BLOCKED", "external_send": False,
              "reader_magnet": str(path), "email_draft": str(draft),
              "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "blockers": ["verified sender account", "consented recipients", "unsubscribe mechanism", "campaign approval"],
              "segments": ["new reader", "engaged reader", "series/read-through reader"]}
    _save(out / "audience.json", result)
    return result


def measurement(payload, baseline, *, now=None):
    if not payload.get("run_dir"):
        raise ValueError("METRON needs the title's run_dir to persist its review")
    root = Path(payload["run_dir"]) / "marketing"
    metrics_path = root / "metrics.json"
    evidence = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.is_file() else {}
    # Never recycle the previous cycle's task metrics as newly measured data.
    metrics = evidence.get("metrics", {})
    checked_at = time.time() if now is None else now
    try:
        as_of = datetime.fromisoformat(str(evidence.get("as_of", "")))
        as_of = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
        fresh = 0 <= checked_at - as_of.timestamp() <= 7 * 86400
    except ValueError:
        fresh = False
    if not evidence.get("source") or not fresh:
        metrics = {}
    report = baseline(str(payload["title"]), metrics)
    report.update({"checked_at_epoch": checked_at, "source": evidence.get("source"),
                   "as_of": evidence.get("as_of"), "status": "measured" if not report["missing"] else "awaiting_metrics",
                   "metrics_input_path": str(metrics_path)})
    report["next_review_epoch"] = report["checked_at_epoch"] + 7 * 86400
    _save(root / "measurement.json", report)
    return report

"""Local revenue pipeline for ALFA opportunities.

The pipeline automates preparation and tracking, never impersonation or spam.
External outreach remains human-approved. Revenue is counted only after a
payment reference is recorded by the user or a trusted webhook.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openjarvis.one_agents.alfa import _db, get_opportunity


_COLUMNS = {
    "pipeline_stage": "TEXT NOT NULL DEFAULT 'qualified'",
    "client_name": "TEXT NOT NULL DEFAULT ''",
    "client_contact": "TEXT NOT NULL DEFAULT ''",
    "contact_channel": "TEXT NOT NULL DEFAULT ''",
    "outreach_sent_at": "TEXT NOT NULL DEFAULT ''",
    "response_text": "TEXT NOT NULL DEFAULT ''",
    "response_received_at": "TEXT NOT NULL DEFAULT ''",
    "response_status": "TEXT NOT NULL DEFAULT ''",
    "proposal_path": "TEXT NOT NULL DEFAULT ''",
    "agreement_path": "TEXT NOT NULL DEFAULT ''",
    "invoice_path": "TEXT NOT NULL DEFAULT ''",
    "payment_link": "TEXT NOT NULL DEFAULT ''",
    "payment_status": "TEXT NOT NULL DEFAULT 'unpaid'",
    "amount_paid": "INTEGER NOT NULL DEFAULT 0",
    "payment_reference": "TEXT NOT NULL DEFAULT ''",
    "paid_at": "TEXT NOT NULL DEFAULT ''",
    "delivery_status": "TEXT NOT NULL DEFAULT 'not_started'",
    "delivered_at": "TEXT NOT NULL DEFAULT ''",
    "retainer_status": "TEXT NOT NULL DEFAULT 'proposed'",
    "revenue_updated_at": "TEXT NOT NULL DEFAULT ''",
}

VALID_STAGES = {
    "qualified", "outreach_approved", "contacted", "replied",
    "proposal_ready", "payment_pending", "paid", "delivery_queued",
    "delivering", "delivered", "retainer", "lost",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _home() -> Path:
    return Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".openjarvis"))


def ensure_schema() -> None:
    with _db() as db:
        existing = {row["name"] for row in db.execute("PRAGMA table_info(opportunities)").fetchall()}
        for column, ddl in _COLUMNS.items():
            if column not in existing:
                db.execute(f"ALTER TABLE opportunities ADD COLUMN {column} {ddl}")
        db.execute(
            "UPDATE opportunities SET pipeline_stage = 'outreach_approved' "
            "WHERE approval_status = 'approved' AND pipeline_stage = 'qualified'"
        )


def _decode_steps(value: str | list[str] | None) -> list[str]:
    if isinstance(value, list):
        return value
    try:
        return [str(step) for step in json.loads(value or "[]")]
    except (TypeError, json.JSONDecodeError):
        return []


def _row_dict(row: Any) -> dict[str, Any]:
    result = dict(row)
    result["build_steps"] = _decode_steps(result.get("build_steps"))
    return result


def list_pipeline(stage: str | None = None, limit: int = 50) -> dict[str, Any]:
    ensure_schema()
    with _db() as db:
        if stage:
            rows = db.execute(
                "SELECT * FROM opportunities WHERE pipeline_stage = ? "
                "ORDER BY revenue_updated_at DESC, score DESC LIMIT ?",
                (stage, max(1, min(limit, 200))),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM opportunities ORDER BY "
                "CASE pipeline_stage "
                "WHEN 'paid' THEN 1 WHEN 'delivery_queued' THEN 2 WHEN 'delivering' THEN 3 "
                "WHEN 'replied' THEN 4 WHEN 'proposal_ready' THEN 5 WHEN 'contacted' THEN 6 "
                "WHEN 'outreach_approved' THEN 7 ELSE 8 END, "
                "revenue_updated_at DESC, score DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
    opportunities = [_row_dict(row) for row in rows]
    return {"opportunities": opportunities, "count": len(opportunities), "summary": revenue_summary()}


def revenue_summary() -> dict[str, int]:
    ensure_schema()
    with _db() as db:
        row = db.execute(
            """SELECT
            COALESCE(SUM(CASE WHEN pipeline_stage != 'lost' THEN one_time_price ELSE 0 END), 0) potential_pipeline,
            COALESCE(SUM(CASE WHEN pipeline_stage != 'lost' THEN retainer_price ELSE 0 END), 0) potential_mrr,
            COALESCE(SUM(amount_paid), 0) earned_revenue,
            COALESCE(SUM(CASE WHEN retainer_status = 'active' THEN retainer_price ELSE 0 END), 0) active_mrr,
            COALESCE(SUM(CASE WHEN payment_status = 'paid' THEN 1 ELSE 0 END), 0) paid_deals,
            COALESCE(SUM(CASE WHEN pipeline_stage NOT IN ('lost', 'delivered') THEN 1 ELSE 0 END), 0) open_deals
            FROM opportunities"""
        ).fetchone()
    return {key: int(row[key] or 0) for key in row.keys()}


def _update(url: str, **values: Any) -> dict[str, Any]:
    ensure_schema()
    if not values:
        opportunity = get_opportunity(url)
        if opportunity is None:
            raise ValueError("Opportunity not found")
        return opportunity
    values["revenue_updated_at"] = _now()
    assignments = ", ".join(f"{key} = ?" for key in values)
    with _db() as db:
        changed = db.execute(
            f"UPDATE opportunities SET {assignments} WHERE url = ?",
            (*values.values(), url),
        ).rowcount
        if not changed:
            raise ValueError("Opportunity not found")
        row = db.execute("SELECT * FROM opportunities WHERE url = ?", (url,)).fetchone()
    return _row_dict(row)


def approve_outreach(url: str, payment_link: str = "") -> dict[str, Any]:
    return _update(
        url,
        approval_status="approved",
        pipeline_stage="outreach_approved",
        payment_link=payment_link.strip(),
    )


def record_outreach(url: str, channel: str, client_contact: str = "", client_name: str = "") -> dict[str, Any]:
    opportunity = get_opportunity(url)
    if opportunity is None:
        raise ValueError("Opportunity not found")
    if opportunity.get("approval_status") != "approved":
        raise ValueError("Outreach must be approved before it is marked sent")
    return _update(
        url,
        pipeline_stage="contacted",
        contact_channel=channel.strip()[:80],
        client_contact=client_contact.strip()[:240],
        client_name=client_name.strip()[:160],
        outreach_sent_at=_now(),
    )


def _classify_response(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("not interested", "no thanks", "decline", "filled", "hired someone")):
        return "negative"
    if any(term in lowered for term in ("interested", "let's talk", "lets talk", "call", "proposal", "quote", "move forward", "how soon")):
        return "positive"
    return "follow_up"


def record_response(url: str, text: str) -> dict[str, Any]:
    if not text.strip():
        raise ValueError("Response text is required")
    status = _classify_response(text)
    stage = "lost" if status == "negative" else "replied"
    updated = _update(
        url,
        pipeline_stage=stage,
        response_text=text.strip()[:5000],
        response_received_at=_now(),
        response_status=status,
    )
    if status == "positive":
        updated = prepare_deal(url)
    return updated


def _deal_folder(opportunity: dict[str, Any]) -> Path:
    slug = "".join(character if character.isalnum() else "-" for character in opportunity["service"]).strip("-")
    suffix = str(abs(hash(opportunity["url"])))[:10]
    folder = _home() / "revenue" / f"{slug}-{suffix}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def prepare_deal(url: str) -> dict[str, Any]:
    ensure_schema()
    with _db() as db:
        row = db.execute("SELECT * FROM opportunities WHERE url = ?", (url,)).fetchone()
    if row is None:
        raise ValueError("Opportunity not found")
    opportunity = _row_dict(row)
    folder = _deal_folder(opportunity)
    client = opportunity.get("client_name") or "Prospective Client"
    price = int(opportunity.get("one_time_price") or opportunity.get("budget_max") or 0)
    retainer = int(opportunity.get("retainer_price") or 0)
    payment_link = opportunity.get("payment_link") or os.environ.get("ALFA_PAYMENT_LINK", "")
    steps = opportunity.get("build_steps") or ["Confirm scope", "Build", "Test", "Deliver"]
    proposal = folder / "proposal.md"
    agreement = folder / "service-agreement-draft.md"
    invoice = folder / "invoice.md"
    proposal.write_text(
        "\n".join([
            "# Service Proposal", "", f"Client: {client}", f"Source: {opportunity['url']}", "",
            "## Deliverable", opportunity.get("service_definition") or opportunity["title"], "",
            "## Delivery plan", *[f"{index}. {step}" for index, step in enumerate(steps, 1)], "",
            f"Project fee: USD {price:,}", f"Optional ongoing care: USD {retainer:,}/month", "",
            "Payment link: " + (payment_link or "Add payment link before sending"), "",
            "Status: DRAFT - review scope, dates, and legal terms before sending.",
        ]),
        encoding="utf-8",
    )
    agreement.write_text(
        "\n".join([
            "# Service Agreement - Draft", "", f"Provider: Vineet / ONE", f"Client: {client}", "",
            f"Scope: {opportunity.get('service_definition') or opportunity['title']}",
            f"Fee: USD {price:,}", "Payment terms: Payment before delivery work begins unless otherwise agreed.",
            "Revisions: One reasonable revision round is included.",
            "Ownership: Final deliverables transfer after full payment.",
            "Confidentiality: Both parties will protect non-public project information.",
            "Cancellation: Work completed before cancellation remains payable.", "",
            "Provider signature: ____________________", "Client signature: ____________________", "Date: __________", "",
            "DRAFT: This template is not legal advice. Review before use.",
        ]),
        encoding="utf-8",
    )
    invoice.write_text(
        "\n".join([
            "# Invoice - Draft", "", f"Bill to: {client}", f"Service: {opportunity['service']}",
            f"Amount due: USD {price:,}", "Status: UNPAID", "Reference: Add after payment", "",
            "Payment link: " + (payment_link or "Add payment link before sending"),
        ]),
        encoding="utf-8",
    )
    return _update(
        url,
        pipeline_stage="proposal_ready",
        proposal_path=str(proposal),
        agreement_path=str(agreement),
        invoice_path=str(invoice),
        payment_link=payment_link,
    )


def record_payment(url: str, amount: int, reference: str, payment_link: str = "") -> dict[str, Any]:
    if amount <= 0:
        raise ValueError("Payment amount must be greater than zero")
    if not reference.strip():
        raise ValueError("Payment reference is required")
    opportunity = get_opportunity(url)
    if opportunity is None:
        raise ValueError("Opportunity not found")
    if opportunity.get("payment_status") == "paid" and opportunity.get("payment_reference") == reference.strip():
        return start_delivery(url)
    _update(
        url,
        pipeline_stage="paid",
        payment_status="paid",
        amount_paid=int(amount),
        payment_reference=reference.strip()[:240],
        payment_link=payment_link.strip() or opportunity.get("payment_link", ""),
        paid_at=_now(),
    )
    return start_delivery(url)


def start_delivery(url: str, allow_unpaid: bool = False) -> dict[str, Any]:
    ensure_schema()
    with _db() as db:
        row = db.execute("SELECT * FROM opportunities WHERE url = ?", (url,)).fetchone()
    if row is None:
        raise ValueError("Opportunity not found")
    opportunity = _row_dict(row)
    if opportunity.get("payment_status") != "paid" and not allow_unpaid:
        raise ValueError("Payment must be confirmed before delivery starts")
    if opportunity.get("delivery_job_id") and opportunity.get("delivery_status") in {"queued", "running", "workspace_ready"}:
        from openjarvis.one_agents.runtime import get_job

        existing_job = get_job(opportunity["delivery_job_id"])
        return {"opportunity": opportunity, "delivery_job": existing_job or {"id": opportunity["delivery_job_id"]}}
    from openjarvis.one_agents.runtime import enqueue_job

    steps = "; ".join(opportunity.get("build_steps") or [])
    task = (
        "Create the delivery workspace and execution checklist for this paid client engagement. "
        "Do not claim external delivery. Produce concrete files/checklists that Vineet can review.\n"
        f"Client: {opportunity.get('client_name') or 'Client'}\n"
        f"Service: {opportunity.get('service_definition') or opportunity['title']}\n"
        f"Steps: {steps}\n"
        f"Proposal: {opportunity.get('proposal_path', '')}\n"
        f"Agreement: {opportunity.get('agreement_path', '')}\n"
        f"Source: {url}"
    )
    job = enqueue_job("beta", task, mode="execute")
    updated = _update(
        url,
        pipeline_stage="delivery_queued",
        delivery_status="queued",
        delivery_job_id=job["id"],
    )
    return {"opportunity": updated, "delivery_job": job}


def complete_delivery(url: str, activate_retainer: bool = False) -> dict[str, Any]:
    return _update(
        url,
        pipeline_stage="retainer" if activate_retainer else "delivered",
        delivery_status="completed",
        delivered_at=_now(),
        retainer_status="active" if activate_retainer else "proposed",
    )


def mark_lost(url: str) -> dict[str, Any]:
    return _update(url, approval_status="dismissed", pipeline_stage="lost")


def get_artifact(url: str, kind: str) -> Path:
    column = {"proposal": "proposal_path", "agreement": "agreement_path", "invoice": "invoice_path"}.get(kind)
    if column is None:
        raise ValueError("Artifact must be proposal, agreement, or invoice")
    ensure_schema()
    with _db() as db:
        row = db.execute(f"SELECT {column} FROM opportunities WHERE url = ?", (url,)).fetchone()
    if row is None or not row[column]:
        raise ValueError("Artifact is not ready")
    path = Path(row[column]).resolve()
    allowed = (_home() / "revenue").resolve()
    if allowed not in path.parents or not path.is_file():
        raise ValueError("Artifact path is invalid")
    return path


def mark_delivery_job(job_id: str, status: str) -> None:
    """Synchronize BETA job progress without claiming client delivery."""
    if status not in {"running", "workspace_ready", "failed"}:
        return
    stage = "delivering" if status in {"running", "workspace_ready"} else "delivery_queued"
    ensure_schema()
    with _db() as db:
        db.execute(
            "UPDATE opportunities SET pipeline_stage = ?, delivery_status = ?, revenue_updated_at = ? "
            "WHERE delivery_job_id = ?",
            (stage, status, _now(), job_id),
        )

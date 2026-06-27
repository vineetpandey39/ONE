from __future__ import annotations

from datetime import datetime, timezone

from openjarvis.one_agents import alfa, revenue


def _seed(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    revenue.ensure_schema()
    now = datetime.now(timezone.utc).isoformat()
    with alfa._db() as db:
        db.execute(
            """INSERT INTO opportunities
            (url, source, title, summary, service, score, budget_min, budget_max,
             currency, published_at, discovered_at, status, service_definition,
             build_steps, one_time_price, retainer_price, retainer_pitch,
             outreach_message, approval_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "https://example.test/lead", "test", "Need an automation", "Paid automation work",
                "automation", 95, 500, 1000, "USD", now, now, "new",
                "Build a workflow", '["Map workflow", "Build", "Test", "Deliver"]',
                800, 160, "Monthly care", "Hello, I can help.", "pending_review",
            ),
        )
    return "https://example.test/lead"


def test_pipeline_requires_real_payment_before_beta(monkeypatch, tmp_path):
    url = _seed(monkeypatch, tmp_path)
    queued = []
    monkeypatch.setattr(
        "openjarvis.one_agents.runtime.enqueue_job",
        lambda agent_id, task, mode: queued.append((agent_id, mode)) or {"id": "beta-test", "agent_id": agent_id},
    )

    assert revenue.approve_outreach(url)["pipeline_stage"] == "outreach_approved"
    assert revenue.record_outreach(url, "Reddit DM", "client-user", "Client")["pipeline_stage"] == "contacted"
    replied = revenue.record_response(url, "Interested. Please send a proposal and let's move forward.")
    assert replied["pipeline_stage"] == "proposal_ready"
    assert replied["proposal_path"]
    assert queued == []

    paid = revenue.record_payment(url, 800, "txn-123")
    assert paid["opportunity"]["pipeline_stage"] == "delivery_queued"
    assert queued == [("beta", "execute")]
    summary = revenue.revenue_summary()
    assert summary["earned_revenue"] == 800
    assert summary["paid_deals"] == 1


def test_negative_response_is_not_revenue(monkeypatch, tmp_path):
    url = _seed(monkeypatch, tmp_path)
    revenue.approve_outreach(url)
    revenue.record_outreach(url, "email")
    lost = revenue.record_response(url, "No thanks, we hired someone else.")
    assert lost["pipeline_stage"] == "lost"
    assert revenue.revenue_summary()["earned_revenue"] == 0

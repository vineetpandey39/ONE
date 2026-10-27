"""Coordination with the explicitly configured local control.py repair queue.

No configuration preserves standalone installations. A configured but unavailable
store fails closed. This lock serializes control.py claim/renew/record with the
short dispatch section; it never grants production or provider permission.
"""
from contextlib import closing, contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import time
from datetime import datetime, timezone


class RepairDeferred(RuntimeError):
    pass


def home():
    return Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".openjarvis"))


def mission(row):
    try:
        task = json.loads(row.get("task") or "{}")
        commission = task.get("commission") or {}
        mission_id = task.get("mission_id") or commission.get("mission_id")
        brand = task.get("brand") or commission.get("brand")
        if mission_id and brand:
            return (str(brand), str(mission_id))
    except (ValueError, TypeError, AttributeError):
        pass
    # Exact task fallback covers legacy workers, without treating every job of
    # an agent as one mission. Empty tasks are scoped to the physical job.
    return (str(row.get("agent_id") or ""), str(row.get("task") or row.get("id")))


@contextmanager
def external_repair_guard(connect, previous, *, owner=None):
    config = home() / "helios_external_repair.json"
    override = os.environ.get("ONE_HELIOS_EXTERNAL_REPAIR_DB")
    db = None
    try:
        if not override and not config.exists():
            if owner is not None:
                raise RepairDeferred("external repair owner cannot be validated")
            reason = newer_attempt(connect, previous)
            if reason:
                raise RepairDeferred(reason)
            yield
            return
        try:
            path = Path(override or json.loads(config.read_text(encoding="utf-8"))["operator_db"])
            if not path.is_absolute():
                raise ValueError("absolute operator database required")
            db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=2)
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            reason = terminal_receipt(db, connect, previous)
            if reason:
                raise RepairDeferred(reason)
            leases = db.execute("SELECT key,token,lease_until FROM queue "
                                "WHERE status='claimed' AND lease_until>?", (time.time(),)).fetchall()
            owner_valid = False
            for lease in leases:
                if not lease["key"].startswith("runtime:"):
                    raise RepairDeferred("external repair scope cannot be resolved")
                with closing(connect()) as runtime_db:
                    row = runtime_db.execute("SELECT * FROM jobs WHERE id=?", (lease["key"][8:],)).fetchone()
                if row is None:
                    raise RepairDeferred("external repair scope cannot be resolved")
                same = mission(dict(row)) == mission(previous)
                authenticated = (isinstance(owner, tuple) and len(owner) == 2
                                 and owner[0] == lease["key"] and isinstance(owner[1], str)
                                 and hmac.compare_digest(owner[1], str(lease["token"] or "")))
                if authenticated and same:
                    owner_valid = True
                elif same:
                    raise RepairDeferred("mission has an active external repair owner")
            if owner is not None and not owner_valid:
                raise RepairDeferred("external repair ownership is invalid, expired, or for another mission")
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            raise RepairDeferred("configured external repair store unavailable or invalid") from exc
        reason = newer_attempt(connect, previous)
        if reason:
            raise RepairDeferred(reason)
        yield
    finally:
        if db is not None:
            db.rollback()
            db.close()


def attempt_key(previous, revision):
    # Traceback line numbers are not changed diagnoses.
    error = str(previous.get("error") or "").split("\n\nTraceback", 1)[0]
    raw = json.dumps([mission(previous), previous.get("agent_id"), error, revision], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


@contextmanager
def repair_dispatch(previous, revision):
    """Persist intent before dispatch; uncertainty requires reconciliation, not replay."""
    if not revision:
        yield
        return
    db = None
    try:
        try:
            home().mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(home() / "helios_repair_dispatch.db", timeout=2)
            db.execute("CREATE TABLE IF NOT EXISTS attempts (key TEXT PRIMARY KEY, job TEXT, revision TEXT)")
            db.execute("INSERT INTO attempts VALUES (?,?,?)",
                       (attempt_key(previous, revision), previous["id"], revision))
            db.commit()
        except sqlite3.IntegrityError as exc:
            raise RepairDeferred("repair already dispatched for this mission and failure; changed diagnosis or verified repair required") from exc
        except (OSError, sqlite3.Error) as exc:
            raise RepairDeferred("repair dispatch evidence unavailable") from exc
        yield
    finally:
        if db is not None:
            db.close()


def already_dispatched(previous, revision):
    path = home() / "helios_repair_dispatch.db"
    if not path.exists():
        return False
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            return db.execute("SELECT 1 FROM attempts WHERE key=?",
                              (attempt_key(previous, revision),)).fetchone() is not None
    except sqlite3.Error:
        # Unreadable evidence cannot authorize a repeated execution.
        return True


def _stamp(value):
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return moment.replace(tzinfo=moment.tzinfo or timezone.utc).timestamp()
    except (ValueError, TypeError):
        return None


def newer_attempt(connect, previous):
    """Later work is a reconciliation dependency, never proof of business success."""
    created = _stamp(previous.get("created_at"))
    if created is None:
        return ""
    # A reused physical row can fail again after a later-created attempt.
    # Its latest failure must not be hidden by that older outcome.
    cutoff = max(created, _stamp(previous.get("updated_at")) or created)
    with closing(connect()) as db:
        rows = db.execute("SELECT * FROM jobs WHERE agent_id=? AND id!=? "
                          "AND created_at>? AND mode!='watch' ORDER BY created_at DESC",
                          (previous.get("agent_id"), previous.get("id"), previous.get("created_at"))).fetchall()
    for raw in rows:
        row = dict(raw)
        later = _stamp(row.get("created_at"))
        if later is None or later <= cutoff:
            continue
        if mission(row) != mission(previous):
            continue
        # Same mission can have independent actions (upload vs comments).
        try:
            old_task = json.loads(previous.get("task") or "{}")
            new_task = json.loads(row.get("task") or "{}")
            if old_task.get("stage") != new_task.get("stage"):
                continue
        except (ValueError, TypeError, AttributeError):
            if row.get("task") != previous.get("task"):
                continue
        return f"newer same-work attempt {row['id']} requires reconciliation; historical failure retained"
    return ""


def _checked_evidence(receipt):
    """Recheck operator-recorded hashes; never infer acceptance from filenames."""
    checked = {}
    entries = json.loads(receipt["evidence"])
    if not isinstance(entries, list) or not entries:
        return checked
    for entry in entries:
        path = Path(entry["path"])
        if not path.is_absolute() or path.stat().st_size > 25_000_000:
            return {}
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            return {}
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            continue
        if isinstance(value, dict):
            checked[entry["sha256"]] = value
    return checked


def _private_delivery(checked, scope, failed_at):
    for checkpoint in checked.values():
        accepted = checkpoint.get("accepted") or {}
        if not isinstance(accepted, dict):
            continue
        terminal_at = _stamp(checkpoint.get("at"))
        if (checkpoint.get("status") != "resolved" or checkpoint.get("mission_id") != scope[1]
                or terminal_at is None or failed_at > terminal_at
                or checkpoint.get("privacy") != "private" or checkpoint.get("processing") != "succeeded"
                or not checkpoint.get("master_sha256") or checkpoint.get("remaining_blockers") != []):
            continue
        master = str(checkpoint.get("master_sha256") or "")
        bound = any(isinstance(item.get(master), dict)
                    and item[master].get("video_id") == checkpoint.get("video_id")
                    and item[master].get("privacy") == "private" for item in checked.values())
        if len(master) != 64 or any(c not in "0123456789abcdef" for c in master) or not bound:
            continue
        review = checked.get(accepted.get("independent_review_sha256"), {})
        video = review.get("video") or {}
        if (accepted.get("video_id") == checkpoint.get("video_id") == video.get("id")
                and bool(video.get("id")) and accepted.get("privacy") == "private"
                and accepted.get("processing") == "succeeded"
                and accepted.get("package_sha256") == checkpoint.get("package_sha256") == review.get("package_sha256")
                and bool(review.get("package_sha256"))
                and accepted.get("caption_matches") is True
                and review.get("caption_matches") is True and review.get("metadata_matches") is True
                and review.get("pixel_review_accepted") is True
                and video.get("status", {}).get("privacyStatus") == "private"
                and video.get("processingDetails", {}).get("processingStatus") == "succeeded"):
            return str(video["id"])
    return ""


def terminal_receipt(db, connect, previous):
    """Only operator scope plus verified artifacts can defer historical attempts.

    No runtime/company completed row is interpreted as delivery. Exact scoped
    supersession also covers policy no-ops, without calling those publication.
    """
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='receipts'").fetchone():
        return ""  # Older standalone queue schema has no terminal evidence.
    failed_at = _stamp(previous.get("updated_at"))
    if failed_at is None:
        return ""
    receipts = db.execute("SELECT * FROM receipts WHERE id IN "
                          "(SELECT MAX(id) FROM receipts GROUP BY key) ORDER BY id DESC").fetchall()
    for receipt in receipts:
        key = str(receipt["key"])
        exact = key == "runtime:" + str(previous.get("id"))
        if float(receipt["at"]) < failed_at:
            continue  # A genuinely newer failure is never covered by old evidence.
        status = receipt["status"]
        if status == "verification_pending" and exact:
            return f"operator receipt {receipt['id']} awaits verification; no replay"
        if status not in {"resolved", "superseded"}:
            continue
        if not exact:
            if status != "resolved" or not key.startswith("runtime:"):
                continue
            with closing(connect()) as runtime_db:
                anchor = runtime_db.execute("SELECT * FROM jobs WHERE id=?", (key[8:],)).fetchone()
            if anchor is None or mission(dict(anchor)) != mission(previous):
                continue
            # Delivery reconciliation is limited to production/private-upload,
            # never later comments, publication, or other mission actions.
            try:
                task = json.loads(previous.get("task") or "{}")
            except (TypeError, ValueError):
                continue
            if not (previous.get("agent_id") == "planexium" or
                    (previous.get("agent_id") == "echo" and task.get("stage") == "private_upload")):
                continue
        try:
            checked = _checked_evidence(receipt)
        except (OSError, ValueError, KeyError, TypeError):
            checked = {}
        if not checked:
            return f"operator terminal receipt {receipt['id']} needs evidence revalidation; no replay"
        if exact:
            return f"operator receipt {receipt['id']} records {status}; historical failure retained, no replay"
        try:
            video = _private_delivery(checked, mission(previous), failed_at)
        except (TypeError, AttributeError, KeyError):
            return f"operator terminal receipt {receipt['id']} needs semantic revalidation; no replay"
        if video:
            return f"verified private delivery {video} in operator receipt {receipt['id']}; historical failure retained, no replay"
    return ""

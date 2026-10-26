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
            yield
            return
        try:
            path = Path(override or json.loads(config.read_text(encoding="utf-8"))["operator_db"])
            if not path.is_absolute():
                raise ValueError("absolute operator database required")
            db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=2)
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
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

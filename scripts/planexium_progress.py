"""Read-only live mission progress; closing this display never stops production."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import time


def read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def snapshot(root, queue):
    health = read(root / "production-health.json")
    progress_path = root / "edit/render-progress.json"
    progress = read(progress_path)
    plan = read(root / "cinematic-plan.json")
    plan = read(root / "edit/cinematic-coverage-plan.json").get("plan", plan)
    assets = root / "cinematic-assets/planexium" / str(plan.get("revision", "motion-rich-v3"))
    receipts = sorted((assets / "receipts").glob("envato-v*.json"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    current = receipts[0] if receipts else None
    provider = read(current) if current else {}
    last_failure = "none"
    for receipt in receipts:
        failed = read(receipt)
        if failed.get("terminal_status") != "Failed":
            continue
        error = str(failed.get("provider_error", "")).casefold()
        reason = ("subject/context evidence rejected" if "rejected asset" in error else
                  "selected description unavailable" if "idp-description" in error else
                  "browser screenshot timed out" if "screenshot" in error else
                  "browser startup probe timed out" if "get-ciminstance" in error else
                  "native download timed out" if "chrome did not finish" in error else
                  "provider failed; authoritative receipt retained")
        last_failure = f"{receipt.name}: {reason}"
        break
    partials = list(assets.rglob("*.crdownload"))
    status = health.get("status", "unknown")
    if queue.is_file() and health.get("agent_job_id"):
        with sqlite3.connect(queue.as_uri() + "?mode=ro", uri=True) as db:
            row = db.execute("SELECT status FROM jobs WHERE id=?", (health["agent_job_id"],)).fetchone()
            if row:
                status = row[0]
    last = max([p.stat().st_mtime for p in [progress_path, current, *partials]
                if p and p.exists()], default=root.stat().st_mtime)
    return {
        "mission": root.name, "job": health.get("agent_job_id"), "queue_status": status,
        "actual_stage": progress.get("status") if status == "running" else health.get("current_stage"),
        "detail": progress.get("detail", ""),
        "accepted_assets": len(list((assets / "acquired").glob("stock-*.json"))),
        "planned_assets": len(plan.get("stock_requests", [])),
        "candidate": current.name if current else "none",
        "provider_job": provider.get("job_id", "none"),
        "provider_status": provider.get("terminal_status", "in flight / see detail"),
        "last_retry_reason": last_failure,
        "download_mib": round(sum(p.stat().st_size for p in partials) / 1048576, 1),
        "last_progress": datetime.fromtimestamp(last).astimezone().isoformat(timespec="seconds"),
        "progress_age_seconds": int(time.time() - last),
        "master_exists": (root / "edit/master.mp4").is_file(),
        "qc_receipt_exists": (root / "edit/qc-report.json").is_file(),
        "upload_receipt_exists": (root / "upload-ledger.json").is_file(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mission", type=Path)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    if os.name == "nt" and args.watch:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW("PLANEXIUM - Live production progress (display only)")
    while True:
        try:
            data = snapshot(args.mission.resolve(), args.queue.resolve())
            if args.watch:
                os.system("cls" if os.name == "nt" else "clear")
                print("PLANEXIUM LIVE PROGRESS | PRIVATE DELIVERY ONLY")
                print("Closing this display does not stop the production worker.\n")
            for key, value in data.items():
                print(f"{key.replace('_', ' ').title():24} {value}")
            print("\nReceipt presence alone is NOT verified upload completion.", flush=True)
        except (OSError, sqlite3.Error) as exc:
            print(f"Progress read temporarily unavailable: {type(exc).__name__}", flush=True)
        if not args.watch:
            break
        time.sleep(10)


if __name__ == "__main__":
    main()

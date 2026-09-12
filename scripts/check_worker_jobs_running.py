"""Exit 1 if any job is currently 'running' in the given agent_queue.db, else 0.

Used by start-one.ps1's runtime.py mtime-restart check: that check used to
Stop-Process -Force the worker unconditionally whenever runtime.py looked
newer than the running process, with no regard for a job in flight. Once
ONE-AutoRestart made start-one.ps1 fire every 5 minutes on its own, that hard
kill could land mid-job. This lets the caller defer the restart by one cycle
instead.
"""
import sqlite3
import sys

db_path = sys.argv[1]
con = sqlite3.connect(db_path)
count = con.execute("SELECT COUNT(*) FROM jobs WHERE status='running'").fetchone()[0]
sys.exit(1 if count > 0 else 0)

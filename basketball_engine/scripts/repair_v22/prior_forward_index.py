"""Persistent read index for immutable forward decision ledgers.

The ledger remains the source of truth and stays append-only.  This module
removes the former per-run reread of every decision/input JSON pair.  Existing
history is seeded from the frozen daily views, which already contain the
preserved first-write decision, and each later completed run directory is
ingested exactly once from its immutable files.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _triggered(decision: dict) -> bool:
    if decision.get("triggered") is True:
        return True
    return any(
        isinstance(item, dict) and item.get("triggered") is True
        for item in (decision.get("market_decisions") or {}).values()
    )


def _connect(root: Path) -> sqlite3.Connection:
    path = root / "cache" / "repair_v22" / "prior_forward_index.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS index_meta(
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS indexed_run(
          run_id TEXT PRIMARY KEY,
          indexed_at TEXT NOT NULL,
          decision_files INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS prior_forward_record(
          prediction_id TEXT PRIMARY KEY,
          event_id TEXT,
          asof TEXT,
          decision_path TEXT NOT NULL,
          decision_json TEXT NOT NULL,
          event_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_prior_forward_event_asof
          ON prior_forward_record(event_id,asof,prediction_id);
        CREATE INDEX IF NOT EXISTS ix_prior_forward_asof
          ON prior_forward_record(asof,prediction_id);
        """
    )
    return db


def _insert_record(db: sqlite3.Connection, decision: dict, event: dict, path: str) -> bool:
    prediction_id = str(decision.get("prediction_id") or "").strip()
    if not prediction_id or decision.get("archive_type") != "FORWARD_NATIVE" or not _triggered(decision):
        return False
    db.execute(
        "INSERT OR IGNORE INTO prior_forward_record VALUES(?,?,?,?,?,?)",
        (
            prediction_id,
            str(decision.get("event_id") or event.get("event_id") or ""),
            str(decision.get("asof") or ""),
            path,
            json.dumps(decision, ensure_ascii=False, separators=(",", ":")),
            json.dumps(event, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    return True


def _bootstrap_from_frozen_daily_views(db: sqlite3.Connection, root: Path, current_run_id: str) -> None:
    if db.execute("SELECT 1 FROM index_meta WHERE key='dashboard_bootstrap_v1'").fetchone():
        return
    inserted = 0
    files = 0
    for path in sorted((root / "dashboard_v2" / "data").glob("20??-??-??.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        files += 1
        for row in document.get("events") or []:
            if not isinstance(row, dict):
                continue
            decision = row.get("execution") or row.get("decision") or {}
            event = row.get("event") or {}
            inserted += int(_insert_record(db, decision, event, f"frozen_daily:{path}"))

    # Frozen daily views are the operational projection of all older immutable
    # first writes.  Mark existing completed directories as seeded so later
    # runs only open newly appended ledger files.  The current directory is
    # deliberately excluded because it is still being written.
    indexed_at = datetime.now(timezone.utc).isoformat()
    ledger_root = root / "ledger" / "repair_v22"
    for run_dir in ledger_root.iterdir() if ledger_root.exists() else ():
        if run_dir.is_dir() and run_dir.name != current_run_id:
            db.execute(
                "INSERT OR IGNORE INTO indexed_run VALUES(?,?,?)",
                (run_dir.name, indexed_at, -1),
            )
    db.execute(
        "INSERT OR REPLACE INTO index_meta VALUES('dashboard_bootstrap_v1',?)",
        (json.dumps({"files": files, "records": inserted, "at": indexed_at}),),
    )
    db.commit()


def _index_new_ledger_runs(db: sqlite3.Connection, root: Path, current_run_id: str) -> None:
    indexed = {row[0] for row in db.execute("SELECT run_id FROM indexed_run")}
    ledger_root = root / "ledger" / "repair_v22"
    if not ledger_root.exists():
        return
    for run_dir in sorted(ledger_root.iterdir(), key=lambda item: item.name):
        if not run_dir.is_dir() or run_dir.name == current_run_id or run_dir.name in indexed:
            continue
        decision_files = 0
        for decision_path in run_dir.glob("decision_*.json"):
            decision_files += 1
            try:
                decision = json.loads(decision_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            prediction_id = str(decision.get("prediction_id") or "")
            input_path = decision_path.with_name(f"input_{prediction_id}.json")
            try:
                event = (json.loads(input_path.read_text(encoding="utf-8")) or {}).get("event") or {}
            except (OSError, ValueError, TypeError):
                event = {}
            _insert_record(db, decision, event, str(decision_path))
        db.execute(
            "INSERT OR REPLACE INTO indexed_run VALUES(?,?,?)",
            (run_dir.name, datetime.now(timezone.utc).isoformat(), decision_files),
        )
        db.commit()


def load_prior_forward_records(root: Path, current_run_id: str) -> tuple[list[dict], dict]:
    """Return triggered immutable records without rereading old small files."""
    root = Path(root)
    with _connect(root) as db:
        _bootstrap_from_frozen_daily_views(db, root, current_run_id)
        _index_new_ledger_runs(db, root, current_run_id)
        rows = db.execute(
            "SELECT decision_path,decision_json,event_json FROM prior_forward_record "
            "ORDER BY asof,prediction_id"
        ).fetchall()
        bootstrap = db.execute(
            "SELECT value FROM index_meta WHERE key='dashboard_bootstrap_v1'"
        ).fetchone()
        run_count = db.execute("SELECT COUNT(*) FROM indexed_run").fetchone()[0]
    records = [
        {"path": path, "decision": json.loads(decision), "event": json.loads(event)}
        for path, decision, event in rows
    ]
    audit = {
        "storage": str(root / "cache" / "repair_v22" / "prior_forward_index.sqlite"),
        "records": len(records),
        "indexed_runs": run_count,
        "bootstrap": json.loads(bootstrap[0]) if bootstrap else None,
        "current_run_excluded": current_run_id,
    }
    return records, audit

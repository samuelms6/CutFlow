from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from .config import DB_PATH


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                source_url TEXT,
                original_name TEXT,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                stage TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                clips_json TEXT NOT NULL DEFAULT '[]',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(job_id: str, source_type: str, source_url: str | None = None, original_name: str | None = None) -> dict[str, Any]:
    ts = now_iso()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO jobs (id, source_type, source_url, original_name, status, progress, stage, message, created_at, updated_at) VALUES (?, ?, ?, ?, 'queued', 0, 'queued', 'Na fila para processamento', ?, ?)",
            (job_id, source_type, source_url, original_name, ts, ts),
        )
    return get_job(job_id) or {}


def update_job(job_id: str, **fields: Any) -> None:
    allowed = {"status", "progress", "stage", "message", "metadata_json", "clips_json", "error"}
    payload: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key in {"metadata_json", "clips_json"} and not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        payload[key] = value
    if not payload:
        return
    payload["updated_at"] = now_iso()
    assignments = ", ".join(f"{k} = ?" for k in payload)
    values = list(payload.values()) + [job_id]
    with _conn() as conn:
        conn.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", values)


def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    item = dict(row)
    for key in ("metadata_json", "clips_json"):
        try:
            item[key.removesuffix("_json")] = json.loads(item.pop(key))
        except Exception:
            item[key.removesuffix("_json")] = {} if key.startswith("metadata") else []
    return item


def get_job(job_id: str) -> dict[str, Any] | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _decode(row)


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_decode(row) for row in rows if row is not None]


def delete_job(job_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

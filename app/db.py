from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone
from numbers import Integral, Real
from typing import Any
from .config import DB_PATH


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def json_safe(value: Any) -> Any:
    """Converte recursivamente valores para JSON estrito.

    FastAPI/Starlette rejeita NaN e Infinity. Como análises numéricas podem
    produzir esses valores em entradas incomuns, normalizamos para null antes
    de persistir e novamente ao ler registros antigos.
    """
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]

    item_method = getattr(value, "item", None)
    if callable(item_method):
        try:
            return json_safe(item_method())
        except Exception:
            pass
    return value


def _strict_json(value: Any) -> str:
    return json.dumps(json_safe(value), ensure_ascii=False, allow_nan=False)


def _repair_nonfinite_rows(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id, metadata_json, clips_json FROM jobs").fetchall()
    for row in rows:
        replacements: dict[str, str] = {}
        for field in ("metadata_json", "clips_json"):
            raw = row[field]
            try:
                parsed = json.loads(raw)
                normalized = _strict_json(parsed)
                if normalized != raw:
                    replacements[field] = normalized
            except Exception:
                replacements[field] = "{}" if field == "metadata_json" else "[]"
        if replacements:
            assignments = ", ".join(f"{key} = ?" for key in replacements)
            values = list(replacements.values()) + [now_iso(), row["id"]]
            conn.execute(
                f"UPDATE jobs SET {assignments}, updated_at = ? WHERE id = ?",
                values,
            )


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
        _repair_nonfinite_rows(conn)


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
        if key in {"metadata_json", "clips_json"}:
            if isinstance(value, str):
                try:
                    value = _strict_json(json.loads(value))
                except Exception:
                    value = "{}" if key == "metadata_json" else "[]"
            else:
                value = _strict_json(value)
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
            decoded = json.loads(item.pop(key))
            item[key.removesuffix("_json")] = json_safe(decoded)
        except Exception:
            item[key.removesuffix("_json")] = {} if key.startswith("metadata") else []
    return json_safe(item)


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

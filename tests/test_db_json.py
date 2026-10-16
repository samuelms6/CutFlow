import json
import math
import sqlite3

import app.db as db


def test_json_safe_replaces_nested_nonfinite_values():
    value = {
        "nan": float("nan"),
        "pos": float("inf"),
        "neg": float("-inf"),
        "nested": [1.0, {"bad": float("nan")}],
    }
    clean = db.json_safe(value)
    assert clean["nan"] is None
    assert clean["pos"] is None
    assert clean["neg"] is None
    assert clean["nested"][1]["bad"] is None
    json.dumps(clean, allow_nan=False)


def test_init_db_repairs_existing_nonfinite_json(tmp_path, monkeypatch):
    path = tmp_path / "cutflow.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO jobs
            (id, source_type, status, progress, stage, message, metadata_json, clips_json, created_at, updated_at)
            VALUES ('broken', 'upload', 'processing', 43, 'audiovisual', 'teste',
                    '{"value": NaN, "nested": {"x": Infinity}}',
                    '[{"score": NaN}]',
                    '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """
        )
    db.init_db()
    item = db.get_job("broken")
    assert item is not None
    assert item["metadata"]["value"] is None
    assert item["metadata"]["nested"]["x"] is None
    assert item["clips"][0]["score"] is None
    json.dumps(item, allow_nan=False)

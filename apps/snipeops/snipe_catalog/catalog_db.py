from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from config.settings import SNIPE_CATALOG_DB_PATH

DB_PATH = SNIPE_CATALOG_DB_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(SNIPE_CATALOG_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS catalog_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS catalog_models (
            id INTEGER PRIMARY KEY,
            name TEXT,
            manufacturer_name TEXT,
            model_number TEXT,
            raw_json TEXT,
            updated_at TEXT
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS catalog_locations (
            id INTEGER PRIMARY KEY,
            name TEXT,
            raw_json TEXT,
            updated_at TEXT
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS catalog_statuslabels (
            id INTEGER PRIMARY KEY,
            name TEXT,
            raw_json TEXT,
            updated_at TEXT
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS catalog_suppliers (
            id INTEGER PRIMARY KEY,
            name TEXT,
            raw_json TEXT,
            updated_at TEXT
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS catalog_depreciations (
            id INTEGER PRIMARY KEY,
            name TEXT,
            raw_json TEXT,
            updated_at TEXT
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS catalog_categories (
            id INTEGER PRIMARY KEY,
            name TEXT,
            raw_json TEXT,
            updated_at TEXT
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS catalog_manufacturers (
            id INTEGER PRIMARY KEY,
            name TEXT,
            raw_json TEXT,
            updated_at TEXT
        )
        """)
        conn.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def set_meta(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO catalog_meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()


def get_meta(key: str, default: str = "") -> str:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM catalog_meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def upsert_models(rows: list[dict]) -> int:
    now = _now_iso()
    ids = [int(r["id"]) for r in rows if r.get("id") is not None]

    with _connect() as conn:
        for r in rows:
            mid = r.get("id")
            if mid is None:
                continue
            name = r.get("name")
            manufacturer_name = (r.get("manufacturer") or {}).get("name") if isinstance(r.get("manufacturer"), dict) else None
            model_number = r.get("model_number")
            conn.execute(
                """
                INSERT INTO catalog_models(id,name,manufacturer_name,model_number,raw_json,updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    manufacturer_name=excluded.manufacturer_name,
                    model_number=excluded.model_number,
                    raw_json=excluded.raw_json,
                    updated_at=excluded.updated_at
                """,
                (int(mid), name, manufacturer_name, model_number, json.dumps(r), now),
            )

        # delete anything no longer in Snipe
        if ids:
            qmarks = ",".join(["?"] * len(ids))
            conn.execute(f"DELETE FROM catalog_models WHERE id NOT IN ({qmarks})", ids)
        else:
            conn.execute("DELETE FROM catalog_models")

        conn.commit()
    return len(ids)


def _upsert_simple(table: str, rows: list[dict]) -> int:
    now = _now_iso()
    ids = [int(r["id"]) for r in rows if r.get("id") is not None]

    with _connect() as conn:
        for r in rows:
            rid = r.get("id")
            if rid is None:
                continue
            name = r.get("name")
            conn.execute(
                f"""
                INSERT INTO {table}(id,name,raw_json,updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    raw_json=excluded.raw_json,
                    updated_at=excluded.updated_at
                """,
                (int(rid), name, json.dumps(r), now),
            )

        if ids:
            qmarks = ",".join(["?"] * len(ids))
            conn.execute(f"DELETE FROM {table} WHERE id NOT IN ({qmarks})", ids)
        else:
            conn.execute(f"DELETE FROM {table}")

        conn.commit()
    return len(ids)


def upsert_locations(rows: list[dict]) -> int:
    return _upsert_simple("catalog_locations", rows)


def upsert_statuslabels(rows: list[dict]) -> int:
    return _upsert_simple("catalog_statuslabels", rows)


def upsert_suppliers(rows: list[dict]) -> int:
    return _upsert_simple("catalog_suppliers", rows)


def upsert_depreciations(rows: list[dict]) -> int:
    return _upsert_simple("catalog_depreciations", rows)


def list_table(table: str, limit: int = 5000) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY name LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    
def upsert_categories(rows: list[dict]) -> int:
    return _upsert_simple("catalog_categories", rows)


def upsert_manufacturers(rows: list[dict]) -> int:
    return _upsert_simple("catalog_manufacturers", rows)
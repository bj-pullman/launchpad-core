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

        conn.execute("""
        CREATE TABLE IF NOT EXISTS catalog_assets (
            id INTEGER PRIMARY KEY,
            asset_tag TEXT,
            serial TEXT,
            name TEXT,
            model_name TEXT,
            category_name TEXT,
            status_name TEXT,
            location_name TEXT,
            assigned_type TEXT,
            assigned_id INTEGER,
            assigned_name TEXT,
            raw_json TEXT,
            updated_at TEXT
        )
        """)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_assets_asset_tag ON catalog_assets(asset_tag)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_assets_serial ON catalog_assets(serial)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_assets_name ON catalog_assets(name)")
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

def _nested_name(row: dict, key: str) -> str | None:
    value = row.get(key)
    if isinstance(value, dict):
        return value.get("name")
    return None


def upsert_assets(rows: list[dict]) -> int:
    now = _now_iso()
    ids = [int(r["id"]) for r in rows if r.get("id") is not None]

    with _connect() as conn:
        for r in rows:
            asset_id = r.get("id")
            if asset_id is None:
                continue

            assigned = r.get("assigned_to") if isinstance(r.get("assigned_to"), dict) else {}

            conn.execute(
                """
                INSERT INTO catalog_assets(
                    id,
                    asset_tag,
                    serial,
                    name,
                    model_name,
                    category_name,
                    status_name,
                    location_name,
                    assigned_type,
                    assigned_id,
                    assigned_name,
                    raw_json,
                    updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    asset_tag=excluded.asset_tag,
                    serial=excluded.serial,
                    name=excluded.name,
                    model_name=excluded.model_name,
                    category_name=excluded.category_name,
                    status_name=excluded.status_name,
                    location_name=excluded.location_name,
                    assigned_type=excluded.assigned_type,
                    assigned_id=excluded.assigned_id,
                    assigned_name=excluded.assigned_name,
                    raw_json=excluded.raw_json,
                    updated_at=excluded.updated_at
                """,
                (
                    int(asset_id),
                    str(r.get("asset_tag") or "").strip(),
                    str(r.get("serial") or "").strip(),
                    str(r.get("name") or "").strip(),
                    _nested_name(r, "model"),
                    _nested_name(r, "category"),
                    _nested_name(r, "status_label"),
                    _nested_name(r, "location") or _nested_name(r, "rtd_location"),
                    assigned.get("type"),
                    assigned.get("id"),
                    assigned.get("name"),
                    json.dumps(r),
                    now,
                ),
            )

        if ids:
            qmarks = ",".join(["?"] * len(ids))
            conn.execute(f"DELETE FROM catalog_assets WHERE id NOT IN ({qmarks})", ids)
        else:
            conn.execute("DELETE FROM catalog_assets")

        conn.commit()

    return len(ids)


def search_assets(query: str, limit: int = 25) -> list[dict]:
    q = str(query or "").strip()
    if not q:
        return []

    like = f"%{q}%"

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM catalog_assets
            WHERE asset_tag LIKE ?
               OR serial LIKE ?
               OR name LIKE ?
               OR model_name LIKE ?
            ORDER BY
                CASE
                    WHEN asset_tag = ? THEN 0
                    WHEN serial = ? THEN 1
                    WHEN name = ? THEN 2
                    ELSE 3
                END,
                asset_tag,
                name
            LIMIT ?
            """,
            (like, like, like, like, q, q, q, int(limit)),
        ).fetchall()

        return [dict(r) for r in rows]


def get_asset(asset_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM catalog_assets WHERE id = ?",
            (int(asset_id),),
        ).fetchone()

        return dict(row) if row else None
    
def get_assets_assigned_to_asset(parent_asset_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM catalog_assets
            WHERE assigned_id = ?
            ORDER BY asset_tag, name, serial
            """,
            (int(parent_asset_id),),
        ).fetchall()

        return [dict(r) for r in rows]


def list_cart_assets(location_name: str | None = None, limit: int = 500) -> list[dict]:
    params = []
    where = """
        (
            name LIKE '%CART%'
            OR asset_tag LIKE '%CART%'
            OR category_name LIKE '%CART%'
        )
    """

    if location_name:
        where += " AND location_name = ?"
        params.append(location_name)

    params.append(int(limit))

    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM catalog_assets
            WHERE {where}
            ORDER BY location_name, asset_tag, name
            LIMIT ?
            """,
            params,
        ).fetchall()

        return [dict(r) for r in rows]
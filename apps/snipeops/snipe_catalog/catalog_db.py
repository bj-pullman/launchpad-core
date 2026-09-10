from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from config.settings import SNIPE_CATALOG_DB_PATH

DB_PATH = SNIPE_CATALOG_DB_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


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
            model_id INTEGER,
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

        if not _table_has_column(conn, "catalog_assets", "model_id"):
            conn.execute("ALTER TABLE catalog_assets ADD COLUMN model_id INTEGER")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_assets_asset_tag ON catalog_assets(asset_tag)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_assets_serial ON catalog_assets(serial)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_assets_name ON catalog_assets(name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_assets_model_id ON catalog_assets(model_id)")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_catalog_assets_assignment
            ON catalog_assets(assigned_type, assigned_id)
            """
        )

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

            manufacturer = r.get("manufacturer") if isinstance(r.get("manufacturer"), dict) else {}

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
                (
                    int(mid),
                    r.get("name"),
                    manufacturer.get("name"),
                    r.get("model_number"),
                    json.dumps(r),
                    now,
                ),
            )

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

            conn.execute(
                f"""
                INSERT INTO {table}(id,name,raw_json,updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    raw_json=excluded.raw_json,
                    updated_at=excluded.updated_at
                """,
                (int(rid), r.get("name"), json.dumps(r), now),
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


def upsert_categories(rows: list[dict]) -> int:
    return _upsert_simple("catalog_categories", rows)


def upsert_manufacturers(rows: list[dict]) -> int:
    return _upsert_simple("catalog_manufacturers", rows)


def list_table(table: str, limit: int = 5000) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM {table} ORDER BY name LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]


def _nested_name(row: dict, key: str) -> str | None:
    value = row.get(key)
    if isinstance(value, dict):
        return value.get("name")
    return None


def _nested_id(row: dict, key: str) -> int | None:
    value = row.get(key)
    if isinstance(value, dict) and value.get("id") is not None:
        return int(value.get("id"))
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
                    model_id,
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
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    asset_tag=excluded.asset_tag,
                    serial=excluded.serial,
                    name=excluded.name,
                    model_id=excluded.model_id,
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
                    _nested_id(r, "model"),
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


def search_asset_catalog(
    query: str,
    *,
    page: int = 1,
    per_page: int = 25,
) -> dict:
    """Search the synchronized Snipe-IT asset cache with exact identifiers first."""
    q = str(query or "").strip()
    page = max(1, int(page or 1))
    per_page = min(100, max(10, int(per_page or 25)))
    if not q:
        return {"results": [], "total": 0, "page": page, "per_page": per_page, "pages": 0}

    like = f"%{q}%"
    match_sql = """
        a.asset_tag LIKE ?
        OR a.serial LIKE ?
        OR a.name LIKE ?
        OR a.model_name LIKE ?
        OR a.assigned_name LIKE ?
        OR a.location_name LIKE ?
        OR a.status_name LIKE ?
        OR parent.asset_tag LIKE ?
        OR parent.name LIKE ?
    """
    match_params = [like] * 9

    with _connect() as conn:
        total = int(conn.execute(
            f"""
            SELECT COUNT(*)
            FROM catalog_assets AS a
            LEFT JOIN catalog_assets AS parent
              ON lower(COALESCE(a.assigned_type, '')) = 'asset'
             AND parent.id = a.assigned_id
            WHERE {match_sql}
            """,
            match_params,
        ).fetchone()[0])

        rows = conn.execute(
            f"""
            SELECT a.*,
                   parent.asset_tag AS current_cart_asset_tag,
                   parent.name AS current_cart_name,
                   parent.location_name AS current_cart_location
            FROM catalog_assets AS a
            LEFT JOIN catalog_assets AS parent
              ON lower(COALESCE(a.assigned_type, '')) = 'asset'
             AND parent.id = a.assigned_id
            WHERE {match_sql}
            ORDER BY
                CASE
                    WHEN lower(COALESCE(a.asset_tag, '')) = lower(?) THEN 0
                    WHEN lower(COALESCE(a.serial, '')) = lower(?) THEN 1
                    WHEN lower(COALESCE(a.name, '')) = lower(?) THEN 2
                    ELSE 3
                END,
                a.asset_tag,
                a.name,
                a.id
            LIMIT ? OFFSET ?
            """,
            [*match_params, q, q, q, per_page, (page - 1) * per_page],
        ).fetchall()

    pages = (total + per_page - 1) // per_page if total else 0
    return {
        "results": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
    }


def search_cart_assets(query: str = "", *, limit: int = 50) -> list[dict]:
    """Search cart-like assets in the local catalog without calling Snipe-IT."""
    q = str(query or "").strip()
    search_params: list = []
    search_sql = ""
    if q:
        like = f"%{q}%"
        search_sql = """
          AND (asset_tag LIKE ? OR name LIKE ? OR category_name LIKE ? OR location_name LIKE ?)
        """
        search_params.extend([like, like, like, like])
    row_limit = min(250, max(1, int(limit)))

    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM catalog_assets
            WHERE (
                name LIKE 'CART%'
                OR asset_tag LIKE '%CART%'
                OR category_name LIKE '%CART%'
                OR model_name LIKE '%CART%'
            )
            {search_sql}
            ORDER BY
                CASE WHEN lower(COALESCE(asset_tag, '')) = lower(?) THEN 0 ELSE 1 END,
                location_name,
                asset_tag,
                name
            LIMIT ?
            """,
            [*search_params, q, row_limit],
        ).fetchall()
    return [dict(row) for row in rows]


def get_asset(asset_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM catalog_assets WHERE id = ?",
            (int(asset_id),),
        ).fetchone()

        return dict(row) if row else None

def update_asset_assignment(
    asset_id: int,
    *,
    assigned_type: str | None,
    assigned_id: int | None,
    assigned_name: str | None,
) -> dict | None:
    """
    Immediately update the cached assignment state for an asset.

    Media Catalog writes assignments directly to Snipe-IT, but reads its
    cart contents from the local catalog database. Updating the normalized
    assignment columns here keeps the UI consistent without requiring a
    full catalog sync after every cart operation.
    """
    now = _now_iso()

    with _connect() as conn:
        existing = conn.execute(
            """
            SELECT raw_json
            FROM catalog_assets
            WHERE id = ?
            """,
            (int(asset_id),),
        ).fetchone()

        if not existing:
            return None

        raw_data = {}

        try:
            raw_data = json.loads(existing["raw_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            raw_data = {}

        if assigned_id is None:
            raw_data["assigned_to"] = None
        else:
            raw_data["assigned_to"] = {
                "id": int(assigned_id),
                "type": assigned_type or "asset",
                "name": assigned_name or "",
            }

        conn.execute(
            """
            UPDATE catalog_assets
            SET assigned_type = ?,
                assigned_id = ?,
                assigned_name = ?,
                raw_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                assigned_type,
                int(assigned_id) if assigned_id is not None else None,
                assigned_name,
                json.dumps(raw_data),
                now,
                int(asset_id),
            ),
        )

        conn.commit()

        row = conn.execute(
            """
            SELECT *
            FROM catalog_assets
            WHERE id = ?
            """,
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


def list_assets_by_model_ids(model_ids: list[int]) -> list[dict]:
    ids = [int(mid) for mid in model_ids if mid]
    if not ids:
        return []

    qmarks = ",".join(["?"] * len(ids))

    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM catalog_assets
            WHERE model_id IN ({qmarks})
            ORDER BY model_name, asset_tag, serial, name
            """,
            ids,
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
    
def count_assets_assigned_to_assets(asset_ids: list[int]) -> dict[int, int]:
    """
    Return device counts for multiple parent assets in one query.

    The returned dictionary uses the parent/cart asset ID as the key
    and the number of assets assigned to that cart as the value.

    The parent cart itself is not counted.
    """
    normalized_ids = sorted({
        int(asset_id)
        for asset_id in asset_ids
        if asset_id is not None
    })

    if not normalized_ids:
        return {}

    placeholders = ",".join("?" for _ in normalized_ids)

    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                assigned_id,
                COUNT(*) AS device_count
            FROM catalog_assets
            WHERE lower(COALESCE(assigned_type, '')) = 'asset'
              AND assigned_id IN ({placeholders})
            GROUP BY assigned_id
            """,
            normalized_ids,
        ).fetchall()

    counts = {
        int(row["assigned_id"]): int(row["device_count"] or 0)
        for row in rows
        if row["assigned_id"] is not None
    }

    # Include carts that currently contain zero devices.
    return {
        asset_id: counts.get(asset_id, 0)
        for asset_id in normalized_ids
    }

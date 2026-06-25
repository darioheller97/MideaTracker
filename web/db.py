"""SQLite storage for the Midea tracker web app.

Three small tables:
  - watches:  one per user (personal token), their city + budget + push subscription
  - cache:    shared scrape results (key -> json payload), so we scrape once for all
  - geo:      geocode cache (city -> lat/lon/postcode)
"""

import json
import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "midea.db"
_LOCK = threading.Lock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _LOCK, _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS watches (
                token         TEXT PRIMARY KEY,
                city          TEXT NOT NULL,
                min_price     REAL,
                max_price     REAL,
                products      TEXT,            -- json list of product keys
                push_sub      TEXT,            -- json push subscription
                last_notified TEXT,            -- json {key: price}
                created_at    REAL,
                updated_at    REAL
            );
            CREATE TABLE IF NOT EXISTS cache (
                key     TEXT PRIMARY KEY,
                payload TEXT,                  -- json list of result dicts
                ts      REAL
            );
            CREATE TABLE IF NOT EXISTS geo (
                city     TEXT PRIMARY KEY,
                lat      REAL,
                lon      REAL,
                postcode TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )


# ── watches ────────────────────────────────────────────────────────────────

def create_watch(token: str, city: str, min_price: float, max_price: float,
                  products: list[str]) -> None:
    now = time.time()
    with _LOCK, _conn() as c:
        c.execute(
            "INSERT INTO watches (token, city, min_price, max_price, products, "
            "last_notified, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (token, city, min_price, max_price, json.dumps(products), "{}", now, now),
        )


def update_watch(token: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = [json.dumps(v) if k in ("products", "push_sub", "last_notified") else v
            for k, v in fields.items()]
    with _LOCK, _conn() as c:
        c.execute(f"UPDATE watches SET {cols} WHERE token=?", (*vals, token))


def get_watch(token: str) -> dict | None:
    with _LOCK, _conn() as c:
        row = c.execute("SELECT * FROM watches WHERE token=?", (token,)).fetchone()
    return _watch_row(row) if row else None


def all_watches() -> list[dict]:
    with _LOCK, _conn() as c:
        rows = c.execute("SELECT * FROM watches").fetchall()
    return [_watch_row(r) for r in rows]


def _watch_row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["products"] = json.loads(d.get("products") or "[]")
    d["push_sub"] = json.loads(d["push_sub"]) if d.get("push_sub") else None
    d["last_notified"] = json.loads(d.get("last_notified") or "{}")
    return d


# ── shared scrape cache ──────────────────────────────────────────────────────

def set_cache(key: str, payload: list[dict]) -> None:
    with _LOCK, _conn() as c:
        c.execute(
            "INSERT INTO cache (key, payload, ts) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET payload=excluded.payload, ts=excluded.ts",
            (key, json.dumps(payload, ensure_ascii=False), time.time()),
        )


def get_cache(key: str) -> tuple[list[dict], float] | None:
    with _LOCK, _conn() as c:
        row = c.execute("SELECT payload, ts FROM cache WHERE key=?", (key,)).fetchone()
    if not row:
        return None
    return json.loads(row["payload"]), row["ts"]


def latest_ts() -> float:
    with _LOCK, _conn() as c:
        row = c.execute("SELECT MAX(ts) AS t FROM cache").fetchone()
    return row["t"] or 0.0


# ── global settings ──────────────────────────────────────────────────────────

def get_setting(key: str, default=None):
    with _LOCK, _conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value) -> None:
    with _LOCK, _conn() as c:
        c.execute(
            "INSERT INTO settings (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )


# ── geocode cache ────────────────────────────────────────────────────────────

def get_geo(city: str) -> dict | None:
    with _LOCK, _conn() as c:
        row = c.execute("SELECT * FROM geo WHERE city=?", (city.lower(),)).fetchone()
    return dict(row) if row else None


def set_geo(city: str, lat: float, lon: float, postcode: str | None) -> None:
    with _LOCK, _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO geo (city, lat, lon, postcode) VALUES (?,?,?,?)",
            (city.lower(), lat, lon, postcode),
        )

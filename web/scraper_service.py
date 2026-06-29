"""Shared scraping + notification service.

Scrapes each shop ONCE per cycle (cached for all users); only OBI/Toom are scraped
per distinct city (cheap JSON APIs). Then each user's watch is evaluated against the
cached results and a Web Push is sent for new qualifying deals.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

# Reuse the desktop scraping engine (no GUI deps).
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import scrapers  # noqa: E402

from . import db, push  # noqa: E402

logger = logging.getLogger(__name__)

CATALOG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
SHOPS: dict = CATALOG.get("shops", {})
PRODUCTS: list = CATALOG.get("products", [])
PRICE_RANGE: dict = CATALOG.get("price_range", {"min": 0, "max": 5000})
# OBI & Toom are location-aware (per city); everything else is delivery/online → shared.
LOCATION_SHOPS = {"obi", "toom"}

# A desktop app on a residential IP can upload results for the online shops (it gets
# the bot-protected ones our datacenter IP can't). While such an upload is fresh, the
# server stops scraping that shop itself so its blocked results don't overwrite the
# good residential data. Local shops (OBI/Toom) are city-specific → never ingested.
INGEST_FRESH_SEC = int(os.environ.get("INGEST_FRESH_SEC", "5400"))  # 90 min default


def record_ingest(shops: list[str]) -> None:
    """Stamp now() as the last-ingest time for each uploaded shop."""
    try:
        cur = json.loads(db.get_setting("ingest_ts") or "{}")
    except Exception:
        cur = {}
    now = time.time()
    for s in shops:
        cur[s] = now
    db.set_setting("ingest_ts", json.dumps(cur))


def _fresh_ingested() -> set[str]:
    """Shops whose last desktop upload is recent enough to trust over a server scrape."""
    try:
        cur = json.loads(db.get_setting("ingest_ts") or "{}")
    except Exception:
        return set()
    now = time.time()
    return {s for s, ts in cur.items() if now - ts < INGEST_FRESH_SEC}


def _cfg(city: str | None) -> dict:
    c = dict(CATALOG)
    c["location"] = city or ""
    return c


def _scrape_one(shop_key: str, city: str | None = None) -> list[dict]:
    info = SHOPS.get(shop_key)
    if not info:
        return []
    try:
        return scrapers.scrape_shop(shop_key, info["url"], config=_cfg(city))
    except Exception as e:
        logger.warning("scrape %s failed: %s", shop_key, e)
        return [scrapers._error(shop_key, f"Fehler: {e}", info.get("url", ""))]


def scrape_catalog(cities: set[str]) -> None:
    """Scrape location-independent shops once + OBI/Toom per city; write to cache.

    Online shops with a fresh desktop upload are skipped (the residential-IP data
    is better than what our datacenter IP would get)."""
    fresh = _fresh_ingested()
    for key, info in SHOPS.items():
        if not info.get("active", True) or key in LOCATION_SHOPS:
            continue
        if key in fresh:
            logger.info("skip %s — using fresh desktop upload", key)
            continue
        db.set_cache(key, _scrape_one(key))
    for city in cities:
        for key in LOCATION_SHOPS:
            if not SHOPS.get(key, {}).get("active", True):
                continue
            db.set_cache(f"{key}|{city.lower()}", _scrape_one(key, city))


def results_for(city: str) -> list[dict]:
    """Assemble cached results for a city: shared shops + that city's OBI/Toom."""
    items: list[dict] = []
    for key, info in SHOPS.items():
        if not info.get("active", True):
            continue
        cached = (db.get_cache(f"{key}|{city.lower()}") if key in LOCATION_SHOPS
                  else db.get_cache(key))
        if cached:
            items.extend(cached[0])
    return items


def _is_deal(it: dict, mn: float, mx: float) -> bool:
    if it.get("in_stock") is False:
        return False
    price = it.get("price")
    return isinstance(price, (int, float)) and price > 0 and mn <= price <= mx


def evaluate_and_notify() -> None:
    for w in db.all_watches():
        sub = w.get("push_sub")
        if not sub:
            continue
        mn = w.get("min_price") or 0
        mx = w.get("max_price") or 10 ** 9
        last = dict(w.get("last_notified") or {})
        changed = False
        for it in results_for(w["city"]):
            if not _is_deal(it, mn, mx):
                continue
            key = f"{it.get('shop')}|{it.get('title')}"
            prev = last.get(key)
            price = it["price"]
            if prev is None or price < prev:
                last[key] = price
                changed = True
                push.send_push(sub, {
                    "title": f"💶 {it.get('shop')} — {price:.2f} €",
                    "body": it.get("title", "Midea PortaSplit"),
                    "url": it.get("url", ""),
                })
        if changed:
            db.update_watch(w["token"], last_notified=last)


def distinct_cities() -> set[str]:
    cities = {w["city"] for w in db.all_watches() if w.get("city")}
    return cities or {CATALOG.get("location", "Leipzig")}


def scrape_city_now(city: str) -> None:
    """Scrape only the location-aware shops for one city, synchronously.
    Used after a city change so the new city has data before the page loads."""
    city = city.strip()
    if not city:
        return
    for key in LOCATION_SHOPS:
        if not SHOPS.get(key, {}).get("active", True):
            continue
        try:
            db.set_cache(f"{key}|{city.lower()}", _scrape_one(key, city))
        except Exception:
            logger.exception("scrape_city_now failed for %s/%s", key, city)


def _cleanup_playwright_tmp() -> None:
    """Remove stale Playwright browser profile dirs from /tmp (they accumulate on crash)."""
    import glob, shutil, time
    stale_after = 3600  # seconds
    now = time.time()
    for pattern in (
        "/tmp/snap-private-tmp/snap.chromium/tmp/playwright_chromiumdev_profile-*",
        "/tmp/playwright_chromiumdev_profile-*",
    ):
        for path in glob.glob(pattern):
            try:
                if now - os.path.getmtime(path) > stale_after:
                    shutil.rmtree(path, ignore_errors=True)
            except Exception:
                pass


def run_cycle() -> None:
    cities = distinct_cities()
    logger.info("Scrape cycle: %d city(ies), %d shops", len(cities), len(SHOPS))
    try:
        _cleanup_playwright_tmp()
        scrape_catalog(cities)
        evaluate_and_notify()
    except Exception:
        logger.exception("scrape cycle failed")

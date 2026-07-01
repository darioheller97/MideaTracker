"""FastAPI app for the Midea tracker — midea.iceatea.me.

Per-user watches via a private token (no passwords), a shared scrape cache, and
Web Push notifications. Run with:  uvicorn web.app:app
"""

import logging
import os
import secrets
import subprocess
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db, push, scraper_service as svc

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
SCAN_INTERVAL_MIN = int(os.environ.get("SCAN_INTERVAL_MIN", "5"))
# Shared secret the desktop app sends to upload its residential-IP scrape results.
# Unset → the /ingest endpoint is disabled.
INGEST_SECRET = os.environ.get("INGEST_SECRET", "")


def _app_version() -> str:
    """A build id that changes only when the deployed code changes.

    Uses the git commit hash so a redeploy (pull + restart) bumps it and open
    clients get a 'refresh' prompt, while a plain restart (same code) does not.
    """
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE.parent,
                             capture_output=True, text=True, timeout=3)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return "dev"


APP_VERSION = _app_version()

app = FastAPI(title="Midea Tracker")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


# ── lifecycle ────────────────────────────────────────────────────────────────

def _current_interval() -> int:
    """Return the active scan interval (DB setting > env var > 20 min)."""
    val = db.get_setting("scan_interval_min")
    try:
        return max(1, int(val)) if val is not None else SCAN_INTERVAL_MIN
    except (TypeError, ValueError):
        return SCAN_INTERVAL_MIN


@app.on_event("startup")
def _startup():
    db.init_db()
    push.ensure_keys()
    if os.environ.get("MIDEA_NO_SCRAPE") == "1":
        logger.info("MIDEA_NO_SCRAPE=1 — skipping scheduler/scrape (test mode)")
        return
    # First scrape in the background so startup isn't blocked.
    threading.Thread(target=svc.run_cycle, daemon=True).start()
    interval = _current_interval()
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        sched = BackgroundScheduler(daemon=True)
        sched.add_job(svc.run_cycle, "interval", minutes=interval,
                      id="scrape", max_instances=1, coalesce=True)
        sched.start()
        app.state.scheduler = sched
        logger.info("Scheduler started (every %d min)", interval)
    except Exception:
        logger.exception("Could not start scheduler")


# ── helpers ──────────────────────────────────────────────────────────────────

def _sorted_results(items: list[dict]) -> list[dict]:
    def keyf(it):
        grp = 0 if it.get("in_stock") is True else (1 if it.get("in_stock") is False else 2)
        price = it.get("price")
        return (grp, price if isinstance(price, (int, float)) else float("inf"))
    return sorted(items, key=keyf)


# ── pages ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "products": svc.PRODUCTS,
        "price_range": svc.PRICE_RANGE,
        "default_city": svc.CATALOG.get("location", "Leipzig"),
    })


@app.post("/watch")
def create_watch(city: str = Form(...), min_price: float = Form(0),
                 max_price: float = Form(1500), products: list[str] = Form(default=[])):
    token = secrets.token_urlsafe(12)
    db.create_watch(token, city.strip() or "Leipzig", min_price, max_price, products)
    return RedirectResponse(url=f"/w/{token}", status_code=303)


@app.get("/w/{token}", response_class=HTMLResponse)
def watch_page(request: Request, token: str):
    w = db.get_watch(token)
    if not w:
        raise HTTPException(404, "Unbekannter Link")
    return templates.TemplateResponse(request, "watch.html", {
        "watch": w, "products": svc.PRODUCTS,
        "app_server_key": push.application_server_key(),
        "scan_interval_min": _current_interval(),
    })


# ── api ──────────────────────────────────────────────────────────────────────

@app.get("/api/results")
def api_results(token: str):
    w = db.get_watch(token)
    if not w:
        raise HTTPException(404, "Unbekannter Link")
    items = svc.results_for(w["city"])
    ts = db.latest_ts()
    interval = _current_interval()
    now = time.time()
    # Data is "stale" if the last scan is older than 2× the scan interval.
    stale = bool(ts) and (now - ts) > interval * 60 * 2
    next_scan_est = int(max(0, (ts + interval * 60) - now)) if ts else None
    return JSONResponse({
        "city": w["city"],
        "min_price": w.get("min_price"),
        "max_price": w.get("max_price"),
        "updated": ts,
        "updated_human": time.strftime("%d.%m.%Y %H:%M", time.localtime(ts)) if ts else "—",
        "results": _sorted_results(items),
        "version": APP_VERSION,
        "interval_min": interval,
        "stale": stale,
        "next_scan_sec": next_scan_est,
    })


@app.post("/ingest")
async def ingest(request: Request):
    """Receive residential-IP scrape results from the desktop app.

    Body: {"shops": {"<shop_key>": [<result dict>, ...], ...}}. Only known,
    non-location (online) shops are accepted — local shops (OBI/Toom) are
    city-specific and must stay server-scraped per city."""
    if not INGEST_SECRET:
        raise HTTPException(503, "Ingest deaktiviert (kein INGEST_SECRET gesetzt)")
    if not secrets.compare_digest(request.headers.get("X-Ingest-Token", ""), INGEST_SECRET):
        raise HTTPException(403, "Ungültiges Ingest-Token")
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Ungültiges JSON")
    shops = data.get("shops") if isinstance(data, dict) else None
    if not isinstance(shops, dict):
        raise HTTPException(400, "Feld 'shops' (Objekt) erwartet")
    accepted: list[str] = []
    for key, results in shops.items():
        if (key in svc.SHOPS and key not in svc.LOCATION_SHOPS
                and isinstance(results, list)):
            clean = [r for r in results if isinstance(r, dict)][:50]
            db.set_cache(key, clean)
            accepted.append(key)
    if accepted:
        svc.record_ingest(accepted)
        logger.info("Ingest accepted shops: %s", ", ".join(accepted))
    return {"ok": True, "accepted": accepted}


@app.post("/w/{token}/delete")
def delete_watch(token: str):
    if not db.get_watch(token):
        raise HTTPException(404, "Unbekannter Link")
    db.delete_watch(token)
    return RedirectResponse(url="/", status_code=303)


@app.post("/w/{token}/settings")
def update_settings(token: str, city: str = Form(...), min_price: float = Form(0),
                    max_price: float = Form(1500), products: list[str] = Form(default=[]),
                    scan_interval_min: int = Form(20)):
    if not db.get_watch(token):
        raise HTTPException(404)
    new_city = city.strip() or "Leipzig"
    old_city = (db.get_watch(token) or {}).get("city", "")
    db.update_watch(token, city=new_city, min_price=min_price,
                    max_price=max_price, products=products, last_notified={})
    interval = max(1, scan_interval_min)
    db.set_setting("scan_interval_min", interval)
    sched = getattr(app.state, "scheduler", None)
    if sched:
        try:
            sched.reschedule_job("scrape", trigger="interval", minutes=interval)
            logger.info("Scan interval updated to %d min", interval)
        except Exception:
            logger.exception("Failed to reschedule scrape job")
    if new_city.lower() != old_city.lower():
        # Scrape location shops for the new city synchronously so the watch
        # page shows correct results immediately on redirect (OBI/Toom use
        # plain HTTP APIs so this completes in a few seconds).
        svc.scrape_city_now(new_city)
    threading.Thread(target=svc.run_cycle, daemon=True).start()
    return RedirectResponse(url=f"/w/{token}", status_code=303)


@app.post("/w/{token}/subscribe")
async def subscribe(token: str, request: Request):
    if not db.get_watch(token):
        raise HTTPException(404)
    sub = await request.json()
    db.update_watch(token, push_sub=sub)
    return {"ok": True}


@app.post("/w/{token}/test-push")
def test_push(token: str):
    w = db.get_watch(token)
    if not w or not w.get("push_sub"):
        raise HTTPException(400, "Keine Push-Anmeldung")
    ok = push.send_push(w["push_sub"], {
        "title": "✅ Test", "body": "Benachrichtigungen funktionieren!", "url": f"/w/{token}"})
    return {"ok": ok}


# ── PWA assets (served at root scope) ────────────────────────────────────────

@app.get("/sw.js")
def service_worker():
    return FileResponse(HERE / "static" / "sw.js", media_type="application/javascript")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(HERE / "static" / "manifest.webmanifest",
                        media_type="application/manifest+json")

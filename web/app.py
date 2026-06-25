"""FastAPI app for the Midea tracker — midea.iceatea.me.

Per-user watches via a private token (no passwords), a shared scrape cache, and
Web Push notifications. Run with:  uvicorn web.app:app
"""

import logging
import os
import secrets
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
SCAN_INTERVAL_MIN = int(os.environ.get("SCAN_INTERVAL_MIN", "20"))

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
    return JSONResponse({
        "city": w["city"],
        "min_price": w.get("min_price"),
        "max_price": w.get("max_price"),
        "updated": ts,
        "updated_human": time.strftime("%d.%m.%Y %H:%M", time.localtime(ts)) if ts else "—",
        "results": _sorted_results(items),
    })


@app.post("/w/{token}/settings")
def update_settings(token: str, city: str = Form(...), min_price: float = Form(0),
                    max_price: float = Form(1500), products: list[str] = Form(default=[]),
                    scan_interval_min: int = Form(20)):
    if not db.get_watch(token):
        raise HTTPException(404)
    db.update_watch(token, city=city.strip() or "Leipzig", min_price=min_price,
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

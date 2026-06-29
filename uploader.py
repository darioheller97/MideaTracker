"""Upload residential-IP scrape results to the web app (midea.icetea.me).

The web server runs on a datacenter IP that bot-protected shops block, while this
desktop app runs on a home/residential IP that can reach them. So after each scan we
POST the ONLINE shops' results up to the web app's /ingest endpoint. Local shops
(OBI/Toom etc.) are city-specific and stay server-scraped per city, so we skip them.

Config (first match wins):
  1. env vars MIDEA_INGEST_URL + MIDEA_INGEST_SECRET
  2. an ``upload.json`` next to the .exe (or next to this file when run from source):
       {"url": "https://midea.icetea.me/ingest", "secret": "<shared secret>"}
Uploading is silently disabled when neither is configured.
"""

import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _config_paths() -> list[Path]:
    paths: list[Path] = []
    if getattr(sys, "frozen", False):           # PyInstaller .exe → look beside the exe
        paths.append(Path(sys.executable).resolve().parent / "upload.json")
    paths.append(Path(__file__).resolve().parent / "upload.json")   # source checkout
    return paths


def load_upload_config() -> dict | None:
    url = os.environ.get("MIDEA_INGEST_URL", "").strip()
    secret = os.environ.get("MIDEA_INGEST_SECRET", "").strip()
    if url and secret:
        return {"url": url, "secret": secret}
    for p in _config_paths():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
        if data.get("url") and data.get("secret"):
            return {"url": data["url"], "secret": data["secret"]}
    return None


def upload_results(results: dict[str, list[dict]], shops_cfg: dict) -> bool:
    """POST the online (non-local) shops' results to the web app. Returns True on 200.

    ``results`` is {shop_key: [result dicts]}; ``shops_cfg`` is config["shops"], used
    to drop local/city-specific shops. Safe to call from a background thread."""
    cfg = load_upload_config()
    if not cfg:
        return False
    payload_shops: dict[str, list] = {}
    for key, items in results.items():
        if shops_cfg.get(key, {}).get("local", False):
            continue   # city-specific → the server handles it per city
        if isinstance(items, list):
            payload_shops[key] = items
    if not payload_shops:
        return False
    try:
        import requests
        r = requests.post(
            cfg["url"], json={"shops": payload_shops},
            headers={"X-Ingest-Token": cfg["secret"]}, timeout=20,
        )
        if r.status_code == 200:
            logger.info("Uploaded %d shop(s) to web app: %s",
                        len(payload_shops), ", ".join(sorted(payload_shops)))
            return True
        logger.warning("Upload failed: HTTP %d %s", r.status_code, r.text[:200])
    except Exception as e:
        logger.warning("Upload error: %s", e)
    return False

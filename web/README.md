# Midea Tracker — Web App (midea.iceatea.me)

A small **FastAPI + PWA** front-end for the Midea PortaSplit tracker. It reuses the
desktop app's scraping engine (`../scrapers.py`), scrapes **once per interval and shares
the results with all users** (so user count doesn't increase bot-blocking), and sends
**Web Push** alerts to phones. Per-user setup is via a **private link** (no accounts).

## How it works
- One scheduled scrape per interval caches results (SQLite `web/midea.db`).
- Location-independent shops are scraped once; **OBI/Toom** are scraped per distinct
  **city** (cheap JSON APIs, fine from any IP).
- Each user opens `/`, sets city + budget + models, gets a private `/w/<token>` link,
  and can enable push notifications (PWA).

## Run locally
```bash
pip install -r web/requirements.txt
# optional: enables the browser-based shops (Euronics/Hornbach/...); API shops work without it
python -m playwright install chromium
# from the repo root:
uvicorn web.app:app --host 127.0.0.1 --port 8770
```
Open http://127.0.0.1:8770 . (Web Push needs HTTPS — works behind the reverse proxy below;
on localhost most browsers also allow it for testing.)

## Environment
- `SCAN_INTERVAL_MIN` — scrape interval in minutes (default 20).
- `VAPID_CLAIM_EMAIL` — e.g. `mailto:admin@iceatea.me`.
- VAPID keys are auto-generated into `web/.vapid_private.pem` + `web/.vapid.json` on first
  run. **Keep these files** (back them up) — regenerating them invalidates existing push
  subscriptions. They are git-ignored.

## Deploy on the server (midea.iceatea.me)
HTTPS is required for service workers / Web Push.

**Caddy** (auto-TLS) — add to the Caddyfile:
```
midea.iceatea.me {
    reverse_proxy 127.0.0.1:8770
}
```

**nginx** — `proxy_pass http://127.0.0.1:8770;` on a `server_name midea.iceatea.me;`
block with a Let's Encrypt cert (certbot) or your wildcard.

**systemd** (`/etc/systemd/system/midea.service`):
```ini
[Unit]
Description=Midea Tracker web app
After=network.target

[Service]
WorkingDirectory=/opt/MideaTracker
Environment=SCAN_INTERVAL_MIN=20
Environment=VAPID_CLAIM_EMAIL=mailto:admin@iceatea.me
ExecStart=/opt/MideaTracker/.venv/bin/uvicorn web.app:app --host 127.0.0.1 --port 8770
Restart=always

[Install]
WantedBy=multi-user.target
```
`systemctl enable --now midea`.

## Notes
- **Protected shops** (Cyberport, Bauhaus, sometimes Hornbach pickup) are best-effort from
  a datacenter IP and may show "blockiert"; OBI/Toom (APIs) + the tolerant shops carry the
  service. No proxy is used (by design).
- Hornbach is **delivery-only** here (per-city pickup needs the market-cookie mapping,
  not ported to the web app).
- iOS: Web Push requires installing the page via Safari → Share → **Zum Home-Bildschirm**
  (iOS 16.4+), then opening it from the home screen.

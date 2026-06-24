"""Shop scrapers for Midea PortaSplit Preis-Monitor.

Each scraper function takes a URL and returns a list of dicts:
    {
        "shop": str,
        "title": str,
        "price": float | None,
        "currency": str,
        "url": str,
        "in_stock": bool | None,
        "error": str | None,
    }
"""

import json
import math
import re
import logging
import threading
from typing import Any

import requests
from lxml import html as lhtml

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

TIMEOUT = 20

# Keywords that identify Midea products (lowercase)
_MIDEA_KW = ["midea", "portasplit", "klimaanlage", "mobile klimaanlage"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch(url: str) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.text
        logger.warning("%s returned status %d", url, r.status_code)
        return None
    except requests.RequestException as e:
        logger.error("Error fetching %s: %s", url, e)
        return None


def _price_from_text(text: str) -> float | None:
    if not text:
        return None
    text = text.strip().replace("\xa0", " ").replace("\u20ac", "").replace("EUR", "").strip()
    # German: 1.299,00
    m = re.search(r"(\d[\d\.]*,\d{2})", text)
    if m:
        raw = m.group(1).replace(".", "").replace(",", ".")
        try:
            return round(float(raw), 2)
        except ValueError:
            pass
    # Plain: 1299.00
    m = re.search(r"(\d+\.\d{2})", text)
    if m:
        try:
            return round(float(m.group(1)), 2)
        except ValueError:
            pass
    return None


def _is_midea_product(title: str) -> bool:
    """Check if a product title is likely a Midea PortaSplit."""
    tl = title.lower()
    has_midea = any(kw in tl for kw in ["midea portasplit", "midea", "portasplit"])
    # Exclude non-Midea products
    if not has_midea:
        return False
    # Exclude accessories (filters, hoses, etc) unless portasplit is mentioned
    if "portasplit" not in tl and any(excl in tl for excl in ["filter", "schlauch", "abdeckung", "fensterdichtung"]):
        return False
    return True


def _clean_url(base_url: str, link: str) -> str:
    if not link:
        return base_url
    if link.startswith("http"):
        return link
    if link.startswith("/"):
        from urllib.parse import urlparse
        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}{link}"
    return base_url


# ---------------------------------------------------------------------------
# Playwright browser helper
# ---------------------------------------------------------------------------

_PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass


_PW_CHECKED = False


def _ensure_playwright_browser():
    """Install Chromium for Playwright if not already present (once per run)."""
    global _PW_CHECKED
    if _PW_CHECKED:
        return True
    import os, subprocess, sys
    try:
        base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "ms-playwright")
        if os.path.isdir(base) and any(e.startswith("chromium") for e in os.listdir(base)):
            _PW_CHECKED = True
            return True
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, timeout=180, check=False,
        )
        _PW_CHECKED = True
        return True
    except Exception as e:
        logger.debug("Playwright browser check: %s", e)
        return False


# Full stealth payload (more convincing than just navigator.webdriver).
_STEALTH_JS = (
    'Object.defineProperty(navigator,"webdriver",{get:()=>undefined});'
    'Object.defineProperty(navigator,"languages",{get:()=>["de-DE","de"]});'
    'Object.defineProperty(navigator,"plugins",{get:()=>[1,2,3,4,5]});'
    'window.chrome={runtime:{}};'
)
# Substrings that indicate a bot-challenge / interstitial rather than real content.
_CHALLENGE_MARKERS = (
    "Sicherheitsüberprüfung", "kein Bot", "Just a moment",
    "Checking your browser", "Cloudflare", "Enable JavaScript",
    "wird überprüft", "Bitte aktivieren Sie JavaScript",
)


# Which browser to launch — probed once, then cached.
#   None  = not yet probed
#   dict  = working launch kwargs (e.g. {} for bundled, {"channel": "msedge"})
#   False = no usable browser found
_BROWSER_CHOICE: dict | bool | None = None
_BROWSER_LOCK = threading.Lock()


def _launch_chromium(pw):
    """Launch a Chromium-based browser using whatever is available on the PC:
    Playwright's bundled Chromium, else system Edge (on every Windows PC),
    else system Chrome. Returns a browser or None. The first working choice
    is cached so we don't re-probe on every fetch."""
    global _BROWSER_CHOICE
    args = ["--disable-blink-features=AutomationControlled"]
    with _BROWSER_LOCK:
        choice = _BROWSER_CHOICE
    if choice is False:
        return None
    if isinstance(choice, dict):
        try:
            return pw.chromium.launch(headless=True, args=args, **choice)
        except Exception:
            pass  # cached choice stopped working — fall through to re-probe
    for kw in ({}, {"channel": "msedge"}, {"channel": "chrome"}):
        try:
            browser = pw.chromium.launch(headless=True, args=args, **kw)
            with _BROWSER_LOCK:
                _BROWSER_CHOICE = kw
            logger.info("Browser: %s", kw.get("channel", "bundled Chromium"))
            return browser
        except Exception as e:
            logger.debug("launch %s failed: %s", kw or "bundled", e)
    with _BROWSER_LOCK:
        _BROWSER_CHOICE = False
    logger.warning("No usable browser found (need Chromium, Edge or Chrome).")
    return None


def _browser_fetch(
    url: str,
    timeout_ms: int = 40000,
    cookies: list[dict] | None = None,
    wait_polls: int = 12,
) -> tuple[str | None, str | None]:
    """Fetch a page with Playwright (headless + stealth).

    Polls the body up to ``wait_polls`` × 2s, waiting *past* Cloudflare/Akamai
    challenges until real content appears. Returns (body_text, html) or (None, None).
    Optional ``cookies`` (list of {name,value,domain,path}) e.g. to pick a store.
    """
    if not _PLAYWRIGHT_AVAILABLE:
        logger.warning("Playwright not installed — cannot browser-fetch %s", url)
        return None, None
    try:
        with sync_playwright() as pw:
            browser = _launch_chromium(pw)
            if browser is None:
                return None, None
            context = browser.new_context(
                locale="de-DE",
                viewport={"width": 1366, "height": 1000},
                user_agent=HEADERS["User-Agent"],
            )
            context.add_init_script(_STEALTH_JS)
            if cookies:
                try:
                    context.add_cookies(cookies)
                except Exception as e:
                    logger.debug("add_cookies failed: %s", e)
            page = context.new_page()
            try:
                page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            except Exception as e:
                logger.debug("goto soft-failed for %s: %s", url, e)
            body_text, html = "", ""
            for _ in range(max(1, wait_polls)):
                page.wait_for_timeout(2000)
                try:
                    body_text = page.inner_text("body")
                    html = page.content()
                except Exception:
                    body_text, html = "", ""
                if len(body_text) > 600 and not any(c in body_text for c in _CHALLENGE_MARKERS):
                    break
            browser.close()
            return body_text or None, html or None
    except Exception as e:
        logger.warning("Playwright fetch failed for %s: %s", url, e)
        return None, None


# ---------------------------------------------------------------------------
# Geolocation (makes "local" shops actually honour the configured city)
# ---------------------------------------------------------------------------

_GEO_CACHE: dict[str, tuple[float, float, str | None]] = {}
_GEO_LOCK = threading.Lock()


def _geocode(city: str) -> tuple[float, float, str | None] | None:
    """Geocode a city name → (lat, lon, postcode) via OSM Nominatim, cached."""
    if not city:
        return None
    key = city.strip().lower()
    with _GEO_LOCK:
        if key in _GEO_CACHE:
            return _GEO_CACHE[key]
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": city, "format": "json", "limit": 1,
                    "addressdetails": 1, "countrycodes": "de"},
            headers={"User-Agent": "PortaSplitMonitor/1.0 (price monitor)"},
            timeout=15,
        )
        data = r.json()
        if not data:
            return None
        lat = float(data[0]["lat"])
        lon = float(data[0]["lon"])
        postcode = (data[0].get("address", {}) or {}).get("postcode")
        result = (lat, lon, postcode)
        with _GEO_LOCK:
            _GEO_CACHE[key] = result
        return result
    except Exception as e:
        logger.warning("Geocode failed for %s: %s", city, e)
        return None


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in km between two lat/lon points."""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _structured_price(html_content: str | None, body_text: str | None) -> float | None:
    """Pull a price from structured data first (reliable), then visible text."""
    if html_content:
        m = re.search(r'property="product:price:amount"\s+content="([\d.,]+)"', html_content)
        if m:
            p = _price_from_text(m.group(1).replace(".", "X").replace(",", ".").replace("X", ""))
            if p:
                return p
        for item in _extract_jsonld(html_content):
            for obj in (item if isinstance(item, list) else [item]):
                if not isinstance(obj, dict):
                    continue
                offers = obj.get("offers")
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                if isinstance(offers, dict) and offers.get("price"):
                    try:
                        return round(float(str(offers["price"]).replace(",", ".")), 2)
                    except ValueError:
                        pass
        m = re.search(r'itemprop="price"[^>]*content="([\d.,]+)"', html_content)
        if m:
            try:
                return round(float(m.group(1).replace(".", "").replace(",", ".")) if "," in m.group(1)
                             else float(m.group(1)), 2)
            except ValueError:
                pass
    return _price_from_text(body_text or "")


def _stock_from_text(body: str) -> bool | None:
    """Best-effort availability from rendered page text."""
    b = (body or "").lower()
    neg = ["nicht lieferbar", "nicht verfügbar", "ausverkauft", "derzeit nicht",
           "nicht auf lager", "vergriffen", "nicht online bestellbar", "nicht reservierbar"]
    pos = ["in den warenkorb", "sofort lieferbar", "auf lager", "lieferbar",
           "sofort verfügbar", "jetzt kaufen"]
    if any(n in b for n in neg):
        return False
    if any(p in b for p in pos):
        return True
    return None


# How far (km) and how many stores to consider for "local" pickup chains.
DEFAULT_RADIUS_KM = 100
MAX_LOCAL_MARKETS = 8


def _generic_browser_scrape(url: str, shop: str, **kwargs) -> list[dict[str, Any]]:
    """Render a product page with the strong stealth browser and extract
    price + stock. Used for shops without a clean API (Euronics, Cyberport, …)."""
    body, html = _browser_fetch(url)
    if not body or len(body) < 400 or any(c in body for c in _CHALLENGE_MARKERS):
        return [_error(shop, f"{shop} blockiert / nicht erreichbar (Bot-Schutz)", url)]
    price = _structured_price(html, body)
    if price is not None and price <= 0:
        price = None
    stock = _stock_from_text(body)
    title = ""
    if html:
        tm = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
        if tm:
            title = re.sub(r"\s+", " ", tm.group(1)).strip()[:120]
    # Fail safe: if the render produced neither a real price nor a clear stock
    # signal nor a plausible product title, treat it as unreadable (not garbage).
    looks_product = "portasplit" in (title + body[:3000]).lower()
    if price is None and stock is None and not looks_product:
        return [_error(shop, f"{shop} nicht vollständig geladen / blockiert", url)]
    if not title or "portasplit" not in title.lower():
        title = f"Midea PortaSplit ({shop})"
    return [{
        "shop": shop,
        "title": title,
        "price": price,
        "currency": "€",
        "url": url,
        "in_stock": stock,
        "error": None,
    }]


# --- Toom API helpers (clean JSON, IP-robust) ------------------------------

_TOOM_BAD = ("unavailable", "nicht", "not purchasable", "not available", "leider")


def _toom_jsonview(product_id: str, market_id: int) -> dict | None:
    try:
        r = requests.get(
            f"https://api.toom.de/public/v1/jsonview/{product_id}/{market_id}",
            headers={**HEADERS, "Accept": "application/json"}, timeout=TIMEOUT,
        )
        return r.json()
    except Exception:
        return None


def _toom_block(block: dict | None) -> tuple[bool | None, float | None]:
    """Parse a deliver/reserve block → (available, offer_price)."""
    if not block:
        return None, None
    state = str(block.get("state", "")).lower()
    offer = (block.get("price") or {}).get("offer")
    try:
        offer = float(offer) if offer is not None else None
    except (TypeError, ValueError):
        offer = None
    if not state:
        return None, offer
    return (not any(b in state for b in _TOOM_BAD)), offer


def _market_latlon(m: dict) -> tuple[float, float] | None:
    a = m.get("address", {}) or {}
    if a.get("latitude") and a.get("longitude"):
        try:
            return float(a["latitude"]), float(a["longitude"])
        except (TypeError, ValueError):
            return None
    return None


def _nearest_markets(markets: list[dict], geo: tuple, radius_km: float) -> list[tuple[dict, float]]:
    """Return [(market, distance_km)] within radius, nearest first, capped."""
    lat, lon = geo[0], geo[1]
    cand = []
    for m in markets:
        ll = _market_latlon(m)
        if not ll:
            continue
        d = _haversine(lat, lon, ll[0], ll[1])
        if d <= radius_km:
            cand.append((m, d))
    cand.sort(key=lambda x: x[1])
    return cand[:MAX_LOCAL_MARKETS]


def _extract_jsonld(html_content: str) -> list[dict]:
    """Extract JSON-LD structured data from HTML."""
    results = []
    for m in re.finditer(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html_content, re.DOTALL | re.IGNORECASE,
    ):
        try:
            data = json.loads(m.group(1))
            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)
        except json.JSONDecodeError:
            pass
    return results


# ---------------------------------------------------------------------------
# Amazon.de (Playwright — product page)
# ---------------------------------------------------------------------------

def scrape_amazon(url: str, **kwargs) -> list[dict[str, Any]]:
    config = kwargs.get("config", {})
    shop_info = {}
    for k, v in config.get("shops", {}).items():
        if v.get("url") == url:
            shop_info = v
            break
    is_product_page = shop_info.get("product_page", False)

    if is_product_page:
        return _scrape_amazon_product(url)
    return _scrape_amazon_search(url)


def _scrape_amazon_product(url: str) -> list[dict[str, Any]]:
    """Scrape a single Amazon product detail page."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = _launch_chromium(pw)
            if browser is None:
                raise RuntimeError("kein Browser (Chromium/Edge/Chrome) verfügbar")
            context = browser.new_context(locale="de-DE", viewport={"width": 1920, "height": 1080})
            context.add_init_script('Object.defineProperty(navigator, "webdriver", {get: () => undefined});')
            page = context.new_page()
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)

            title = page.title()

            # Price from corePrice
            price_data = page.evaluate("""() => {
                const priceEl = document.querySelector('#corePrice_desktop .a-price .a-offscreen, ' +
                    '#priceblock_ourprice, #priceblock_dealprice, ' +
                    '.a-price .a-offscreen, .aok-offscreen');
                if (priceEl) return priceEl.textContent.trim();
                // Try buy box
                const box = document.getElementById('buyBoxInner') || document.getElementById('buybox');
                if (box) {
                    const p = box.querySelector('.a-price .a-offscreen');
                    if (p) return p.textContent.trim();
                }
                return '';
            }""")
            price = _price_from_text(price_data)

            # Stock status from page text
            body = page.inner_text("body")
            stock = None
            if "derzeit nicht auf lager" in body.lower() or "nicht verfügbar" in body.lower():
                stock = False
            elif "auf lager" in body.lower() or "sofort lieferbar" in body.lower():
                stock = True
            else:
                # Check if add-to-cart button exists
                has_btn = page.evaluate("""() => {
                    const box = document.getElementById('buyBoxInner') || document.getElementById('buybox');
                    return box ? !!box.querySelector('[type=\"submit\"], input[name=\"submit.addToCart\"]') : false;
                }""")
                stock = True if has_btn else None

            browser.close()

        if price or stock is not None:
            return [{
                "shop": "Amazon.de",
                "title": title.strip(),
                "price": price,
                "currency": "€",
                "url": url,
                "in_stock": stock,
                "error": None,
            }]
    except Exception as e:
        logger.warning("Amazon product scrape failed: %s", e)

    return [_error("Amazon.de", "Preis nicht ermittelbar (Blockiert?)", url)]


def _scrape_amazon_search(url: str) -> list[dict[str, Any]]:
    """Scrape Amazon search results page."""
    body_text, html = _browser_fetch(url)
    if not body_text:
        html_r = _fetch(url)
        if not html_r:
            return [_error("Amazon.de", "Seite nicht erreichbar", url)]
        tree = lhtml.fromstring(html_r)
    else:
        from lxml.html import fromstring
        tree = fromstring(html)

    results: list[dict[str, Any]] = []
    items = tree.cssselect("[data-asin]")
    for item in items:
        asin = item.get("data-asin", "")
        if not asin:
            continue
        title_el = item.cssselect("h2 a span, h2 a, .a-text-normal")
        title = title_el[0].text_content().strip() if title_el else ""
        if not _is_midea_product(title):
            continue
        price_el = item.cssselect(".a-price .a-offscreen, .a-price-whole")
        price_text = price_el[0].text_content().strip() if price_el else ""
        price = _price_from_text(price_text)
        link_el = item.cssselect("h2 a")
        link = link_el[0].get("href") if link_el else ""
        results.append({
            "shop": "Amazon.de",
            "title": title,
            "price": price,
            "currency": "€",
            "url": _clean_url(url, link),
            "in_stock": None,
            "error": None,
        })

    if not results:
        results.append(_error("Amazon.de", "Keine Midea PortaSplit Produkte gefunden", url))
    return results


# ---------------------------------------------------------------------------
# MediaMarkt (Playwright + JSON-LD)
# ---------------------------------------------------------------------------

def scrape_mediamarkt(url: str, **kwargs) -> list[dict[str, Any]]:
    # Use Playwright for full DOM extraction with availability
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = _launch_chromium(pw)
            if browser is None:
                raise RuntimeError("kein Browser (Chromium/Edge/Chrome) verfügbar")
            context = browser.new_context(locale="de-DE", viewport={"width": 1920, "height": 1080})
            context.add_init_script(
                'Object.defineProperty(navigator, "webdriver", {get: () => undefined});'
            )
            page = context.new_page()
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(7000)

            # Extract product data via JS
            products_js = page.evaluate("""() => {
                const cards = document.querySelectorAll('article');
                const results = [];
                cards.forEach(card => {
                    const text = card.innerText;
                    const lines = text.split(String.fromCharCode(10)).filter(l => l.trim());

                    // Product name: first line that looks like a product name (skip 'Produktdatenblatt')
                    let title = '';
                    for (const line of lines) {
                        const t = line.trim();
                        if (t && t !== 'Produktdatenblatt' && t.length > 5 && !t.startsWith('0') && !t.startsWith('Basierend')) {
                            title = t;
                            break;
                        }
                    }

                    // Price: first number with €
                    const priceMatch = text.match(/(\\d[\\d\\.,]*\\d{2})\\s*[€]/);
                    const price = priceMatch ? priceMatch[1] : '';

                    // Link
                    const linkEl = card.querySelector('a[href*=\"/product/\"]');
                    const link = linkEl ? linkEl.getAttribute('href') : '';

                    // Availability
                    let available = null;
                    let delivery = '';
                    if (/keine lieferung/i.test(text)) { available = false; delivery = '❌ Keine Lieferung'; }
                    else if (/lieferung ab/i.test(text)) {
                        available = true;
                        const m = text.match(/lieferung ab\s*([\d.]+)/i);
                        delivery = m ? '📅 Lieferung ab ' + m[1] : '📅 Lieferbar';
                    }
                    else if (/lieferung nach hause/i.test(text)) { available = true; delivery = '📦 Lieferung nach Hause'; }
                    else if (/sofort lieferbar/i.test(text)) { available = true; delivery = '⚡ Sofort lieferbar'; }

                    // Marketplace seller with delivery = usually available
                    if (/verkauf und versand durch/i.test(text) && available === null) {
                        available = true;
                    }

                    if (title) {
                        results.push({ title, price, link, available, delivery });
                    }
                });
                return results;
            }""")

            browser.close()

        results = []
        for p in products_js:
            title = p.get("title", "").strip()
            if not title or not _is_midea_product(title):
                continue
            price = _price_from_text(p.get("price", ""))
            link = p.get("link", "")
            available = p.get("available")
            delivery = p.get("delivery", "")

            results.append({
                "shop": "MediaMarkt",
                "title": title,
                "price": price,
                "currency": "€",
                "url": _clean_url(url, link),
                "in_stock": available,
                "delivery": delivery,
                "error": None,
            })

        if results:
            return results

    except Exception as e:
        logger.warning("MediaMarkt Playwright extraction failed: %s", e)

    # Fallback: JSON-LD (no availability data)
    body_text, html = _browser_fetch(url)
    if not html:
        html = _fetch(url)
    if html:
        jsonld_items = _extract_jsonld(html)
        for entry in jsonld_items:
            item_list = entry.get("itemListElement", []) if isinstance(entry, dict) and entry.get("@type") == "ItemList" else [entry]
            for elem in item_list:
                item = elem.get("item", elem) if isinstance(elem, dict) else elem
                if not isinstance(item, dict):
                    continue
                name = item.get("name", "")
                if not name or not _is_midea_product(name):
                    continue
                offers = item.get("offers", {})
                price_raw = offers.get("price", 0)
                price = float(price_raw) if price_raw else None
                link = item.get("url", "")
                results.append({
                    "shop": "MediaMarkt",
                    "title": name.strip(),
                    "price": price,
                    "currency": "€",
                    "url": _clean_url(url, link),
                    "in_stock": None,
                    "error": None,
                })

    if not results:
        results.append(_error("MediaMarkt", "Keine Midea PortaSplit Produkte gefunden", url))
    return results


# ---------------------------------------------------------------------------
# OBI (Playwright product page)
# ---------------------------------------------------------------------------

def scrape_obi(url: str, **kwargs) -> list[dict[str, Any]]:
    """OBI via the clean PDP availability API (HTTP, IP-robust).
    Location-aware: the configured city's postal code drives which pickup
    stores are returned. Delivery is location-independent."""
    config = kwargs.get("config", {}) or {}
    location = config.get("location", "")
    radius = config.get("local_radius_km", DEFAULT_RADIUS_KM)

    m = re.search(r"/p/(\d+)", url)
    if not m:
        return [_error("OBI", "Artikelnummer nicht aus URL lesbar", url)]
    article = m.group(1)

    geo = _geocode(location) if location else None
    postcode = (geo[2] if geo else None) or "04103"

    try:
        r = requests.get(
            f"https://www.obi.de/api/pdp/v1/availability/{article}",
            params={"postalCode": postcode, "quantity": 1},
            headers={**HEADERS, "Accept": "application/json"}, timeout=TIMEOUT,
        )
        data = r.json()
    except Exception as e:
        logger.warning("OBI API failed: %s", e)
        return [_error("OBI", f"OBI API Fehler: {e}", url)]

    pickups = data.get("pickupStores") or []
    delivery = data.get("deliveryDataPerSeller") or []
    prices = [p["price"] for p in pickups if isinstance(p.get("price"), (int, float))]
    ref_price = min(prices) if prices else None

    results: list[dict[str, Any]] = []
    if delivery and ref_price is not None:
        results.append({
            "shop": "OBI", "title": "Midea PortaSplit — Lieferung",
            "price": ref_price, "currency": "€", "url": url,
            "in_stock": True, "delivery": "📦 Lieferung möglich", "error": None,
        })
    for p in pickups:
        info = p.get("pickupStoreInfo", {}) or {}
        name = info.get("pickupStoreName") or info.get("city") or "Markt"
        qty = p.get("availableQuantity", 0) or 0
        dist = p.get("pickupDistance")
        results.append({
            "shop": "OBI", "title": f"Midea PortaSplit — {name}",
            "price": p.get("price"), "currency": "€", "url": url,
            "in_stock": qty > 0,
            "delivery": (f"🏪 {dist:.0f} km" if isinstance(dist, (int, float)) else "🏪 Abholung"),
            "error": None,
        })
    if not results:
        results.append({
            "shop": "OBI", "title": "Midea PortaSplit (nicht lieferbar / nicht im Markt)",
            "price": None, "currency": "€", "url": url, "in_stock": False, "error": None,
        })
    return results


# ---------------------------------------------------------------------------
# BAUHAUS (blocked)
# ---------------------------------------------------------------------------

def scrape_bauhaus(url: str, **kwargs) -> list[dict[str, Any]]:
    # BAUHAUS uses Akamai and usually blocks headless browsers entirely; attempt
    # anyway via the strong fetch and report a clear message if it fails.
    return _generic_browser_scrape(url, "BAUHAUS", **kwargs)


# ---------------------------------------------------------------------------
# eBay
# ---------------------------------------------------------------------------

def scrape_toom(url: str, **kwargs) -> list[dict[str, Any]]:
    """Toom via the clean per-market jsonview API (HTTP, IP-robust).
    Location-aware: checks the nearest Toom markets to the configured city
    (within radius), plus location-independent delivery."""
    config = kwargs.get("config", {}) or {}
    location = config.get("location", "")
    radius = config.get("local_radius_km", DEFAULT_RADIUS_KM)

    from urllib.parse import unquote
    page = unquote(_fetch(url) or "")
    pm = re.search(r'sap_artikelnummer"?\s*:\s*"?(\d{6,9})', page)
    if not pm:
        return [_error("Toom", "Produkt-ID nicht ermittelbar", url)]
    product_id = pm.group(1)

    geo = _geocode(location) if location else None
    try:
        mk = requests.get("https://api.toom.de/public/api/markets",
                          headers={**HEADERS, "Accept": "application/json"}, timeout=TIMEOUT)
        markets = mk.json()
        markets = markets if isinstance(markets, list) else markets.get("markets", [])
    except Exception as e:
        return [_error("Toom", f"Markt-API Fehler: {e}", url)]

    near = _nearest_markets(markets, geo, radius) if geo else []

    results: list[dict[str, Any]] = []
    deliver_added = False
    for m, dist in near:
        jv = _toom_jsonview(product_id, m["id"])
        if not jv:
            continue
        if not deliver_added:
            deliver_added = True
            dav, doff = _toom_block(jv.get("deliver"))
            if dav and doff is not None:
                results.append({
                    "shop": "Toom", "title": "Midea PortaSplit — Lieferung",
                    "price": doff, "currency": "€", "url": url,
                    "in_stock": True, "delivery": "📦 Lieferung möglich", "error": None,
                })
        rav, roff = _toom_block(jv.get("reserve"))
        results.append({
            "shop": "Toom", "title": f"Midea PortaSplit — {m['name']}",
            "price": roff, "currency": "€", "url": url,
            "in_stock": bool(rav), "delivery": f"🏪 {dist:.0f} km", "error": None,
        })

    if not near:
        return [_error("Toom",
            "Kein Standort gesetzt — bitte Stadt in den Einstellungen angeben.", url)]
    if not results:
        results.append({
            "shop": "Toom", "title": "Midea PortaSplit (keine Marktdaten)",
            "price": None, "currency": "€", "url": url, "in_stock": None, "error": None,
        })
    return results


# ---------------------------------------------------------------------------
# billiger.de
# ---------------------------------------------------------------------------

def scrape_billiger(url: str, **kwargs) -> list[dict[str, Any]]:
    html = _fetch(url)
    if not html:
        return [_error("billiger.de", "Seite nicht erreichbar", url)]

    tree = lhtml.fromstring(html)
    results = []
    for card in tree.cssselect(".tw-product"):
        link_els = card.cssselect("a[href]")
        if not link_els:
            continue
        a = link_els[0]
        title = (a.text_content() or "").strip()
        href = a.get("href", "")
        if not title:
            continue
        full_url = _clean_url(url, href)
        card_text = card.text_content()
        price = None
        m = re.search(r"(\d[\d\.,]*\d{2})\s*[€€]", card_text)
        if m:
            price = _price_from_text(m.group(1))
        results.append({
            "shop": "billiger.de",
            "title": title,
            "price": price,
            "currency": "€",
            "url": full_url,
            "in_stock": price is not None,
            "error": None,
        })

    if not results:
        results.append({"shop": "billiger.de", "title": "Midea PortaSplit (öffnen)", "price": None,
            "currency": "€", "url": url, "in_stock": None, "error": None})
    else:
        seen, clean = set(), []
        for r in results:
            t = r["title"]
            words = t.split()
            if len(words) >= 4 and words[:len(words)//2] == words[len(words)//2:]:
                t = " ".join(words[:len(words)//2])
            if t in ("Cool 2,35 kW", "3,5 kW"):
                t = f"Midea PortaSplit {t}"
            if t not in seen:
                seen.add(t); r["title"] = t; clean.append(r)
        results = clean
    return results


# ---------------------------------------------------------------------------
# Cyberport (blocked)
# ---------------------------------------------------------------------------

def scrape_cyberport(url: str, **kwargs) -> list[dict[str, Any]]:
    return _generic_browser_scrape(url, "Cyberport", **kwargs)


# ---------------------------------------------------------------------------
# Prosatech (Playwright product page)
# ---------------------------------------------------------------------------

def scrape_prosatech(url: str, **kwargs) -> list[dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = _launch_chromium(pw)
            if browser is None:
                raise RuntimeError("kein Browser (Chromium/Edge/Chrome) verfügbar")
            context = browser.new_context(locale="de-DE", viewport={"width": 1920, "height": 1080})
            context.add_init_script('Object.defineProperty(navigator, "webdriver", {get: () => undefined});')
            page = context.new_page()
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)

            title = page.title()
            body = page.inner_text("body")
            browser.close()

        price = None
        price_match = re.search(r"(\d[\d\.,]*\d{2})\s*[€€]", title)
        if price_match:
            price = _price_from_text(price_match.group(1))
        if not price:
            price_match = re.search(r"(\d[\d\.,]*\d{2})\s*[€€]", body)
            if price_match:
                price = _price_from_text(price_match.group(1))

        in_stock = "lieferbar" in body.lower() or "auf lager" in body.lower() or "sofort" in body.lower()
        no_stock = "nicht lieferbar" in body.lower() or "ausverkauft" in body.lower()
        
        # Extract delivery time
        delivery = ""
        dm = re.search(r"lieferzeit[:\s]*([^\n]+)", body, re.IGNORECASE)
        if dm:
            delivery = "⏱ " + dm.group(1).strip()

        return [{
            "shop": "Prosatech",
            "title": title.strip(),
            "price": price,
            "currency": "€",
            "url": url,
            "in_stock": True if in_stock else (False if no_stock else None),
            "delivery": delivery,
            "error": None,
        }]
    except Exception as e:
        logger.warning("Prosatech scrape failed: %s", e)

    return [_error("Prosatech",
        "Prosatech blockiert Anfragen. Bitte im Browser öffnen.", url)]


# ---------------------------------------------------------------------------
# Euronics (blocked)
# ---------------------------------------------------------------------------

def scrape_euronics(url: str, **kwargs) -> list[dict[str, Any]]:
    return _generic_browser_scrape(url, "Euronics", **kwargs)


# ---------------------------------------------------------------------------
# Hornbach (blocked)
# ---------------------------------------------------------------------------

def scrape_hornbach(url: str, **kwargs) -> list[dict[str, Any]]:
    """Hornbach renders fine with the stealth browser. It shows a price even when
    sold out, so we gate on real availability: delivery ("Bequem liefern lassen"
    without "NICHT ONLINE BESTELLBAR") and the nearest market's reservation status.
    The market is geo-assigned by the server to the machine's location."""
    body, html = _browser_fetch(url)
    if not body or len(body) < 400 or any(c in body for c in _CHALLENGE_MARKERS):
        return [_error("Hornbach", "Hornbach blockiert / nicht erreichbar", url)]

    U = body.upper()
    # The buybox must have actually rendered, otherwise we can't judge availability.
    buybox_rendered = "BEQUEM LIEFERN LASSEN" in U or "RESERVIER" in U
    if not buybox_rendered:
        return [_error("Hornbach", "Hornbach nicht vollständig geladen / blockiert", url)]

    price = _structured_price(html, body)
    if price is None:
        m = re.search(r"Preis\s*[—–-]\s*([\d.]+,\d{2})\s*€", body)
        if m:
            price = _price_from_text(m.group(1))

    results: list[dict[str, Any]] = []
    if "BEQUEM LIEFERN LASSEN" in U and "NICHT ONLINE BESTELLBAR" not in U:
        results.append({
            "shop": "Hornbach", "title": "Midea PortaSplit — Lieferung",
            "price": price, "currency": "€", "url": url,
            "in_stock": True, "delivery": "📦 Lieferung möglich", "error": None,
        })
    # Market name sits right before the reservation status line.
    mk = re.search(r"HORNBACH\s+([A-ZÄÖÜ][\wäöüß .\-]{2,28}?)\s+Z\.ZT\.\s+(?:NICHT\s+)?RESERVIER", body)
    if not mk:
        mk = re.search(r"HORNBACH\s+([A-ZÄÖÜ][\wäöüß .\-]{2,28}?)\s+RESERVIER", body)
    if mk:  # only emit a pickup row when we actually found the market block
        market_name = mk.group(1).strip()
        pickup_unavail = ("NICHT RESERVIERBAR" in U) or ("NICHT IM MARKT" in U)
        results.append({
            "shop": "Hornbach", "title": f"Midea PortaSplit — {market_name}",
            "price": price, "currency": "€", "url": url,
            "in_stock": (not pickup_unavail), "delivery": "🏪 Abholung", "error": None,
        })
    if not results:
        results.append(_error("Hornbach", "Hornbach: Markt-/Lieferstatus nicht lesbar", url))
    return results


# ---------------------------------------------------------------------------
# Joybuy (blocked)
# ---------------------------------------------------------------------------

def scrape_joybuy(url: str, **kwargs) -> list[dict[str, Any]]:
    return _generic_browser_scrape(url, "Joybuy", **kwargs)


# ---------------------------------------------------------------------------
# Alternate (Playwright product page)
# ---------------------------------------------------------------------------

def scrape_alternate(url: str, **kwargs) -> list[dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = _launch_chromium(pw)
            if browser is None:
                raise RuntimeError("kein Browser (Chromium/Edge/Chrome) verfügbar")
            context = browser.new_context(locale="de-DE", viewport={"width": 1920, "height": 1080})
            context.add_init_script('Object.defineProperty(navigator, "webdriver", {get: () => undefined});')
            page = context.new_page()
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)

            title = page.title()
            body = page.inner_text("body")

            # Extract price from page
            price = None
            price_match = re.search(r"(\d[\d\.,]*\d{2})\s*[€€]", title)
            if price_match:
                price = _price_from_text(price_match.group(1))
            if not price:
                price_match = re.search(r"(\d[\d\.,]*\d{2})\s*[€€]", body)
                if price_match:
                    price = _price_from_text(price_match.group(1))

            in_stock = "lieferbar" in body.lower() or "auf lager" in body.lower()
            no_stock = "nicht lieferbar" in body.lower() or "ausverkauft" in body.lower()

            browser.close()

        return [{
            "shop": "Alternate",
            "title": title.strip(),
            "price": price,
            "currency": "€",
            "url": url,
            "in_stock": True if in_stock else (False if no_stock else None),
            "error": None,
        }]
    except Exception as e:
        logger.warning("Alternate scrape failed: %s", e)

    return [_error("Alternate",
        "Alternate blockiert Anfragen. Bitte im Browser öffnen.", url)]


# ---------------------------------------------------------------------------
# Expert (Playwright product page)
# ---------------------------------------------------------------------------

def scrape_expert(url: str, **kwargs) -> list[dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = _launch_chromium(pw)
            if browser is None:
                raise RuntimeError("kein Browser (Chromium/Edge/Chrome) verfügbar")
            context = browser.new_context(locale="de-DE", viewport={"width": 1920, "height": 1080})
            context.add_init_script('Object.defineProperty(navigator, "webdriver", {get: () => undefined});')
            page = context.new_page()
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(8000)

            title = page.title()
            body = page.inner_text("body")

            price = None
            price_match = re.search(r"(\d[\d\.,]*\d{2})\s*[€€]", title)
            if price_match:
                price = _price_from_text(price_match.group(1))
            if not price:
                price_match = re.search(r"(\d[\d\.,]*\d{2})\s*[€€]", body)
                if price_match:
                    price = _price_from_text(price_match.group(1))

            in_stock = "lieferbar" in body.lower() or "auf lager" in body.lower()
            no_stock = "nicht lieferbar" in body.lower() or "ausverkauft" in body.lower()

            browser.close()

        if price:
            return [{
                "shop": "Expert",
                "title": title.strip(),
                "price": price,
                "currency": "€",
                "url": url,
                "in_stock": True if in_stock else (False if no_stock else None),
                "error": None,
            }]
    except Exception as e:
        logger.warning("Expert scrape failed: %s", e)

    return [_error("Expert",
        "Expert blockiert Anfragen. Bitte im Browser öffnen.", url)]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

SCRAPER_REGISTRY: dict[str, callable] = {
    "amazon": scrape_amazon,
    "mediamarkt": scrape_mediamarkt,
    "obi": scrape_obi,
    "bauhaus": scrape_bauhaus,
    "billiger": scrape_billiger,
    "prosatech": scrape_prosatech,
    "euronics": scrape_euronics,
    "toom": scrape_toom,
    "hornbach": scrape_hornbach,
    "joybuy": scrape_joybuy,
    "alternate": scrape_alternate,
    "expert": scrape_expert,
}


def scrape_shop(shop_key: str, url: str, **kwargs) -> list[dict[str, Any]]:
    scraper = SCRAPER_REGISTRY.get(shop_key)
    if not scraper:
        return [_error(shop_key, f"Kein Scraper für {shop_key}", url)]
    try:
        return scraper(url, **kwargs)
    except Exception as e:
        logger.exception("Scraper %s failed", shop_key)
        return [_error(shop_key, f"Fehler: {e}", url)]


def scrape_all(config: dict) -> dict[str, list[dict[str, Any]]]:
    """Scrape all active shops sequentially."""
    results = {}
    shops = config.get("shops", {})
    for key, shop_info in shops.items():
        if not shop_info.get("active", True):
            continue
        url = shop_info["url"]
        logger.info("Scraping %s …", shop_info["name"])
        results[key] = scrape_shop(key, url, config=config)
    return results


def scrape_all_parallel(config: dict, max_workers: int = 5) -> dict[str, list[dict[str, Any]]]:
    """Scrape all active shops in parallel using threads."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    shops = config.get("shops", {})
    active = {k: v for k, v in shops.items() if v.get("active", True)}
    results: dict[str, list[dict[str, Any]]] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for key, info in active.items():
            url = info["url"]
            logger.info("Scraping %s … (parallel)", info["name"])
            futures[pool.submit(scrape_shop, key, url, config=config)] = key

        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                logger.error("Parallel scrape %s failed: %s", key, e)
                results[key] = [_error(key, f"Fehler: {e}", active[key]["url"])]

    return results

def _error(shop: str, msg: str, url: str) -> dict[str, Any]:
    return {
        "shop": shop,
        "title": f"⚠ {msg}",
        "price": None,
        "currency": "€",
        "url": url,
        "in_stock": None,
        "error": msg,
    }

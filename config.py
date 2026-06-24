"""Configuration management for Midea PortaSplit Preis-Monitor."""

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "location": "Leipzig",
    "local_radius_km": 100,
    "price_range": {"min": 600, "max": 1800},
    "check_interval_minutes": 30,
    "notify_on_deal": True,
    "tray_mode": True,
    "products": [
        {"key": "portasplit_35kw", "name": "Midea PortaSplit 3.5 kW (heizen + kühlen)", "keywords": ["midea portasplit 3.5"], "active": True},
        {"key": "portasplit_cool", "name": "Midea PortaSplit Cool 2.35 kW (nur kühlen)", "keywords": ["midea portasplit cool"], "active": True},
        {"key": "portasplit_e", "name": "Midea PortaSplit-E (Mobile Klimaanlage)", "keywords": ["midea portasplit-e"], "active": True},
    ],
    "shops": {
        "amazon": {"name": "Amazon.de", "url": "https://www.amazon.de/dp/B0GX16LKSC", "active": True, "local": False, "product_page": True},
        "mediamarkt": {"name": "MediaMarkt", "url": "https://www.mediamarkt.de/de/search.html?query=midea+portasplit", "active": True, "local": False, "product_page": False},
        "obi": {"name": "OBI", "url": "https://www.obi.de/p/8620890/midea-mobile-split-klimaanlage-portasplit", "active": True, "local": True, "product_page": True},
        "prosatech": {"name": "Prosatech", "url": "https://prosatech.de/Mobile-Klimaanlage-Midea-PortaSplit-35kw", "active": True, "local": False, "product_page": True},
        "bauhaus": {"name": "BAUHAUS", "url": "https://www.bauhaus.info/klimaanlagen/midea-klimasplitgeraet-portasplit-12000-btu/p/31934233", "active": True, "local": True, "product_page": True},
        "euronics": {"name": "Euronics", "url": "https://www.euronics.de/haus-und-haushalt/heizen-lueften-kuehlen/kuehlen/split-klimageraete/porta-split-split-klimageraet-a-4065327878899", "active": True, "local": False, "product_page": True},
        "toom": {"name": "Toom", "url": "https://www.toom.de/p/mobiles-klimageraet-portasplit-12000-btuh/9350668", "active": True, "local": True, "product_page": True},
        "hornbach": {"name": "Hornbach", "url": "https://www.hornbach.de/p/klimasplitgeraet-midea-portasplit-12-000-btu-105-m-weiss/12356554/", "active": True, "local": True, "product_page": True},
        "joybuy": {"name": "Joybuy (JD International)", "url": "https://www.joybuy.de/dp/100615597?siteCode=DE-Site", "active": True, "local": False, "product_page": True},
        "alternate": {"name": "Alternate", "url": "https://www.alternate.de/Midea/PortaSplit-Klimager%C3%A4t/html/product/100144936?sug=midea%20p", "active": True, "local": False, "product_page": True},
        "expert": {"name": "Expert", "url": "https://www.expert.de/shop/unsere-produkte/haushalt-kuche/wohnklima/klimagerate/32750011559-portasplit-mobile-split-klimaanlage.html", "active": True, "local": False, "product_page": True},
    },
}


def load_config() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        saved = {}
    merged = _deep_merge(DEFAULT_CONFIG, saved)
    return merged


def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _deep_merge(base: dict, overrides: dict) -> dict:
    result = dict(base)
    for k, v in overrides.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result

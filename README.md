# Midea PortaSplit Preis-Monitor

Desktop-App zum Verfolgen von Midea PortaSplit Preisen auf mehreren
deutschen Online-Shops. Mit Deal-Benachrichtigungen.

## Features

- 🔍 **Preissuche** in 8 deutschen Shops (Amazon, MediaMarkt, OBI, BAUHAUS, eBay, idealo, Geizhals, billiger.de)
- ⚙ **Einstellungen** für Preisspanne, Shop-Auswahl und Produktvarianten
- 🔔 **Desktop-Benachrichtigungen** bei neuen Schnäppchen
- ⏱ **Auto-Scan** in einstellbarem Intervall
- 📊 **Ergebnis-Tabelle** mit Preisen, Verfügbarkeit und Direktlinks
- 💻 **Standalone .exe** — kein Python nötig

## Installation (für Entwickler)

```bash
cd PortaSplitMonitor
pip install -r requirements.txt
python main.py
```

## Build ( .exe )

Einfach `build.bat` doppelklicken. Die .exe liegt dann im `dist/` Ordner.

## Konfiguration

Die `config.json` im Projektordner wird beim ersten Start automatisch angelegt.
Über das Einstellungs-Menü in der App kannst du bequem anpassen:

- **Preisspanne** – Min/Max-Preis für Benachrichtigungen
- **Produktvarianten** – Welche Midea Modelle tracked werden
- **Shops** – Welche Shops durchsucht werden
- **Scan-Intervall** – Wie oft automatisch gescannt wird

## Verfügbare Shops

| Shop | Online-Lieferung | Status | Preisbeispiel |
|------|:-:|--------|---:|
| **Amazon.de** | ✅ | ✅ **Playwright** — Midea-Produkte erfasst | ~80–96 € (Zubehör) |
| **MediaMarkt** | ✅ | ✅ **Playwright + JSON-LD** | **749 €** (Cool) / **2.618 €** |
| OBI | ✅ | ❌ Keine Midea-Produkte gefunden | - |
| BAUHAUS | ✅ | ❌ Blockiert | - |
| eBay.de | ✅ | ❌ Blockiert | - |
| idealo.de | - | ⚠️ Vergleichsportal (Cloudflare) | - |
| Geizhals | - | ❌ Blockiert | - |
| **billiger.de** | **-** | **✅ requests + lxml** — echte Preise! | **1.386 €** (Cool) / **2.000 €** (3.5kW) |
| Cyberport | ✅ | ❌ Blockiert | - |
| Prosatech | ✅ | ❌ JS-gerendert | - |
| Euronics | ✅ | ❌ Blockiert (403) | - |
| Toom | ✅ (Online) | ❌ Blockiert | - |
| Hornbach | ✅ (Online) | ❌ Blockiert | - |
| Joybuy | ✅ | ❌ Risk Control | - |

> 💡 **3 Shops mit echten Preisen:** MediaMarkt (Playwright), Amazon (Playwright), billiger.de (requests)
> Die restlichen Shops sind als anklickbare Links in der Tabelle verfügbar.
## Produktvarianten

- Midea PortaSplit 3.5 kW (heizen + kühlen)
- Midea PortaSplit Cool 2.35 kW (nur kühlen)
- Midea PortaSplit-E (Mobile Klimaanlage)

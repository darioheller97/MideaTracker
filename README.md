# Midea PortaSplit Preis-Monitor

Desktop-App (Windows) zum Verfolgen von **Midea PortaSplit** Preisen und
Verfügbarkeiten über mehrere deutsche Shops — mit Tray-Modus und
Desktop-Benachrichtigungen bei Schnäppchen.

## Features

- 🔍 **Preis- & Verfügbarkeitssuche** über mehrere Shops, parallel
- 📍 **Standortbezogen** — OBI & Toom prüfen die nächstgelegenen Filialen im
  einstellbaren Umkreis deiner Stadt (Lieferung wird ortsunabhängig erfasst)
- 🌐 **Browser-Shops ohne Extra-Download** — nutzt einen bereits installierten
  Browser (Playwright-Chromium, sonst **Microsoft Edge** bzw. Chrome). Edge ist
  auf jedem Windows 10/11 vorinstalliert, es muss also nichts heruntergeladen werden.
- 🔔 **Desktop-Benachrichtigungen** bei neuen/günstigeren Angeboten
- ⏱ **Auto-Scan** in einstellbarem Intervall, **Tray-Modus**
- 💻 **Standalone .exe** — kein Python nötig

## Schnellstart (.exe)

1. Die `MideaPortaSplitMonitor.exe` aus den [Releases](../../releases) herunterladen.
2. Doppelklick — fertig. (Windows SmartScreen ggf. „Trotzdem ausführen“.)

Die App läuft auf jedem Windows-PC; für die JS-basierten Shops wird ein
installierter Browser (Edge/Chrome/Chromium) verwendet.

## Für Entwickler

```bash
pip install -r requirements.txt
python -m playwright install chromium   # optional; sonst wird Edge/Chrome genutzt
python main.py
```

## Eigene .exe bauen

`build.bat` doppelklicken (nutzt PyInstaller). Ergebnis liegt unter `dist/`.

## Konfiguration

`config.json` (bzw. das Einstellungs-Menü in der App):

- **Standort** & **Umkreis (km)** — für Filial-Shops (OBI, Toom)
- **Preisspanne** — Min/Max für Benachrichtigungen
- **Produktvarianten** — welche Midea-Modelle getrackt werden
- **Shops** & **Scan-Intervall**

## Shops & Methode

| Shop | Methode | Hinweis |
|------|---------|---------|
| OBI | JSON-API (HTTP) | Standortbezogen: Lieferung + Filialen im Umkreis |
| Toom | JSON-API (HTTP) | Standortbezogen: nächste Märkte im Umkreis |
| billiger.de | HTTP | Preisvergleich |
| Prosatech | Browser/HTTP | Online-Lieferung |
| Amazon.de | Browser | Buy-Box-Preis |
| Euronics | Browser | Online-Lieferung |
| Hornbach | Browser | Lieferung + lokaler Markt |
| MediaMarkt | Browser | Suche + Verfügbarkeit |
| Alternate / Expert | Browser | Online-Lieferung |
| Cyberport / Joybuy | Browser (best-effort) | starker Bot-Schutz, oft blockiert |
| BAUHAUS | — | Akamai blockiert Headless-Browser vollständig |

> Hinweis: Manche Shops setzen Bot-Schutz ein. Schlägt das Laden fehl, zeigt die
> Tabelle einen Hinweis + Direktlink statt eines Preises (es gibt keine
> Falschmeldungen). Ergebnisse können je nach Shop/Standort variieren.

## Produktvarianten

- Midea PortaSplit 3,5 kW (heizen + kühlen)
- Midea PortaSplit Cool 2,35 kW (nur kühlen)
- Midea PortaSplit-E (Mobile Klimaanlage)

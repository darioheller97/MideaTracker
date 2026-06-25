# Midea PortaSplit Preis-Monitor

Verfolge **Midea PortaSplit** Preise und Verfügbarkeiten über mehrere deutsche Shops —
mit Benachrichtigungen, sobald ein Angebot deinem Budget entspricht.

Verfügbar als **Web-App** (kein Install, läuft auf dem Handy) und als **Windows-Desktop-App**.

---

## 🌐 Web-App — jetzt live

**https://midea.icetea.me**

- Öffne die Seite, gib deine Stadt und dein Budget ein → du erhältst einen **privaten Link** (kein Account nötig).
- Speicher den Link als Lesezeichen oder installiere die Seite als **PWA** (Teilen → „Zum Home-Bildschirm").
- Aktiviere **Push-Benachrichtigungen** → dein Handy klingelt, sobald ein passendes Angebot auftaucht.
- Der Server scannt alle Shops alle **5 Minuten** im Hintergrund — auch wenn dein Browser geschlossen ist.
- Du kannst das Scan-Intervall über die Einstellungen auf deiner Watch-Seite anpassen.

> **iPhone:** Seite erst über Teilen → „Zum Home-Bildschirm" hinzufügen und *von dort* öffnen — erst dann unterstützt iOS Web Push (ab iOS 16.4).

### Wie es funktioniert

```
Browser öffnet midea.icetea.me
    → Stadt + Budget eingeben
    → Privater Link /w/<token>
    → Benachrichtigungen aktivieren
Server scannt alle 5 Min alle Shops
    → Neues Angebot in Budget? → Push-Notification + Sound + Popup
```

---

## 💻 Desktop-App (Windows)

Standalone `.exe` mit Tray-Modus und Desktop-Benachrichtigungen.

### Features

- 🔍 **Preis- & Verfügbarkeitssuche** über mehrere Shops, parallel
- 📍 **Standortbezogen** — OBI & Toom prüfen die nächstgelegenen Filialen im
  einstellbaren Umkreis deiner Stadt (Lieferung wird ortsunabhängig erfasst)
- 🌐 **Browser-Shops ohne Extra-Download** — nutzt installierten Browser
  (Edge ist auf jedem Windows 10/11 vorinstalliert, nichts muss heruntergeladen werden)
- 🔔 **Desktop-Benachrichtigungen** bei neuen/günstigeren Angeboten
- ⏱ **Auto-Scan** in einstellbarem Intervall, **Tray-Modus**
- 💻 **Standalone .exe** — kein Python nötig

### Schnellstart (.exe)

1. Die `MideaPortaSplitMonitor.exe` aus den [Releases](../../releases) herunterladen.
2. Doppelklick — fertig. (Windows SmartScreen ggf. „Trotzdem ausführen".)

### Für Entwickler

```bash
pip install -r requirements.txt
python -m playwright install chromium   # optional; sonst wird Edge/Chrome genutzt
python main.py
```

### Eigene .exe bauen

`build.bat` doppelklicken (nutzt PyInstaller). Ergebnis liegt unter `dist/`.

---

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

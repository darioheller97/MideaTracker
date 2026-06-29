"""Midea PortaSplit Preis-Monitor — Main Window & Entry Point."""

import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from version import __version__

from PyQt5.QtCore import QTimer, Qt, QThread, pyqtSignal, QUrl
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QDesktopServices
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QStatusBar,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import config as cfgmod
import notifications
import scrapers
import uploader
from settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)

# Hide the console windows that subprocesses (Playwright's driver/browser,
# PowerShell, …) would otherwise flash in a windowed (no-console) build.
if sys.platform == "win32":
    import subprocess as _subprocess
    _CREATE_NO_WINDOW = 0x08000000
    _orig_popen_init = _subprocess.Popen.__init__

    def _popen_no_window(self, *args, **kwargs):
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | _CREATE_NO_WINDOW
        _orig_popen_init(self, *args, **kwargs)

    _subprocess.Popen.__init__ = _popen_no_window


GITHUB_REPO = "darioheller97/MideaTracker"


def _version_gt(a: str, b: str) -> bool:
    try:
        return tuple(int(x) for x in a.split(".")) > tuple(int(x) for x in b.split("."))
    except Exception:
        return False


class UpdateChecker(QThread):
    """Silently checks GitHub for a newer release on startup."""
    update_found = pyqtSignal(str, str)  # (latest_version, download_url)

    def run(self):
        if not getattr(sys, "frozen", False):
            return  # skip in dev / source mode
        try:
            import requests as req
            r = req.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=10,
            )
            data = r.json()
            latest = data.get("tag_name", "").lstrip("v")
            if latest and _version_gt(latest, __version__):
                url = next(
                    (a["browser_download_url"] for a in data.get("assets", [])
                     if a["name"].endswith(".exe")),
                    None,
                )
                if url:
                    self.update_found.emit(latest, url)
        except Exception:
            pass


class UpdateDownloader(QThread):
    """Downloads the new exe in the background and reports progress."""
    progress = pyqtSignal(int, int)   # bytes_done, total_bytes
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, url: str, dest: Path):
        super().__init__()
        self._url = url
        self._dest = dest

    def run(self):
        try:
            import requests as req
            with req.get(self._url, stream=True, timeout=120) as r:
                total = int(r.headers.get("content-length", 0))
                done = 0
                with open(self._dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            done += len(chunk)
                            self.progress.emit(done, total)
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))


class ScanWorker(QThread):
    """Runs the shop scrapers in a background thread and emits each shop's
    results as it completes, so the UI can fill in incrementally."""

    shop_done = pyqtSignal(str, list)   # shop_key, items
    finished_all = pyqtSignal()

    def __init__(self, config: dict):
        super().__init__()
        self._config = config

    def run(self):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        shops = {k: v for k, v in self._config.get("shops", {}).items()
                 if v.get("active", True)}
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(scrapers.scrape_shop, k, v["url"], config=self._config): k
                       for k, v in shops.items()}
            for fut in as_completed(futures):
                k = futures[fut]
                try:
                    items = fut.result()
                except Exception as e:
                    items = [scrapers._error(k, f"Fehler: {e}", shops[k]["url"])]
                self.shop_done.emit(k, items)
        self.finished_all.emit()

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "last_prices.json"


def _fmt_price(p: float | None) -> str:
    if p is None:
        return "—"
    return f"{p:.2f} €"


def _date_ts() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M")


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Midea PortaSplit Preis-Monitor v{__version__}")
        self.setMinimumSize(750, 500)

        self._config: dict = cfgmod.load_config()
        self._last_prices: dict[str, float] = self._load_last_prices()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_auto_scan)
        self._tray = None

        self._build_ui()
        self._build_tray()
        self._apply_config()
        self._update_status('Bereit — Klicke auf "Jetzt Scannen"')
        self._start_timer()

        # Check for updates silently in background (only in packaged .exe)
        self._update_checker = UpdateChecker()
        self._update_checker.update_found.connect(self._on_update_found)
        self._update_checker.start()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        header = QLabel("❄️ Midea PortaSplit — Preisvergleich")
        hf = QFont()
        hf.setPointSize(14)
        hf.setBold(True)
        header.setFont(hf)
        layout.addWidget(header)

        toolbar = QHBoxLayout()
        self._btn_scan = QPushButton("🔍 Jetzt scannen")
        self._btn_scan.clicked.connect(self._on_scan)
        self._btn_settings = QPushButton("⚙ Einstellungen")
        self._btn_settings.clicked.connect(self._on_settings)
        self._lbl_auto = QLabel("⏱ Auto-Scan aktiv")
        self._lbl_auto.setStyleSheet("color: #2e7d32; font-weight: bold;")

        toolbar.addWidget(self._btn_scan)
        toolbar.addStretch()
        toolbar.addWidget(self._lbl_auto)
        toolbar.addWidget(self._btn_settings)
        layout.addLayout(toolbar)

        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(["Shop", "Produkt", "Preis", "Status", "Lieferzeit", "Link"])
        header = self._table.horizontalHeader()
        header.setStretchLastSection(True)
        # Resizable columns: Interactive lets the user drag column widths.
        header.setSectionResizeMode(QHeaderView.Interactive)
        # Set sensible default widths; columns are fully draggable.
        self._table.setColumnWidth(0, 180)   # Shop
        self._table.setColumnWidth(1, 260)   # Produkt
        self._table.setColumnWidth(2, 90)    # Preis (narrow)
        self._table.setColumnWidth(3, 140)   # Status
        self._table.setColumnWidth(4, 140)   # Lieferzeit
        # Link column stretches to fill remaining space.
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        layout.addWidget(self._table)

        self._lbl_summary = QLabel("")
        layout.addWidget(self._lbl_summary)

        self._status = QStatusBar()
        self.setStatusBar(self._status)

    def _build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(self)
        self._set_tray_icon("neutral")
        self._tray.setToolTip("Midea PortaSplit Preis-Monitor")

        menu = QMenu()
        show_action = menu.addAction("🗗 Fenster anzeigen")
        show_action.triggered.connect(self.showNormal)
        scan_action = menu.addAction("🔍 Jetzt scannen")
        scan_action.triggered.connect(self._on_scan)
        menu.addSeparator()
        quit_action = menu.addAction("✕ Beenden")
        quit_action.triggered.connect(QApplication.quit)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _set_tray_icon(self, status: str):
        """Create a colored tray icon: green if available, gray otherwise."""
        size = 32
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        if status == "available":
            p.setBrush(QColor("#2e7d32"))  # green
        else:
            p.setBrush(QColor("#757575"))  # gray
        p.setPen(Qt.NoPen)
        p.drawEllipse(2, 2, size - 4, size - 4)
        p.end()
        self._tray.setIcon(QIcon(pix))

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.showNormal()
            self.raise_()

    def _on_cell_double_clicked(self, row: int, col: int):
        """Open the shop URL in the default browser when the Link cell is double-clicked."""
        if col != 5:
            return
        item = self._table.item(row, 5)
        if not item:
            return
        url = item.toolTip()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    # ------------------------------------------------------------------
    # Config & Timer
    # ------------------------------------------------------------------

    def _apply_config(self):
        self._config = cfgmod.load_config()
        interval = self._config.get("check_interval_minutes", 30)
        self._timer.setInterval(interval * 60 * 1000)

    def _start_timer(self):
        interval = self._config.get("check_interval_minutes", 30)
        if interval > 0:
            self._timer.start(interval * 60 * 1000)
            self._lbl_auto.setText(f"⏱ Auto-Scan: alle {interval} Min")
            self._lbl_auto.setStyleSheet("color: #2e7d32; font-weight: bold;")
        else:
            self._timer.stop()
            self._lbl_auto.setText("⏸ Auto-Scan aus")
            self._lbl_auto.setStyleSheet("color: #888;")

    # ------------------------------------------------------------------
    # Scan (parallel)
    # ------------------------------------------------------------------

    def _on_scan(self):
        if getattr(self, "_worker", None) is not None and self._worker.isRunning():
            return
        self._btn_scan.setEnabled(False)
        self._btn_scan.setText("🔍 Scanne …")
        self._table.setRowCount(0)
        self._scan_results = {}
        self._best_price = None
        self._best_shop = ""
        self._best_title = ""
        self._scan_total = sum(1 for v in self._config.get("shops", {}).values()
                               if v.get("active", True))
        self._scan_done = 0
        self._update_status(f"Scanne Shops … (0/{self._scan_total})")

        self._worker = ScanWorker(self._config)
        self._worker.shop_done.connect(self._on_shop_done)
        self._worker.finished_all.connect(self._on_scan_finished)
        self._worker.start()

    def _on_shop_done(self, shop_key: str, items: list):
        """A shop finished — append its rows immediately (incremental)."""
        self._scan_results[shop_key] = items
        self._scan_done += 1
        rows = self._flatten({shop_key: items})
        self._append_rows(rows)
        self._update_status(f"Scanne Shops … ({self._scan_done}/{self._scan_total})")

    def _on_scan_finished(self):
        # Re-render grouped/sorted for a tidy final layout, then notify.
        self._display_results(self._scan_results)
        self._check_deals(self._scan_results)
        self._btn_scan.setEnabled(True)
        self._btn_scan.setText("🔍 Jetzt scannen")
        self._upload_results_async()

    def _upload_results_async(self):
        """Share this residential-IP scan's online-shop results with the web app
        (so phone users see the bot-protected shops). Fire-and-forget; no-op unless
        upload.json / env vars are configured. Runs off the GUI thread."""
        import copy
        import threading
        results = copy.deepcopy(self._scan_results)
        shops_cfg = self._config.get("shops", {})
        threading.Thread(target=uploader.upload_results,
                         args=(results, shops_cfg), daemon=True).start()

    def _on_auto_scan(self):
        logger.info("Auto-scan triggered")
        self._on_scan()

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def _flatten(self, results: dict[str, list[dict[str, Any]]]) -> list[dict]:
        """Apply product/price filters and return display row-dicts."""
        location = self._config.get("location", "")
        active_kws = []
        for prod in self._config.get("products", []):
            if prod.get("active", True):
                for kw in prod.get("keywords", []):
                    active_kws.append(kw.lower().replace(".", "[.,]"))

        def _matches_product(title: str) -> bool:
            if not active_kws:
                return True
            return any(re.search(kw, title.lower()) for kw in active_kws)

        pr = self._config.get("price_range", {})
        pmin, pmax = pr.get("min", 0), pr.get("max", 99999)

        flat = []
        for shop_key, items in results.items():
            for item in items:
                title = item.get("title", "")
                price = item.get("price")
                has_error = bool(item.get("error"))
                shop_info = self._config.get("shops", {}).get(shop_key, {})
                is_product_page = shop_info.get("product_page", False)
                # Keyword filter only for search-type shops; trust product pages.
                if not has_error:
                    if not is_product_page and not _matches_product(title):
                        continue
                    if price is not None and price > 0:
                        if price < pmin or price > pmax:
                            continue
                shop_name = item.get("shop", shop_key)
                if shop_info.get("local") and location:
                    shop_name = f"{shop_name} {location}"
                in_stock = item.get("in_stock")
                flat.append({
                    "shop_name": shop_name,
                    "title": title,
                    "price": price,
                    "in_stock": in_stock,
                    "error": item.get("error"),
                    "delivery": item.get("delivery", ""),
                    "url": item.get("url", ""),
                    "sort_group": 0 if in_stock is True else (1 if in_stock is False else 2),
                    "sort_price": price if price is not None else float("inf"),
                })
        return flat

    def _render_row(self, it: dict):
        """Append one result row to the table; track the best price."""
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(it["shop_name"]))
        title_item = QTableWidgetItem(it["title"])
        if it.get("error"):
            title_item.setForeground(QColor("#e65100"))
        self._table.setItem(row, 1, title_item)
        price_item = QTableWidgetItem(_fmt_price(it["price"]))
        if it["price"] is not None and it["price"] > 0:
            price_item.setForeground(QColor("#1b5e20"))
            price_item.setFont(QFont("", -1, QFont.Bold))
        self._table.setItem(row, 2, price_item)
        if it["in_stock"] is True:
            status_text = "✅ Lieferbar"
        elif it["in_stock"] is False:
            status_text = "❌ Nicht verfügbar"
        elif it.get("error"):
            status_text = it["error"]
        else:
            status_text = "❓ Unbekannt"
        status_item = QTableWidgetItem(status_text)
        if it["in_stock"] is False or it.get("error"):
            status_item.setForeground(QColor("#c62828"))
        elif it["in_stock"] is True:
            status_item.setForeground(QColor("#1b5e20"))
        self._table.setItem(row, 3, status_item)
        self._table.setItem(row, 4, QTableWidgetItem(it.get("delivery", "")))
        url = it.get("url", "")
        link_item = QTableWidgetItem("🔗 Öffnen")
        link_item.setToolTip(url)
        link_item.setForeground(QColor("#1565C0"))
        self._table.setItem(row, 5, link_item)

        if it["price"] is not None and it["price"] > 0 and it["in_stock"] is not False:
            if self._best_price is None or it["price"] < self._best_price:
                self._best_price = it["price"]
                self._best_shop = it["shop_name"]
                self._best_title = it["title"]

    def _append_rows(self, flat: list):
        for it in flat:
            self._render_row(it)
        self._refresh_summary()

    def _refresh_summary(self, total: int | None = None):
        label = (f"{total} Shops durchsucht" if total is not None
                 else f"{self._scan_done}/{self._scan_total} Shops")
        parts = [label]
        if self._best_price is not None:
            parts.append(f"🏆 Günstigster: {self._best_price:.2f} € bei {self._best_shop}")
            if self._best_title:
                parts.append(f"({self._best_title})")
        self._lbl_summary.setText(" — ".join(parts))

    def _display_results(self, results: dict[str, list[dict[str, Any]]]):
        flat = self._flatten(results)
        flat.sort(key=lambda x: (x["sort_group"], x["sort_price"]))
        self._table.setRowCount(0)
        self._best_price = None
        self._best_shop = ""
        self._best_title = ""
        current_group = -1
        for it in flat:
            if it["sort_group"] != current_group:
                current_group = it["sort_group"]
                headers = {0: "🟢 Verfügbare Produkte", 1: "🔴 Nicht verfügbar", 2: "⚫ Unbekannt / Blockiert"}
                hr = self._table.rowCount()
                self._table.insertRow(hr)
                h_item = QTableWidgetItem(headers[current_group])
                h_item.setBackground(QColor("#f0f0f0"))
                hf = QFont(); hf.setBold(True); hf.setPointSize(10)
                h_item.setFont(hf)
                h_item.setFlags(Qt.ItemIsEnabled)
                self._table.setItem(hr, 0, h_item)
                for c in range(1, 6):
                    filler = QTableWidgetItem("")
                    filler.setBackground(QColor("#f0f0f0"))
                    filler.setFlags(Qt.ItemIsEnabled)
                    self._table.setItem(hr, c, filler)
            self._render_row(it)
        has_available = any(it["in_stock"] is True for it in flat)
        if self._tray:
            self._set_tray_icon("available" if has_available else "neutral")
        self._refresh_summary(total=len(results))
        self._update_status(f"✅ Scan abgeschlossen um {_date_ts()}")

    # ------------------------------------------------------------------
    # Deal detection
    # ------------------------------------------------------------------

    def _check_deals(self, results: dict[str, list[dict[str, Any]]]):
        pr = self._config.get("price_range", {})
        pmin = pr.get("min", 0)
        pmax = pr.get("max", 99999)
        notify = self._config.get("notify_on_deal", True)
        changed = False

        for shop_key, items in results.items():
            for item in items:
                # Don't notify for items that are known to be unavailable.
                if item.get("in_stock") is False:
                    continue
                price = item.get("price")
                title = item.get("title", "")
                delivery = item.get("delivery", "")
                key = f"{shop_key}_{title}"

                # Check price change
                if price is not None and price > 0:
                    if price < pmin or price > pmax:
                        continue
                    last = self._last_prices.get(key)
                    if last is None or price < last:
                        self._last_prices[key] = price
                        changed = True
                        if notify:
                            self._notify(f"💶 Deal! {item.get('shop', shop_key)}",
                                         f"{title}\n{price:.2f} €")

                # Check delivery time change
                if delivery:
                    dkey = f"{key}_delivery"
                    last_delivery = self._last_prices.get(dkey)
                    if last_delivery and last_delivery != delivery:
                        self._last_prices[dkey] = delivery
                        changed = True
                        if notify:
                            self._notify(f"🕐 {item.get('shop', shop_key)}",
                                         f"Lieferzeit geändert: {title}")
                    elif not last_delivery:
                        self._last_prices[dkey] = delivery
                        changed = True

        if changed:
            self._save_last_prices()

    # ------------------------------------------------------------------
    # Auto-update
    # ------------------------------------------------------------------

    def _on_update_found(self, version: str, url: str):
        reply = QMessageBox.question(
            self,
            "Update verfügbar",
            f"Version {version} ist verfügbar (aktuell: v{__version__}).\n\n"
            "Jetzt herunterladen und installieren?\n"
            "(Die App wird nach dem Download automatisch neu gestartet.)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            self._apply_update(url)

    def _apply_update(self, url: str):
        import tempfile
        exe_path = Path(sys.executable)
        update_path = exe_path.with_suffix(".update")

        prog = QProgressDialog("Herunterladen…", "Abbrechen", 0, 100, self)
        prog.setWindowTitle("Update wird installiert")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumWidth(380)
        prog.setValue(0)
        prog.show()

        self._downloader = UpdateDownloader(url, update_path)

        def on_progress(done: int, total: int):
            if prog.wasCanceled():
                self._downloader.terminate()
                update_path.unlink(missing_ok=True)
                return
            if total > 0:
                mb_done = done / 1024 / 1024
                mb_total = total / 1024 / 1024
                prog.setValue(int(done * 100 / total))
                prog.setLabelText(f"Herunterladen… {mb_done:.1f} / {mb_total:.1f} MB")

        def on_finished():
            prog.close()
            # Write a bat script; Windows can't replace a running exe directly.
            bat_fd, bat_path = tempfile.mkstemp(suffix=".bat")
            with os.fdopen(bat_fd, "w", encoding="utf-8") as f:
                f.write(
                    "@echo off\r\n"
                    "timeout /t 2 /nobreak >nul\r\n"
                    f'move /y "{update_path}" "{exe_path}"\r\n'
                    f'start "" "{exe_path}"\r\n'
                    'del "%~f0"\r\n'
                )
            import subprocess
            subprocess.Popen(["cmd", "/c", bat_path], creationflags=0x08000000)
            QApplication.quit()

        def on_error(msg: str):
            prog.close()
            QMessageBox.critical(self, "Download fehlgeschlagen", msg)
            update_path.unlink(missing_ok=True)

        self._downloader.progress.connect(on_progress)
        self._downloader.finished.connect(on_finished)
        self._downloader.error.connect(on_error)
        self._downloader.start()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _on_settings(self):
        dialog = SettingsDialog(self._config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._config = dialog.get_config()
            cfgmod.save_config(self._config)
            self._start_timer()
            self._update_status("⚙ Einstellungen gespeichert")

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def _update_status(self, msg: str):
        self._status.showMessage(msg)
        if self._tray:
            self._tray.setToolTip(f"Midea PortaSplit — {msg}")

    def _notify(self, title: str, body: str):
        """Native, non-blocking notification via the tray balloon (no PowerShell)."""
        if self._tray:
            self._tray.showMessage(title, body, QSystemTrayIcon.Information, 8000)
        else:
            notifications.notify_info(title, body)

    def _load_last_prices(self) -> dict[str, float]:
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return {k: float(v) for k, v in json.load(f).items()}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_last_prices(self):
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._last_prices, f, indent=2)
        except Exception as e:
            logger.warning("Could not save last_prices: %s", e)

    # ------------------------------------------------------------------
    # Close → minimize to tray
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        if self._tray and self._config.get("tray_mode", True):
            self.hide()
            if self._tray:
                self._tray.showMessage(
                    "Midea PortaSplit Monitor",
                    "Läuft im Hintergrund weiter.\nKlicke auf das Tray-Symbol zum Öffnen.",
                    QSystemTrayIcon.Information,
                    3000,
                )
            event.ignore()
        else:
            self._timer.stop()
            self._save_last_prices()
            super().closeEvent(event)


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Midea PortaSplit Preis-Monitor")
    app.setOrganizationName("PortaSplitMonitor")

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

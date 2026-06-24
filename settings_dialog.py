"""Settings dialog for Midea PortaSplit Preis-Monitor."""

from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QDesktopServices
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class SettingsDialog(QDialog):
    """Dialog for configuring price range, location, shops, and products."""

    def __init__(self, config: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Einstellungen — Midea PortaSplit Preis-Monitor")
        self.setMinimumWidth(560)
        self._build_ui()
        self._load_config()

    # ------------------------------------------------------------------
    # UI Build
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # -- Location --
        loc_group = QGroupBox("📍 Standort (für Filial-Shops)")
        loc_layout = QFormLayout(loc_group)
        self._location = QLineEdit()
        self._location.setPlaceholderText("z.B. Leipzig, Berlin, München …")
        loc_layout.addRow("Stadt:", self._location)
        layout.addWidget(loc_group)

        # -- Price Range --
        price_group = QGroupBox("💰 Preisgrenzen")
        price_layout = QFormLayout(price_group)
        row = QHBoxLayout()
        self._price_min = QSpinBox()
        self._price_min.setRange(0, 5000)
        self._price_min.setSuffix(" €")
        self._price_min.setSingleStep(50)
        row.addWidget(self._price_min)
        row.addWidget(QLabel("bis"))
        self._price_max = QSpinBox()
        self._price_max.setRange(0, 5000)
        self._price_max.setSuffix(" €")
        self._price_max.setSingleStep(50)
        row.addWidget(self._price_max)
        price_layout.addRow("Preisspanne:", row)
        layout.addWidget(price_group)

        # -- Check Interval --
        interval_group = QGroupBox("⏱ Scan-Intervall")
        interval_layout = QFormLayout(interval_group)
        self._interval = QSpinBox()
        self._interval.setRange(5, 1440)
        self._interval.setSuffix(" Minuten")
        self._interval.setSingleStep(5)
        interval_layout.addRow("Alle:", self._interval)
        layout.addWidget(interval_group)

        # -- Products --
        prod_group = QGroupBox("❄️ Produktvarianten")
        prod_layout = QVBoxLayout(prod_group)
        self._product_checks: dict[str, QCheckBox] = {}
        for prod in self._config.get("products", []):
            cb = QCheckBox(prod.get("name", prod["key"]))
            self._product_checks[prod["key"]] = cb
            prod_layout.addWidget(cb)
        layout.addWidget(prod_group)

        # -- Shops: split online vs local --
        shops = self._config.get("shops", {})
        online_shops = {k: v for k, v in shops.items() if not v.get("local", False)}
        local_shops = {k: v for k, v in shops.items() if v.get("local", False)}

        # Online shops
        if online_shops:
            online_group = QGroupBox("🌐 Online-Shops")
            online_layout = QGridLayout(online_group)
            self._shop_checks: dict[str, QCheckBox] = {}
            for i, (key, info) in enumerate(online_shops.items()):
                cb = QCheckBox(info.get("name", key))
                self._shop_checks[key] = cb
                online_layout.addWidget(cb, i // 2, i % 2)
            layout.addWidget(online_group)

        # Local shops
        if local_shops:
            local_group = QGroupBox("🏪 Filialen (lokal)")
            local_layout = QGridLayout(local_group)
            for i, (key, info) in enumerate(local_shops.items()):
                name = info.get("name", key)
                cb = QCheckBox(name + " {location}")
                self._shop_checks[key] = cb
                local_layout.addWidget(cb, i // 2, i % 2)
            layout.addWidget(local_group)

        # -- Buy Me a Coffee --
        bmc_layout = QHBoxLayout()
        bmc_layout.addStretch()
        bmc = QLabel(
            '<a href="https://buymeacoffee.com/darioheller" '
            'style="color: #FF813F; font-size: 14px; text-decoration: none; font-weight: bold;">'
            '☕ Buy me a coffee</a>'
        )
        bmc.setOpenExternalLinks(True)
        bmc.setCursor(Qt.PointingHandCursor)
        bmc_layout.addWidget(bmc)
        bmc_layout.addStretch()
        layout.addLayout(bmc_layout)

        # -- Buttons --
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    def _load_config(self):
        self._location.setText(self._config.get("location", "Leipzig"))

        pr = self._config.get("price_range", {})
        self._price_min.setValue(pr.get("min", 600))
        self._price_max.setValue(pr.get("max", 1800))
        self._interval.setValue(self._config.get("check_interval_minutes", 30))

        for prod in self._config.get("products", []):
            cb = self._product_checks.get(prod["key"])
            if cb:
                cb.setChecked(prod.get("active", True))

        location = self._config.get("location", "Leipzig")
        for key, info in self._config.get("shops", {}).items():
            cb = self._shop_checks.get(key)
            if cb:
                cb.setChecked(info.get("active", True))
                # Update local shop label with location
                if info.get("local", False):
                    cb.setText(f"{info.get('name', key)} {location}")

    def get_config(self) -> dict[str, Any]:
        """Return an updated config dict from the dialog values."""
        cfg = dict(self._config)
        cfg["location"] = self._location.text().strip() or "Leipzig"
        cfg["price_range"] = {
            "min": self._price_min.value(),
            "max": self._price_max.value(),
        }
        cfg["check_interval_minutes"] = self._interval.value()

        for prod in cfg.get("products", []):
            cb = self._product_checks.get(prod["key"])
            if cb:
                prod["active"] = cb.isChecked()

        for key, info in cfg.get("shops", {}).items():
            cb = self._shop_checks.get(key)
            if cb:
                info["active"] = cb.isChecked()

        return cfg

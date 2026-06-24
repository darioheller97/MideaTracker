"""Desktop notifications for Midea PortaSplit Preis-Monitor."""

import subprocess
import logging

logger = logging.getLogger(__name__)


def notify_deal(shop: str, product: str, price: float, url: str) -> bool:
    """Send a Windows BalloonTip notification about a deal."""
    title = f"💶 Deal gefunden! {shop}"
    body = f"{product}\n{price:.2f} €"
    return _win_notify(title, body)


def notify_error(shop: str, msg: str) -> bool:
    """Send a notification about a scrape error."""
    title = f"⚠ {shop}"
    body = msg
    return _win_notify(title, body, icon="Warning")


def notify_info(title: str, body: str) -> bool:
    """Send a generic info notification."""
    return _win_notify(title, body)


def _win_notify(title: str, body: str, icon: str = "Info") -> bool:
    """Send Windows notification via PowerShell."""
    try:
        # Escape single quotes for PowerShell
        title_s = title.replace("'", "''")
        body_s = body.replace("'", "''")
        ps_cmd = (
            "[System.Windows.Forms.Application]::EnableVisualStyles(); "
            "$b=New-Object System.Windows.Forms.NotifyIcon; "
            "$b.Icon=[System.Drawing.SystemIcons]::Information; "
            "$b.Visible=$true; "
            f"$b.BalloonTipTitle='{title_s}'; "
            f"$b.BalloonTipText='{body_s}'; "
            f"$b.BalloonTipIcon=[System.Windows.Forms.ToolTipIcon]::{icon}; "
            "$b.ShowBalloonTip(10000); "
            "Start-Sleep -Seconds 12; "
            "$b.Dispose()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, timeout=20, check=False,
        )
        return True
    except Exception as e:
        logger.warning("Notification failed: %s", e)
        return False

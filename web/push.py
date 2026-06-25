"""Web Push (VAPID) helper.

Generates a VAPID keypair on first use (stored next to this file, git-ignored).
The browser needs the public application-server key; the server signs pushes with
the private PEM via pywebpush.
"""

import base64
import json
import logging
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

logger = logging.getLogger(__name__)

_DIR = Path(__file__).resolve().parent
PRIV_PEM = _DIR / ".vapid_private.pem"
META = _DIR / ".vapid.json"


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def ensure_keys() -> None:
    if PRIV_PEM.exists() and META.exists():
        return
    priv = ec.generate_private_key(ec.SECP256R1())
    PRIV_PEM.write_bytes(priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    pub = priv.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    META.write_text(json.dumps({"application_server_key": _b64url(pub)}))
    logger.info("Generated VAPID keypair in %s", _DIR)


def application_server_key() -> str:
    """Base64url public key the browser passes to PushManager.subscribe()."""
    ensure_keys()
    return json.loads(META.read_text())["application_server_key"]


def _claims() -> dict:
    return {"sub": os.environ.get("VAPID_CLAIM_EMAIL", "mailto:admin@iceatea.me")}


def send_push(subscription: dict, payload: dict) -> bool:
    """Send a push to one subscription. Returns False on failure (e.g. expired)."""
    ensure_keys()
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.warning("pywebpush not installed")
        return False
    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=str(PRIV_PEM),
            vapid_claims=_claims(),
            timeout=10,
        )
        return True
    except WebPushException as e:
        logger.warning("Web push failed (%s): %s", getattr(e, "response", None), e)
        return False
    except Exception as e:
        logger.warning("Web push error: %s", e)
        return False

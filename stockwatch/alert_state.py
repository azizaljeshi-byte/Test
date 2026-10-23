"""The decision-change alerts' memory between scheduled runs, encrypted.

The scheduled job keeps this file in the GitHub Actions cache, which anyone who can open a pull request on
this public repository can read. So the file is encrypted (Fernet: AES with an HMAC check) with a key
derived from the STOCKWATCH_STATE_KEY repository secret; without the key it reveals nothing but its size.
It holds only each tracked ticker's last call (e.g. HOLD) and any change waiting to be confirmed: no share
counts, costs, prices or message text.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

KEY_ENV = "STOCKWATCH_STATE_KEY"
MIN_KEY_LENGTH = 32
PATH = Path(__file__).resolve().parent.parent / "data" / "alert_state.bin"
_SALT = b"stockwatch-alert-state-v1"


class StateError(Exception):
    """Safe for public logs: never contains the key or the state."""


def key_status() -> str:
    key = (os.getenv(KEY_ENV) or "").strip()
    if not key:
        return "missing"
    return "configured" if len(key) >= MIN_KEY_LENGTH else f"too short (needs {MIN_KEY_LENGTH}+ characters)"


def _fernet() -> Fernet:
    if key_status() != "configured":
        raise StateError(f"{KEY_ENV} is {key_status()}")
    raw = hashlib.pbkdf2_hmac("sha256", os.environ[KEY_ENV].strip().encode(), _SALT, 200_000, dklen=32)
    return Fernet(base64.urlsafe_b64encode(raw))


def load(path: Path = PATH) -> tuple[dict, str]:
    """(entries, "restored" | "none"). An unreadable file (wrong key, tampering) raises StateError."""
    path = Path(path)
    if not path.exists():
        return {}, "none"
    try:
        data = json.loads(_fernet().decrypt(path.read_bytes()))
    except (InvalidToken, ValueError):
        raise StateError("the saved alert state can't be decrypted (key changed or file damaged)") from None
    if data.get("version") != 1 or not isinstance(data.get("tickers"), dict):
        raise StateError("the saved alert state has an unknown format")
    return data["tickers"], "restored"


def save(entries: dict, path: Path = PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"version": 1, "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "tickers": entries}, sort_keys=True).encode()
    path.write_bytes(_fernet().encrypt(body))

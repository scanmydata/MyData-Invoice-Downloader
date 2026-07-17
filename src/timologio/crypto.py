"""Κρυπτογράφηση credentials at-rest.

Η σύμβαση είναι πορταρισμένη από mydata-etimologio-bridge/crypto.php:40-58,
με libsodium -> Fernet. Δύο σημεία που αξίζει να κρατηθούν όπως είναι:

* το versioned prefix ``enc:1:`` αφήνει χώρο για rotation χωρίς migration
* το ``dec()`` επιστρέφει ό,τι δεν έχει prefix ως έχει (crypto.php:50), οπότε
  η ενεργοποίηση της κρυπτογράφησης δεν σπάει υπάρχοντα δεδομένα
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)

PREFIX = "enc:1:"

_ENV_KEY = "TIMOLOGIO_ENC_KEY"


class SecretRedactingFilter(logging.Filter):
    """Κόβει credentials από τα logs.

    Τα subscription keys είναι 32-hex (επιβεβαιωμένο: όλα τα 58 πραγματικά
    κλειδιά στο Κωδικοί_Υπόχρεων.xlsx έχουν ακριβώς 32 χαρακτήρες), οπότε τα
    πιάνουμε με pattern ακόμη κι αν ξεφύγουν από αμέλεια σε κάποιο μήνυμα.
    """

    _PATTERNS = [
        re.compile(r"(?i)\b[0-9a-f]{32}\b"),
        re.compile(r"(?i)(Ocp-Apim-Subscription-Key\s*[:=]\s*)\S+"),
        re.compile(r"(?i)(aade-user-id\s*[:=]\s*)\S+"),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        red = self._PATTERNS[0].sub("<redacted-key>", msg)
        red = self._PATTERNS[1].sub(r"\1<redacted>", red)
        red = self._PATTERNS[2].sub(r"\1<redacted>", red)
        if red != msg:
            record.msg = red
            record.args = ()
        return True


def _lock_down(path: Path) -> None:
    """Το chmod 0600 του crypto.php:36 δεν υπάρχει στα Windows -> ACL."""
    try:
        import getpass

        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{getpass.getuser()}:F"],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except Exception:  # pragma: no cover - best effort, δεν μπλοκάρει
        log.debug("Δεν μπόρεσα να περιορίσω τα δικαιώματα του %s", path)


def load_or_create_key(enckey_path: Path) -> bytes:
    import os

    env = os.environ.get(_ENV_KEY)
    if env:
        return env.strip().encode()

    if enckey_path.exists():
        return enckey_path.read_bytes().strip()

    enckey_path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    enckey_path.write_bytes(key)
    _lock_down(enckey_path)
    log.info("Δημιουργήθηκε νέο κλειδί κρυπτογράφησης: %s", enckey_path)
    return key


class Crypto:
    def __init__(self, enckey_path: Path) -> None:
        self._fernet = Fernet(load_or_create_key(enckey_path))

    def enc(self, plain: str) -> str:
        if not plain:
            return ""
        return PREFIX + self._fernet.encrypt(plain.encode()).decode()

    def dec(self, stored: str) -> str:
        if not stored:
            return ""
        if not stored.startswith(PREFIX):
            # crypto.php:50 — plaintext περνάει ως έχει
            return stored
        try:
            return self._fernet.decrypt(stored[len(PREFIX):].encode()).decode()
        except InvalidToken:
            # Ποτέ δεν λογκάρουμε την τιμή.
            log.error("Αποτυχία αποκρυπτογράφησης — λάθος ή χαμένο .enckey;")
            return ""

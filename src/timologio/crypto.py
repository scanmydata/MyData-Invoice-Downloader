"""Κρυπτογράφηση credentials at-rest.

Η σύμβαση είναι πορταρισμένη από ένα παλιότερο εργαλείο μας,
με libsodium -> Fernet. Δύο σημεία που αξίζει να κρατηθούν όπως είναι:

* το versioned prefix ``enc:1:`` αφήνει χώρο για rotation χωρίς migration
* το ``dec()`` επιστρέφει ό,τι δεν έχει prefix ως έχει (το παλιότερο εργαλείο), οπότε
  η ενεργοποίηση της κρυπτογράφησης δεν σπάει υπάρχοντα δεδομένα

**Το κλειδί δεδομένων** παράγεται τυχαία μία φορά ανά φάκελο δεδομένων και ζει
στο ``.enckey``. Δεν υπάρχει πουθενά στον κώδικα ούτε στον installer: κάθε
εγκατάσταση έχει το δικό της.

Το ``.enckey`` έχει δύο μορφές:

``ακάλυπτο``
    Σκέτο το κλειδί Fernet. Όποιος διαβάζει τον φάκελο το διαβάζει κι αυτό —
    προστατεύει μόνο από κλεμμένο αντίγραφο *μόνο* της βάσης.

``προστατευμένο`` (μορφή 2, με κύριο κωδικό)
    Το κλειδί δεδομένων είναι **τυλιγμένο** με ένα δεύτερο κλειδί που παράγεται
    από τον κωδικό μέσω Argon2id. Στον δίσκο δεν υπάρχει τίποτα που να το
    ξεκλειδώνει· χωρίς τον κωδικό ο φάκελος είναι άχρηστος ακόμη κι αν
    αντιγραφεί ολόκληρος.

Το κλειδί δεδομένων μένει το ίδιο όταν αλλάζει ο κωδικός — αλλιώς κάθε αλλαγή
κωδικού θα απαιτούσε να ξανακρυπτογραφηθεί όλη η βάση.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import secrets
import subprocess
from pathlib import Path

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)

PREFIX = "enc:1:"

_ENV_KEY = "TIMOLOGIO_ENC_KEY"

#: Για CLI / scheduled tasks σε προστατευμένο φάκελο, χωρίς διαδραστικό prompt.
_ENV_PASSWORD = "TIMOLOGIO_MASTER_PASSWORD"

#: Πρώτη γραμμή αρχείου· ό,τι δεν την έχει είναι σκέτο κλειδί (παλιά μορφή).
_MAGIC = "timologio-key: 2"

#: Παράμετροι Argon2id. Οι τιμές είναι το προφίλ που συνιστά το OWASP για
#: interactive login (64 MiB / 3 περάσματα): αισθητό κόστος για επιτιθέμενο που
#: δοκιμάζει κωδικούς μαζικά, ~0,1 δευτ. για τον χρήστη που τον ξέρει.
_ARGON_MEMORY_KIB = 65536
_ARGON_TIME = 3
_ARGON_LANES = 4
#: Μήκος salt. Τυχαίο ανά αρχείο ώστε δύο γραφεία με τον ίδιο κωδικό να μην
#: μοιράζονται παραγόμενο κλειδί (και να μην πιάνονται με προϋπολογισμένους πίνακες).
_SALT_BYTES = 16

#: Το κλειδί, αφού ξεκλειδωθεί μία φορά. Τα worker threads και οι επόμενες
#: κλήσεις δεν ξαναζητούν κωδικό — ο χρήστης τον δίνει μία φορά ανά εκκίνηση.
_UNLOCKED: dict[str, bytes] = {}


class KeyfileLocked(Exception):
    """Το `.enckey` είναι προστατευμένο και δεν δόθηκε κωδικός."""

    message_el = "Ο φάκελος δεδομένων προστατεύεται με κύριο κωδικό."


class WrongPassword(Exception):
    """Ο κωδικός δεν ξεκλειδώνει το `.enckey`."""

    message_el = "Λάθος κωδικός."


class SecretRedactingFilter(logging.Filter):
    """Κόβει credentials από τα logs.

    Τα subscription keys είναι 32-hex (επιβεβαιωμένο: όλα τα πραγματικά κλειδιά που ελέγχθηκαν στους «Κωδικούς Υπόχρεων» έχουν ακριβώς 32 χαρακτήρες), οπότε τα
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
    """Το chmod 0600 του το παλιότερο εργαλείο δεν υπάρχει στα Windows -> ACL."""
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


# --- μορφή αρχείου ----------------------------------------------------------


def _parse(raw: bytes) -> dict[str, str] | None:
    """Τα πεδία του προστατευμένου αρχείου, ή None αν είναι σκέτο κλειδί."""
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return None
    if not text.startswith(_MAGIC):
        return None
    fields: dict[str, str] = {}
    for line in text.splitlines()[1:]:
        key, _, value = line.partition(":")
        if value:
            fields[key.strip()] = value.strip()
    return fields


def _kek(password: str, salt: bytes, kdf: str) -> bytes:
    """Το κλειδί που τυλίγει το κλειδί δεδομένων, παραγόμενο από τον κωδικό."""
    if kdf == "argon2id":
        from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

        raw = Argon2id(
            salt=salt,
            length=32,
            iterations=_ARGON_TIME,
            lanes=_ARGON_LANES,
            memory_cost=_ARGON_MEMORY_KIB,
        ).derive(password.encode())
    elif kdf == "scrypt":
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

        raw = Scrypt(salt=salt, length=32, n=2**16, r=8, p=1).derive(password.encode())
    else:
        raise ValueError(f"Άγνωστη συνάρτηση παραγωγής κλειδιού: {kdf}")
    return base64.urlsafe_b64encode(raw)


def _preferred_kdf() -> str:
    """Argon2id όπου υπάρχει, αλλιώς scrypt.

    Το Argon2id θέλει OpenSSL 3.2+· η μορφή του αρχείου γράφει ποιο
    χρησιμοποιήθηκε, οπότε ένα αρχείο φτιαγμένο με το ένα ξεκλειδώνει πάντα.
    """
    try:
        _kek("δοκιμή", b"\x00" * _SALT_BYTES, "argon2id")
    except (UnsupportedAlgorithm, ImportError):
        log.info("Το Argon2id δεν υποστηρίζεται εδώ — χρήση scrypt.")
        return "scrypt"
    return "argon2id"


def _write_protected(path: Path, data_key: bytes, password: str) -> None:
    salt = secrets.token_bytes(_SALT_BYTES)
    kdf = _preferred_kdf()
    wrapped = Fernet(_kek(password, salt, kdf)).encrypt(data_key)
    lines = [
        _MAGIC,
        f"kdf: {kdf}",
        f"salt: {base64.urlsafe_b64encode(salt).decode()}",
        f"wrapped: {wrapped.decode()}",
    ]
    if kdf == "argon2id":
        lines[1:1] = [
            f"memory_kib: {_ARGON_MEMORY_KIB}",
            f"time: {_ARGON_TIME}",
            f"lanes: {_ARGON_LANES}",
        ]
    _write_atomic(path, ("\n".join(lines) + "\n").encode("ascii"))


def _write_atomic(path: Path, payload: bytes) -> None:
    """Γράψιμο μέσω προσωρινού αρχείου.

    Το `.enckey` είναι το μοναδικό αντίγραφο του κλειδιού: διακοπή ρεύματος στη
    μέση ενός in-place γραψίματος θα άφηνε μισό αρχείο και μη αναστρέψιμη
    απώλεια όλων των credentials.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".new")
    tmp.write_bytes(payload)
    _lock_down(tmp)
    os.replace(tmp, path)
    _lock_down(path)


def _unwrap(fields: dict[str, str], password: str) -> bytes:
    try:
        salt = base64.urlsafe_b64decode(fields["salt"])
        kek = _kek(password, salt, fields.get("kdf", "argon2id"))
        return Fernet(kek).decrypt(fields["wrapped"].encode())
    except (InvalidToken, KeyError, ValueError) as exc:
        raise WrongPassword from exc


# --- δημόσιο API ------------------------------------------------------------


def is_protected(enckey_path: Path) -> bool:
    """Χρειάζεται κύριος κωδικός για να ανοίξει αυτός ο φάκελος δεδομένων;"""
    if not enckey_path.exists():
        return False
    return _parse(enckey_path.read_bytes()) is not None


def unlock(enckey_path: Path, password: str) -> None:
    """Ξεκλειδώνει μία φορά για όλη τη διεργασία. Σφάλμα -> WrongPassword."""
    fields = _parse(enckey_path.read_bytes())
    if fields is None:
        return
    _UNLOCKED[str(enckey_path.resolve())] = _unwrap(fields, password)


def forget() -> None:
    """Ξεχνά το ξεκλειδωμένο κλειδί (κλείδωμα, δοκιμές)."""
    _UNLOCKED.clear()


def load_or_create_key(enckey_path: Path, password: str | None = None) -> bytes:
    env = os.environ.get(_ENV_KEY)
    if env:
        return env.strip().encode()

    if enckey_path.exists():
        raw = enckey_path.read_bytes()
        fields = _parse(raw)
        if fields is None:
            return raw.strip()
        slot = str(enckey_path.resolve())
        # Κωδικός που δόθηκε ρητά ελέγχεται ΠΑΝΤΑ απέναντι στο αρχείο, ποτέ από
        # την cache. Αλλιώς, με ξεκλειδωμένο ήδη φάκελο, η «επιβεβαίωση
        # τρέχοντος κωδικού» στην αλλαγή ή στην αφαίρεση προστασίας θα δεχόταν
        # οποιονδήποτε κωδικό — δηλαδή δεν θα επιβεβαίωνε τίποτα.
        if password:
            key = _unwrap(fields, password)
            _UNLOCKED[slot] = key
            return key
        cached = _UNLOCKED.get(slot)
        if cached:
            return cached
        env_password = os.environ.get(_ENV_PASSWORD)
        if not env_password:
            raise KeyfileLocked(KeyfileLocked.message_el)
        key = _unwrap(fields, env_password)
        _UNLOCKED[slot] = key
        return key

    key = Fernet.generate_key()
    if password:
        _write_protected(enckey_path, key, password)
        _UNLOCKED[str(enckey_path.resolve())] = key
    else:
        _write_atomic(enckey_path, key)
    log.info("Δημιουργήθηκε νέο κλειδί κρυπτογράφησης: %s", enckey_path)
    return key


def set_password(enckey_path: Path, password: str, current: str | None = None) -> None:
    """Βάζει ή αλλάζει τον κύριο κωδικό. Το κλειδί δεδομένων δεν αλλάζει."""
    if not password:
        raise ValueError("Ο κωδικός δεν μπορεί να είναι κενός.")
    data_key = load_or_create_key(enckey_path, current)
    _write_protected(enckey_path, data_key, password)
    _UNLOCKED[str(enckey_path.resolve())] = data_key


def remove_password(enckey_path: Path, current: str) -> None:
    """Επιστρέφει το αρχείο σε ακάλυπτη μορφή, αφού επιβεβαιώσει τον κωδικό."""
    data_key = load_or_create_key(enckey_path, current)
    _write_atomic(enckey_path, data_key)
    _UNLOCKED[str(enckey_path.resolve())] = data_key


class Crypto:
    def __init__(self, enckey_path: Path, password: str | None = None) -> None:
        self._fernet = Fernet(load_or_create_key(enckey_path, password))

    def enc(self, plain: str) -> str:
        if not plain:
            return ""
        return PREFIX + self._fernet.encrypt(plain.encode()).decode()

    def dec(self, stored: str) -> str:
        if not stored:
            return ""
        if not stored.startswith(PREFIX):
            # το παλιότερο εργαλείο — plaintext περνάει ως έχει
            return stored
        try:
            return self._fernet.decrypt(stored[len(PREFIX):].encode()).decode()
        except InvalidToken:
            # Ποτέ δεν λογκάρουμε την τιμή.
            log.error("Αποτυχία αποκρυπτογράφησης — λάθος ή χαμένο .enckey;")
            return ""

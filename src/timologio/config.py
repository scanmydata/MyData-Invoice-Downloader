"""Ρυθμίσεις εφαρμογής.

Ο φάκελος δεδομένων κρατιέται εκτός του πακέτου ώστε το PyInstaller bundle να
μένει read-only και το .enckey να επιβιώνει σε αναβαθμίσεις.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# --- myDATA endpoints -------------------------------------------------------
MYDATA_BASE = "https://mydatapi.aade.gr/myDATA"
URL_REQUEST_DOCS = f"{MYDATA_BASE}/RequestDocs"
URL_REQUEST_TRANSMITTED_DOCS = f"{MYDATA_BASE}/RequestTransmittedDocs"
URL_REQUEST_E3_INFO = f"{MYDATA_BASE}/RequestE3Info"

#: Ο μόνος host στον οποίο επιτρέπεται να σταλούν τα διαπιστευτήρια ΑΑΔΕ.
AADE_HOST = "mydatapi.aade.gr"

#: XML namespace όλων των απαντήσεων myDATA.
NS = {"ns": "http://www.aade.gr/myDATA/invoice/v1.0"}

# --- Πάροχοι ----------------------------------------------------------------
#: Το επίσημο PDF της ΑΑΔΕ (σελ. 31) λέει ότι το σκέτο downloadingInvoiceUrl
#: επιστρέφει PDF by default. ΔΕΝ ισχύει: μετρημένα, Epsilon και Impact
#: επιστρέφουν HTML σελίδα προβολής. Το suffix είναι υποχρεωτικό.
PDF_SUFFIX = "/pdf"


#: Κλειδί registry όπου ο installer γράφει τον φάκελο δεδομένων που επέλεξε ο
#: χρήστης. HKCU (όχι HKLM) ώστε να μη χρειάζεται δικαιώματα διαχειριστή.
_REG_PATH = r"Software\scanmydata\TimologioDownloader"
_REG_VALUE = "DataDir"

#: Οι τρεις ρόλοι που δίνει ο installer. Ο ρόλος δεν αλλάζει τι *μπορεί* να κάνει
#: η εφαρμογή — αλλάζει τι της ταιριάζει: ο server ξεκινά στο tray και μένει
#: ανοιχτός, το τερματικό ελέγχει τη σύνδεση πριν από οτιδήποτε άλλο.
ROLES = ("standalone", "server", "terminal")

#: Η έκδοση που δηλώνει το κάθε instance στους υπόλοιπους του δικτύου. Κρατιέται
#: εδώ ώστε να υπάρχει μία πηγή: το pyproject δεν διαβάζεται μέσα από το bundle
#: του PyInstaller.
APP_VERSION = "0.2.7"

ROLE_LABELS_EL = {
    "standalone": "Αυτόνομος υπολογιστής",
    "server": "Server (κρατά τα δεδομένα)",
    "terminal": "Τερματικό (συνδέεται στον server)",
}


def _registry_value(name: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH) as key:
            value, _ = winreg.QueryValueEx(key, name)
        return str(value) if value else None
    except OSError:
        return None


def _data_dir_from_registry() -> Path | None:
    value = _registry_value(_REG_VALUE)
    return Path(value) if value else None


def load_role() -> str:
    """Ο ρόλος του υπολογιστή, όπως τον όρισε ο installer."""
    value = (os.environ.get("TIMOLOGIO_ROLE") or _registry_value("Role") or "").lower()
    return value if value in ROLES else "standalone"


def load_start_minimized() -> bool:
    """Ξεκινά μαζεμένο στο tray;

    Ο installer γράφει την αρχική τιμή· η εφαρμογή τη γράφει ξανά όταν την
    αλλάξει ο χρήστης από τον πίνακα ελέγχου, ώστε να υπάρχει μία πηγή αλήθειας
    ανεξάρτητα από το ποιος την όρισε τελευταίος.
    """
    return (_registry_value("StartMinimized") or "0") == "1"


def save_start_minimized(value: bool) -> None:
    if os.name != "nt":
        return
    try:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _REG_PATH) as key:
            winreg.SetValueEx(key, "StartMinimized", 0, winreg.REG_SZ, "1" if value else "0")
    except OSError:
        pass


def _documents_dir() -> Path:
    """Ο φάκελος «Έγγραφα», ακόμη κι αν έχει μετακινηθεί (π.χ. OneDrive)."""
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "Personal")
            return Path(os.path.expandvars(value))
        except OSError:
            pass
    return Path.home() / "Documents"


def _default_data_dir() -> Path:
    return _documents_dir() / "Παραστατικά myDATA"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    """Ρίζα για βάση, .enckey και κατεβασμένα αρχεία."""

    max_workers: int = 8
    """Συνολικά ταυτόχρονα downloads."""

    max_per_host: int = 2
    """Ταυτόχρονα ανά πάροχο. Impact+Epsilon = ~88% του όγκου· χωρίς αυτό
    τους σφυροκοπάμε."""

    aade_timeout: int = 120
    """Το RequestDocs επιστρέφει μεγάλα XML — θέλει γενναίο timeout."""

    provider_timeout: int = 60
    max_retries: int = 4
    retry_cap_seconds: int = 300

    @property
    def db_path(self) -> Path:
        return self.data_dir / "timologio.db"

    @property
    def enckey_path(self) -> Path:
        return self.data_dir / ".enckey"

    @property
    def storage_root(self) -> Path:
        return self.data_dir / "data"

    @property
    def role(self) -> str:
        return load_role()


def load_settings() -> Settings:
    """Ο φάκελος δεδομένων, κατά σειρά προτεραιότητας:

    1. TIMOLOGIO_DATA_DIR (για δοκιμές / φορητή χρήση)
    2. ό,τι επέλεξε ο χρήστης στην εγκατάσταση (registry)
    3. Έγγραφα\\Παραστατικά myDATA
    """
    raw = os.environ.get("TIMOLOGIO_DATA_DIR")
    if raw:
        return Settings(data_dir=Path(raw).expanduser())
    from_registry = _data_dir_from_registry()
    return Settings(data_dir=from_registry or _default_data_dir())

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


def _data_dir_from_registry() -> Path | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH) as key:
            value, _ = winreg.QueryValueEx(key, _REG_VALUE)
        return Path(value) if value else None
    except OSError:
        return None


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

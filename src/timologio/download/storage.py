"""Διάταξη αρχείων στον δίσκο και ασφαλής εγγραφή.

Σχήμα:

    <root>/<ΑΦΜ πελάτη>/<YYYY>/<MM>/<ΠΡΟΜΗΘΕΥΤΗΣ>_<ΑΦΜ>_<ΗΜ/ΝΙΑ>_<ΣΕΙΡΑ>_<ΑΑ>_<ΑΞΙΑ>.pdf
    .../ΤΟΓΚΑΣ ΒΑΣΙΛΕΙΟΣ_044004008_2026-07-15_ΤΔΑ_3949_202,43.pdf

Το όνομα φτιάχνεται για να διαβάζεται από λογιστή, οπότε κρατά ελληνικά. Αυτό
κοστίζει: ελληνικοί χαρακτήρες, μεταβλητό μήκος και κίνδυνος MAX_PATH. Τα
αντιμετωπίζουμε ρητά:

* η επωνυμία κόβεται στους 40 χαρακτήρες
* συνολικός έλεγχος μήκους διαδρομής, με σμίκρυνση της επωνυμίας αν χρειαστεί
* σε σύγκρουση ονόματος (ίδιος προμηθευτής/σειρά/ΑΑ, άλλο MARK) προστίθεται το
  MARK ώστε να μη χαθεί ποτέ αρχείο

Η μοναδικότητα δεν στηρίζεται στο όνομα: το `documents.local_path` στη βάση
είναι η πηγή αλήθειας, και το UNIQUE(client_id, mark) εγγυάται 1 MARK = 1 αρχείο.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from ..models import Document

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *{f"COM{i}" for i in range(1, 10)},
    *{f"LPT{i}" for i in range(1, 10)},
}

PDF_MAGIC = b"%PDF"

#: Μέγιστο μήκος επωνυμίας μέσα στο όνομα αρχείου.
NAME_CAP = 40

#: Κάτω από αυτό η επωνυμία παραλείπεται εντελώς αντί να κοπεί σε κάτι άχρηστο.
_MIN_NAME = 10

#: Πάνω από αυτό ενεργοποιείται το \\?\ prefix (όριο Windows: 260).
_LONG_PATH_THRESHOLD = 240

#: Στόχος μήκους για ολόκληρη τη διαδρομή πριν αρχίσουμε να κόβουμε.
_PATH_BUDGET = 200


def sanitize(part: str, fallback: str = "_", *, keep_dots: bool = False) -> str:
    """Καθαρίζει ένα κομμάτι path για Windows, κρατώντας τα ελληνικά.

    Τα Windows απαγορεύουν τελεία/κενό στο **τέλος** ονόματος αρχείου ή
    φακέλου. Όταν το κομμάτι μπαίνει στη μέση ενός ονόματος (π.χ. η επωνυμία,
    που ακολουθείται από «_ΑΦΜ_…»), το keep_dots το διατηρεί ώστε το «Α.Ε.» να
    μη γίνει «Α.Ε».
    """
    cleaned = _INVALID.sub("_", (part or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.rstrip(" ") if keep_dots else cleaned.rstrip(". ")
    if not cleaned:
        return fallback
    if cleaned.upper().split(".")[0] in _RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned


def format_amount(value: float) -> str:
    """Ελληνική μορφή με κόμμα υποδιαστολής — χωρίς διαχωριστικό χιλιάδων.

    Η τελεία χιλιάδων θα έμπλεκε με την κατάληξη αρχείου.
    """
    return f"{value:.2f}".replace(".", ",")


def long_path(path: Path) -> str:
    r"""Windows MAX_PATH escape (\\?\ prefix)."""
    text = str(path.resolve())
    if os.name == "nt" and len(text) > _LONG_PATH_THRESHOLD and not text.startswith("\\\\?\\"):
        return "\\\\?\\" + text
    return text


def _stem(doc: Document, client_vat: str, name_cap: int = NAME_CAP) -> str:
    """<ΠΡΟΜΗΘΕΥΤΗΣ>_<ΑΦΜ>_<ΗΜ/ΝΙΑ>_<ΣΕΙΡΑ>_<ΑΑ>_<ΑΞΙΑ>

    Το myDATA συμπληρώνει το <name> μόνο στο ~70% των παραστατικών και το
    μητρώο προμηθευτών φτάνει το ~80%. Όπου η επωνυμία λείπει, το όνομα ξεκινά
    από το ΑΦΜ — μια σειρά αρχείων «ΑΓΝΩΣΤΟΣ_…» δεν βοηθάει κανέναν.
    """
    vat, name = doc.counterparty(client_vat)
    parts = []
    supplier = (
        sanitize(name, "", keep_dots=True)[:name_cap].strip(" _") if name_cap else ""
    )
    if supplier and supplier != "_":
        parts.append(supplier)
    parts += [
        sanitize(vat, "χωρίς ΑΦΜ"),
        sanitize(doc.issue_date, "0000-00-00"),
        sanitize(doc.series, "0"),
        sanitize(doc.aa, "0"),
        sanitize(format_amount(doc.total_value)),
    ]
    return "_".join(parts)


#: Μέγιστο μήκος επωνυμίας μέσα στο όνομα του φακέλου πελάτη.
CLIENT_FOLDER_NAME_CAP = 42


def client_folder(root: Path, client_vat: str, client_label: str = "") -> Path:
    """<root>/<ΑΦΜ> <Επωνυμία>

    Το ΑΦΜ μπαίνει πρώτο ώστε οι φάκελοι να ταξινομούνται σταθερά και να
    παραμένουν αναγνωρίσιμοι ακόμη κι αν αλλάξει η επωνυμία.
    """
    name = sanitize(client_vat)
    label = sanitize(client_label, "")[:CLIENT_FOLDER_NAME_CAP].strip(" _.")
    if label and label != "_":
        name = f"{name} {label}"
    return root / name


def find_client_folder(root: Path, client_vat: str, client_label: str = "") -> Path:
    """Ο φάκελος του πελάτη, ακόμη κι αν φτιάχτηκε με άλλη επωνυμία.

    Η επωνυμία αλλάζει (νέο import, όνομα από VIES). Ψάχνουμε πρώτα υπάρχοντα
    φάκελο που αρχίζει με το ΑΦΜ, ώστε να μη σκορπιστούν τα αρχεία σε δύο
    φακέλους για τον ίδιο πελάτη.
    """
    wanted = client_folder(root, client_vat, client_label)
    if wanted.exists() or not root.exists():
        return wanted
    prefix = sanitize(client_vat)
    for existing in root.iterdir():
        if existing.is_dir() and (existing.name == prefix
                                  or existing.name.startswith(prefix + " ")):
            return existing
    return wanted


def target_path(
    root: Path,
    client_vat: str,
    doc: Document,
    suffix: str = ".pdf",
    *,
    disambiguate: bool = False,
    client_label: str = "",
) -> Path:
    """Χτίζει το τελικό path. Partition κατά ημερομηνία **έκδοσης**.

    Έτσι ένα re-run δεν σκορπίζει την ίδια περίοδο σε άλλους φακέλους.
    """
    year, month = "0000", "00"
    if len(doc.issue_date) >= 7 and doc.issue_date[4] == "-":
        year, month = doc.issue_date[:4], doc.issue_date[5:7]

    folder = client_folder(root, client_vat, client_label) / year / month

    def build(cap: int) -> Path:
        stem = _stem(doc, client_vat, cap)
        if disambiguate:
            stem = f"{stem}_{sanitize(doc.mark)}"
        return folder / f"{stem}{suffix}"

    candidate = build(NAME_CAP)
    if len(str(candidate)) <= _PATH_BUDGET:
        return candidate

    # Πολύ μακριά διαδρομή: κόβουμε την επωνυμία — είναι το μόνο κομμάτι που
    # μπορεί να συρρικνωθεί χωρίς να χαθεί πληροφορία ταυτοποίησης. Υπολογίζουμε
    # πόσος χώρος περισσεύει αντί να μαντεύουμε, ώστε να κρατήσουμε όσο
    # περισσότερο όνομα γίνεται.
    without_name = len(str(build(0)))
    available = _PATH_BUDGET - without_name
    cap = max(0, min(NAME_CAP, available))
    if cap < _MIN_NAME:
        cap = 0  # ένα όνομα 3 γραμμάτων δεν λέει τίποτα — καλύτερα καθόλου
    return build(cap)


def resolve_path(
    root: Path, client_vat: str, doc: Document, suffix: str = ".pdf",
    client_label: str = "",
) -> Path:
    """Σαν το target_path, αλλά αποφεύγει σύγκρουση με άλλο MARK.

    Δύο παραστατικά του ίδιου εκδότη με ίδια σειρά/ΑΑ δεν πρέπει να υπάρχουν
    (η σειρά+ΑΑ είναι μοναδική ανά εκδότη), αλλά αν τα δεδομένα είναι περίεργα
    δεν θέλουμε να χαθεί σιωπηλά αρχείο.
    """
    path = target_path(root, client_vat, doc, suffix, client_label=client_label)
    if not path.exists():
        return path
    return target_path(root, client_vat, doc, suffix, disambiguate=True,
                       client_label=client_label)


def write_atomic(path: Path, payload: bytes) -> tuple[int, str]:
    """Γράφει μέσω .part και μετά os.replace (ατομικό σε NTFS).

    Έτσι ένα διακομμένο run δεν αφήνει ποτέ μισό PDF που θα περνούσε για καλό.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    with open(long_path(part), "wb") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(long_path(part), long_path(path))
    return len(payload), hashlib.sha256(payload).hexdigest()


def is_complete_pdf(path: Path, *, min_bytes: int = 100) -> bool:
    """Idempotent resume: υπάρχον, έγκυρο PDF δεν ξανακατεβαίνει."""
    try:
        if path.stat().st_size < min_bytes:
            return False
        with open(long_path(path), "rb") as fh:
            return fh.read(4) == PDF_MAGIC
    except OSError:
        return False

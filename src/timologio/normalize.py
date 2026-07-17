"""Κανονικοποίηση κειμένου για ταίριασμα επικεφαλίδων Excel.

Ο normalizer του e3_brain.py:200-203 ΔΕΝ δουλεύει σε αυτά τα αρχεία: δεν
αφαιρεί τόνους και μετατρέπει τις τελείες σε κενά, οπότε το «Α.Φ.Μ.» γίνεται
«α φ μ» και δεν ταιριάζει με κανένα alias. Εδώ οι τελείες **σβήνονται** (όχι
κενό) ώστε «Α.Φ.Μ.» -> «αφμ».

Δοκιμασμένο και στις 83 πραγματικές επικεφαλίδες του Κωδικοί_Υπόχρεων.xlsx:
μηδέν collisions, και το «Api myData» (BI) μένει καθαρά διακριτό από το
«Subscription key e-timologio» (BL).
"""

from __future__ import annotations

import re
import unicodedata

_DOTS = re.compile(r"[.·]")
_NON_ALNUM = re.compile(r"[^0-9a-zα-ω]+")
_WS = re.compile(r"\s+")


def fold_accents(text: str) -> str:
    """Αφαιρεί τόνους/διαλυτικά και ενοποιεί το τελικό σίγμα."""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return unicodedata.normalize("NFC", stripped).replace("ς", "σ")


def norm_header(text: object) -> str:
    """Κανονικοποιεί επικεφαλίδα για whole-string ταίριασμα."""
    if text is None:
        return ""
    value = _WS.sub(" ", str(text)).strip().lower()
    value = _DOTS.sub("", value)  # «Α.Φ.Μ.» -> «αφμ», ΟΧΙ «α φ μ»
    value = fold_accents(value)
    value = _NON_ALNUM.sub(" ", value)
    return _WS.sub(" ", value).strip()


def norm_text(text: object) -> str:
    if text is None:
        return ""
    return _WS.sub(" ", str(text)).strip()


_AFM = re.compile(r"\d{9}")


def norm_afm(text: object) -> str:
    """Εξάγει 9ψήφιο ΑΦΜ. Δέχεται float από Excel (π.χ. 802576637.0)."""
    raw = norm_text(text)
    if not raw:
        return ""
    if raw.endswith(".0"):
        raw = raw[:-2]
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 8:  # Excel έκοψε αρχικό μηδενικό
        digits = "0" + digits
    match = _AFM.fullmatch(digits)
    return match.group(0) if match else ""


def valid_afm(afm: str) -> bool:
    """Έλεγχος check digit ΑΦΜ (mod 11).

    Χρησιμοποιείται μόνο για σήμανση στο preview, ποτέ για απόρριψη — ένα
    παλιό ΑΦΜ που δεν περνά τον έλεγχο μπορεί κάλλιστα να είναι υπαρκτό.
    """
    if len(afm) != 9 or not afm.isdigit():
        return False
    total = sum(int(afm[i]) * (2 ** (8 - i)) for i in range(8))
    return total % 11 % 10 == int(afm[8])


_HEX32 = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)


def valid_subscription_key(key: str) -> bool:
    """Τα subscription keys είναι 32-hex.

    Επιβεβαιωμένο: και τα 58 πραγματικά κλειδιά του Κωδικοί_Υπόχρεων.xlsx
    έχουν ακριβώς 32 χαρακτήρες.
    """
    return bool(_HEX32.match(key or ""))


def mask(secret: str) -> str:
    """Για εμφάνιση στο preview — ποτέ ολόκληρο μυστικό στην οθόνη."""
    if not secret:
        return "—"
    if len(secret) <= 4:
        return "*" * len(secret)
    return f"{secret[:2]}{'*' * 6}"

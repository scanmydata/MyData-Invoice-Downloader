"""Αναζήτηση επωνυμίας από το μητρώο ΦΠΑ της ΕΕ (VIES).

Το myDATA συμπληρώνει το <issuer><name> μόνο στο ~70% των παραστατικών, και το
μητρώο από παραστατικά/πελάτες φτάνει το ~80%. Το VIES καλύπτει το υπόλοιπο:
δοκιμασμένο στα 14 ΑΦΜ που το myDATA δεν ονομάζει ποτέ, επέστρεψε **9/9**
επωνυμίες (τα υπόλοιπα δεν ήταν στο δείγμα).

Η ιδέα και ο καθαρισμός του «||» είναι από το ένα παλιότερο εσωτερικό εργαλείο.
Δύο διαφορές:

* χρησιμοποιούμε το **REST** API του VIES αντί για SOAP/zeep. Το zeep σέρνει
  lxml + cryptography extras (~15MB) στο bundle του PyInstaller για μία κλήση.
* δεν υλοποιούμε το fallback στο Business Portal: θέλει κλειδί
  (BUSINESS_PORTAL_KEY) που ο τελικός χρήστης δεν έχει.
"""

from __future__ import annotations

import logging
import re
import threading
import time

import requests

log = logging.getLogger(__name__)

VIES_REST = "https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{cc}/vat/{vat}"

#: Το VIES είναι δωρεάν δημόσια υπηρεσία — μία κλήση/δευτερόλεπτο το πολύ.
MIN_INTERVAL = 1.0

_TIMEOUT = 20


class ViesClient:
    """Σειριακός, ευγενικός client. Κάθε ΑΦΜ ρωτιέται μία φορά ανά εκτέλεση."""

    def __init__(self, min_interval: float = MIN_INTERVAL) -> None:
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})
        self._min_interval = min_interval
        self._last_call = 0.0
        self._lock = threading.Lock()

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> ViesClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _throttle(self) -> None:
        with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def lookup(self, vat: str, country: str = "EL") -> str | None:
        """Επωνυμία για το ΑΦΜ, ή None.

        Ποτέ δεν σηκώνει εξαίρεση: το VIES πέφτει τακτικά για συντήρηση και μια
        αποτυχία εδώ δεν πρέπει να χαλάσει τη λήψη παραστατικών.
        """
        clean = clean_vat(vat)
        if not clean:
            return None
        self._throttle()
        try:
            resp = self._session.get(
                VIES_REST.format(cc=country, vat=clean), timeout=_TIMEOUT
            )
        except requests.RequestException as exc:
            log.debug("VIES: αποτυχία δικτύου για %s: %s", clean, exc)
            return None

        if resp.status_code != 200:
            log.debug("VIES: HTTP %s για %s", resp.status_code, clean)
            return None
        try:
            data = resp.json()
        except ValueError:
            return None

        if not data.get("isValid"):
            return None
        return clean_name(data.get("name"))


def clean_vat(vat: str) -> str | None:
    """Καθαρίζει ΑΦΜ σε 9 ψηφία (το παλιότερο εργαλείο)."""
    if not vat:
        return None
    value = str(vat).strip().upper()
    for prefix in ("EL", "GR"):
        if value.startswith(prefix):
            value = value[2:]
    digits = re.sub(r"\D", "", value)
    return digits if len(digits) == 9 else None


def clean_name(name: str | None) -> str | None:
    """Καθαρίζει την επωνυμία της απάντησης.

    Το VIES επιστρέφει κατά τόπους πολλαπλές επωνυμίες χωρισμένες με «||»
    (π.χ. «JUMBO ΑΝΩΝΥΜΗ ΕΜΠΟΡΙΚΗ ΕΤΑΙΡΕΙΑ||JUMBO») — κρατάμε την πρώτη, όπως
    και το το παλιότερο εργαλείο. Το «---» σημαίνει «δεν δίνεται όνομα».
    """
    if not name:
        return None
    text = str(name)
    if "||" in text:
        text = text.split("||")[0]
    text = " ".join(text.split())
    if not text or text.strip("-") == "":
        return None
    return text

"""Λήψη PDF από τα συστήματα των παρόχων.

ΑΣΦΑΛΕΙΑ: το Session εδώ φτιάχνεται σκόπιμα **χωρίς** auth headers. Τα
downloadingInvoiceUrl είναι capability URLs (περιέχουν μη-μαντεύσιμο token) και
δεν θέλουν αυθεντικοποίηση. Στέλνοντας το κλειδί ΑΑΔΕ σε τρίτο πάροχο θα ήταν
διαρροή· εδώ είναι αδύνατο γιατί το Session δεν το γνωρίζει καν.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

from ..config import PDF_SUFFIX, Settings
from .storage import PDF_MAGIC

log = logging.getLogger(__name__)

_FORMAT_SUFFIXES = ("/pdf", "/myDATA", "/EN16931")


class ProviderError(Exception):
    message_el = "Σφάλμα παρόχου"
    retryable = False


class ProviderNotFound(ProviderError):
    message_el = "Το PDF δεν βρέθηκε στον πάροχο"
    retryable = False


class ProviderAuthRequired(ProviderError):
    message_el = "Ο πάροχος ζητά σύνδεση"
    retryable = False


class ProviderUnavailable(ProviderError):
    message_el = "Ο πάροχος δεν αποκρίνεται"
    retryable = True


class ProviderRateLimited(ProviderError):
    message_el = "Προσωρινός περιορισμός από τον πάροχο"
    retryable = True

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("rate limited")
        self.retry_after = retry_after


class NotAPdf(ProviderError):
    message_el = "Ο πάροχος επέστρεψε σελίδα, όχι PDF"
    retryable = False


class IncompleteDownload(ProviderError):
    message_el = "Ατελής λήψη"
    retryable = True


@dataclass
class PdfResult:
    payload: bytes
    url: str


def pdf_url(base: str) -> str:
    """Προσθέτει /pdf αν δεν υπάρχει ήδη μορφότυπος.

    Το επίσημο PDF της ΑΑΔΕ (σελ. 31) λέει ότι χωρίς παράμετρο επιστρέφεται
    PDF. Μετρημένα, Epsilon και Impact επιστρέφουν HTML σελίδα προβολής, οπότε
    το suffix είναι υποχρεωτικό — όχι προαιρετικό.
    """
    trimmed = base.rstrip("/")
    if trimmed.endswith(_FORMAT_SUFFIXES):
        return trimmed
    return trimmed + PDF_SUFFIX


class ProviderDownloader:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session = requests.Session()  # σκόπιμα χωρίς auth headers
        self._session.headers.update({"Accept": "application/pdf,*/*"})

    def close(self) -> None:
        self._session.close()

    def fetch_pdf(self, url: str) -> PdfResult:
        target = pdf_url(url)
        try:
            resp = self._session.get(
                target, timeout=self._settings.provider_timeout, allow_redirects=True
            )
        except requests.Timeout as exc:
            raise ProviderUnavailable("timeout") from exc
        except requests.RequestException as exc:
            raise ProviderUnavailable(str(exc)) from exc

        if resp.status_code in (404, 410):
            raise ProviderNotFound(f"HTTP {resp.status_code}")
        if resp.status_code in (401, 403):
            raise ProviderAuthRequired(f"HTTP {resp.status_code}")
        if resp.status_code == 429:
            ra = resp.headers.get("Retry-After")
            raise ProviderRateLimited(float(ra) if ra and ra.isdigit() else None)
        if resp.status_code >= 500:
            raise ProviderUnavailable(f"HTTP {resp.status_code}")
        if resp.status_code != 200:
            raise ProviderError(f"HTTP {resp.status_code}")

        payload = resp.content

        # Ο έλεγχος γίνεται στα bytes, όχι στο Content-Type: ο τύπος μπορεί να
        # λέει ψέματα, τα magic bytes όχι. (Ίδια λογική: etimologio.php:2645)
        if not payload.startswith(PDF_MAGIC):
            head = payload[:200].decode("utf-8", "replace")
            raise NotAPdf(f"content-type={resp.headers.get('Content-Type','?')} head={head!r}")

        declared = resp.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) != len(payload):
            raise IncompleteDownload(f"περίμενα {declared}, πήρα {len(payload)}")

        return PdfResult(payload=payload, url=target)

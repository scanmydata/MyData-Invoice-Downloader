"""Λήψη PDF από τα συστήματα των παρόχων.

ΑΣΦΑΛΕΙΑ: το Session εδώ φτιάχνεται σκόπιμα **χωρίς** auth headers. Τα
downloadingInvoiceUrl είναι capability URLs (περιέχουν μη-μαντεύσιμο token) και
δεν θέλουν αυθεντικοποίηση. Στέλνοντας το κλειδί ΑΑΔΕ σε τρίτο πάροχο θα ήταν
διαρροή· εδώ είναι αδύνατο γιατί το Session δεν το γνωρίζει καν.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

from ..config import PDF_SUFFIX, Settings
from .storage import PDF_MAGIC

log = logging.getLogger(__name__)

_FORMAT_SUFFIXES = ("/pdf", "/myDATA", "/EN16931")

#: Host κατάληξη όλων των υποτομέων της Epsilon (epsilondigital*.epsilonnet.gr).
_EPSILON_HOST = "epsilonnet.gr"

#: eskap.gr (ΕΣΚΑΠ): η σελίδα του παραστατικού είναι HTML με «χρώμιο» (μενού,
#: κουμπιά)· η καθαρή εκτυπώσιμη μορφή είναι πίσω από το κουμπί «Εκτύπωση» που
#: καλεί ``printPage('/invoice_print.php?authentication_code=…')``.
_ESKAP_HOST = "eskap.gr"
_ESKAP_PRINT_RE = re.compile(
    r"invoice_print\.php\?authentication_code=([A-Za-z0-9]+)", re.I
)

#: UA σαν browser: κάποιοι πάροχοι (eskap) γυρίζουν 403/άδειο χωρίς αυτό.
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _host_matches(netloc: str, host: str) -> bool:
    netloc = (netloc or "").lower()
    return netloc == host or netloc.endswith("." + host)


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

    Το ``/pdf`` μπαίνει ΚΑΙ σε συνδέσμους με query string. Επιβεβαιωμένο στη
    Megasoft (``…/invoiceinspect/qr?QrCode=…/``): με ``/pdf`` επιστρέφει
    κανονικό PDF (content-type application/pdf), ενώ χωρίς αυτό δίνει τη σελίδα
    QR-προβολής (HTML). Παλιότερα το παραλείπαμε για τα query URLs — λάθος: τα
    παραστατικά της Megasoft «κολλούσαν» ως «μόνο online» ενώ κατεβαίνουν άμεσα.
    Αν κάποιος πάροχος δεν υποστηρίζει το ``/pdf``, θα γυρίσει HTML και το
    παραστατικό θα σημειωθεί απλώς ως «μόνο online» — καμία ζημιά.
    """
    trimmed = base.rstrip("/")
    if trimmed.endswith(_FORMAT_SUFFIXES):
        return trimmed
    return trimmed + PDF_SUFFIX


def epsilon_pdf_url(url: str) -> str | None:
    """Άμεσο PDF endpoint της Epsilon, ή ``None`` αν το URL δεν είναι Epsilon.

    Η Epsilon **δεν** επιστρέφει PDF με το ``/pdf`` suffix — δίνει τη σελίδα
    προβολής (Blazor/DocViewer, πίσω από Cloudflare). Έχει όμως άμεσο REST
    endpoint που σερβίρει το **ίδιο** PDF χωρίς browser και χωρίς έλεγχο
    «είστε άνθρωπος»::

        /filedocument/getfile?fileType=2&documentId=<uuid>

    Μετρημένα, το ``fileType`` είναι: 0=JSON, 2=PDF, 3/4=XML. Το ``documentId``
    είναι το μη-μαντεύσιμο capability token — ίδιο μοντέλο εμπιστοσύνης με το
    downloadingInvoiceUrl, οπότε το endpoint δεν θέλει αυθεντικοποίηση.

    Δέχεται και τις δύο μορφές συνδέσμου της Epsilon:
    ``…/DocViewer/<uuid>`` και ``…/fd/<32-hex>:<n>`` (το δεύτερο μετατρέπεται
    στο πρώτο — 32 hex → UUID 8-4-4-4-12).

    ΠΡΟΣΟΧΗ: αρκετοί υποτομείς/tenants δεν εκθέτουν καθόλου server PDF (μόνο
    XML/JSON)· εκεί το endpoint γυρίζει 404 και το παραστατικό πέφτει στο
    browser πέρασμα ως «μόνο online».
    """
    p = urlparse(url)
    if not _host_matches(p.netloc, _EPSILON_HOST):
        return None
    docid: str | None = None
    if "/DocViewer/" in p.path:
        docid = p.path.split("/DocViewer/")[-1].strip("/") or None
    else:
        m = re.search(r"/fd/([^/?#]+)", p.path, re.I)
        if m:
            hexonly = re.sub(r"[^0-9a-fA-F]", "", m.group(1).split(":")[0])
            if len(hexonly) == 32:
                docid = (
                    f"{hexonly[0:8]}-{hexonly[8:12]}-{hexonly[12:16]}-"
                    f"{hexonly[16:20]}-{hexonly[20:32]}"
                )
    if not docid:
        return None
    return f"{p.scheme}://{p.netloc}/filedocument/getfile?fileType=2&documentId={docid}"


def is_eskap(url: str) -> bool:
    """Αν το URL ανήκει στην eskap.gr (ΕΣΚΑΠ)."""
    return _host_matches(urlparse(url).netloc, _ESKAP_HOST)


def eskap_print_url(
    url: str,
    *,
    session: requests.Session | None = None,
    timeout: float = 20.0,
) -> str | None:
    """Το URL της **καθαρής εκτυπώσιμης** σελίδας της eskap.gr, ή ``None``.

    Η σελίδα ``/invoice/<token>`` είναι πλήρες HTML με μενού/κουμπιά — αν την
    τυπώσουμε σε PDF, παίρνουμε τη σελίδα, όχι το τιμολόγιο. Το ίδιο το site
    δίνει «καθαρή» εκτυπώσιμη μορφή στο ``/invoice_print.php?authentication_code=…``
    (το URL του κουμπιού «Εκτύπωση»). Την εντοπίζουμε διαβάζοντας τη σελίδα και
    την επιστρέφουμε, ώστε ο headless browser να τυπώσει **αυτήν**.

    Δεν είναι PDF endpoint (γυρίζει HTML): γι' αυτό δεν μπαίνει στο ``fetch_pdf``
    — χρησιμοποιείται μόνο ως στόχος για το print-to-PDF του browser. Καμία
    παράκαμψη ελέγχου: η eskap δεν έχει έλεγχο «είστε άνθρωπος».
    """
    if not is_eskap(url):
        return None
    sess = session or requests.Session()
    try:
        resp = sess.get(
            url, timeout=timeout, allow_redirects=True,
            headers={"User-Agent": _BROWSER_UA},
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    match = _ESKAP_PRINT_RE.search(resp.text)
    if not match:
        return None
    p = urlparse(str(resp.url) or url)
    return (
        f"{p.scheme}://{p.netloc}"
        f"/invoice_print.php?authentication_code={match.group(1)}"
    )


class ProviderDownloader:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session = requests.Session()  # σκόπιμα χωρίς auth headers
        self._session.headers.update({"Accept": "application/pdf,*/*"})

    def close(self) -> None:
        self._session.close()

    def fetch_pdf(self, url: str) -> PdfResult:
        # Epsilon: άμεσο getfile endpoint (χωρίς browser). Αν ο πάροχος δεν έχει
        # server PDF (404), το μαρκάρουμε ως «μόνο online» (NotAPdf) ώστε να το
        # πιάσει το browser πέρασμα — όχι σκληρή αποτυχία.
        eps = epsilon_pdf_url(url)
        if eps is not None:
            return self._fetch(eps, missing_is_viewer=True)
        return self._fetch(pdf_url(url), missing_is_viewer=False)

    def _fetch(self, target: str, *, missing_is_viewer: bool) -> PdfResult:
        try:
            resp = self._session.get(
                target, timeout=self._settings.provider_timeout, allow_redirects=True
            )
        except requests.Timeout as exc:
            raise ProviderUnavailable("timeout") from exc
        except requests.RequestException as exc:
            raise ProviderUnavailable(str(exc)) from exc

        if resp.status_code in (404, 410):
            if missing_is_viewer:
                raise NotAPdf(f"HTTP {resp.status_code}: χωρίς server PDF")
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

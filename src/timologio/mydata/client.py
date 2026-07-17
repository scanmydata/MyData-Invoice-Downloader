"""HTTP client για τα myDATA REST endpoints.

Αμετάβλητος κανόνας: αυτό το module είναι το **μόνο** σημείο όπου στέλνονται
τα διαπιστευτήρια ΑΑΔΕ, και μόνο προς config.AADE_HOST. Το download/provider.py
έχει δικό του Session χωρίς auth headers, ώστε η διαρροή κλειδιού σε πάροχο να
είναι δομικά αδύνατη.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

import requests

from ..config import (
    AADE_HOST,
    URL_REQUEST_DOCS,
    URL_REQUEST_E3_INFO,
    URL_REQUEST_TRANSMITTED_DOCS,
    Settings,
)
from ..models import Classification, Direction, Document
from .e3 import parse_e3
from .errors import AuthError, RateLimitError, TransientError
from .parse import extract_cursors, parse_documents

log = logging.getLogger(__name__)


class MydataClient:
    def __init__(self, user: str, key: str, settings: Settings) -> None:
        if not user or not key:
            from .errors import MissingKeyError

            raise MissingKeyError("λείπουν διαπιστευτήρια")
        self._headers = {"aade-user-id": user, "Ocp-Apim-Subscription-Key": key}
        self._settings = settings
        self._session = requests.Session()

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> MydataClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get(self, url: str, params: dict[str, str]) -> bytes:
        if urlsplit(url).netloc != AADE_HOST:
            raise ValueError(f"Τα διαπιστευτήρια ΑΑΔΕ δεν στέλνονται στο {url!r}")
        try:
            resp = self._session.get(
                url, params=params, headers=self._headers, timeout=self._settings.aade_timeout
            )
        except requests.Timeout as exc:
            raise TransientError("timeout") from exc
        except requests.RequestException as exc:
            raise TransientError(str(exc)) from exc

        if resp.status_code == 403:
            # Μετρημένο: κενό body. Μην προσπαθήσεις να παρσάρεις XML.
            raise AuthError(resp.text[:200] if resp.content else "403 χωρίς σώμα απάντησης")
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            raise RateLimitError(float(retry_after) if retry_after else None)
        if resp.status_code >= 500:
            raise TransientError(f"HTTP {resp.status_code}")
        if resp.status_code != 200:
            raise TransientError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.content

    def fetch(
        self,
        direction: Direction,
        *,
        mark: str = "0",
        date_from: str | None = None,
        date_to: str | None = None,
        entity_vat: str | None = None,
    ) -> list[Document]:
        """Κατεβάζει όλα τα παραστατικά μιας κατεύθυνσης, με pagination.

        Το RequestTransmittedDocs παίρνει τον **ίδιο** βρόχο pagination με το
        RequestDocs. Το fetch.py:275-286 κάνει ένα μόνο GET χωρίς cursors, που
        σιωπηλά κόβει αποτελέσματα σε μεγάλα διαστήματα.
        """
        url = (
            URL_REQUEST_DOCS
            if direction is Direction.INCOMING
            else URL_REQUEST_TRANSMITTED_DOCS
        )
        current_mark = (mark or "0").strip() or "0"
        params: dict[str, str] = {"mark": current_mark}
        if date_from:
            params["dateFrom"] = date_from
        if date_to:
            params["dateTo"] = date_to
        if entity_vat:
            params["entityVatNumber"] = entity_vat

        collected: dict[str, Document] = {}
        resume_guard: set[str] = set()

        while True:
            payload = self._get(url, params)
            docs, cursors = parse_documents(payload, direction)

            page_max = current_mark
            for doc in docs:
                if doc.mark and doc.mark not in collected:
                    collected[doc.mark] = doc
                if doc.mark.isdigit() and int(doc.mark) > int(page_max or 0):
                    page_max = doc.mark

            npk, nrk = cursors["nextPartitionKey"], cursors["nextRowKey"]
            token = cursors["nextPartitionToken"]

            if npk or nrk:
                params.pop("nextPartitionToken", None)
                params["nextPartitionKey"] = npk
                params["nextRowKey"] = nrk
                continue

            if token:
                params.pop("nextPartitionKey", None)
                params.pop("nextRowKey", None)
                params["nextPartitionToken"] = token
                continue

            # Fallback (fetch.py:242-258): κατά καιρούς η ΑΑΔΕ παραλείπει τα
            # cursors ενώ υπάρχουν κι άλλες εγγραφές. Ξαναρωτάμε με το
            # μεγαλύτερο MARK της σελίδας ως νέο κατώφλι. Το resume_guard
            # αποτρέπει ατέρμονο βρόχο αν το ίδιο MARK ξαναγυρίσει.
            if docs and page_max and page_max != current_mark and page_max not in resume_guard:
                resume_guard.add(page_max)
                current_mark = page_max
                params = {"mark": current_mark}
                if date_from:
                    params["dateFrom"] = date_from
                if date_to:
                    params["dateTo"] = date_to
                if entity_vat:
                    params["entityVatNumber"] = entity_vat
                log.debug("Resume από MARK %s", current_mark)
                continue

            break

        return list(collected.values())

    def fetch_e3(
        self,
        *,
        mark: str = "0",
        date_from: str | None = None,
        date_to: str | None = None,
        entity_vat: str | None = None,
    ) -> dict[str, Classification]:
        """MARK -> κατάσταση χαρακτηρισμού.

        Επιστρέφει μόνο όσα MARK έχουν εγγραφή E3· τα υπόλοιπα μένουν UNKNOWN
        (δεν υπόκεινται σε χαρακτηρισμό εξόδων).

        Το fetch.py:299-302 διευρύνει το dateTo κατά 3 μήνες. Δεν χρειάζεται
        εδώ: το IssueDate της εγγραφής E3 είναι η ημερομηνία έκδοσης του
        παραστατικού, οπότε το ίδιο παράθυρο επιστρέφει τα ίδια MARK
        (επιβεβαιωμένο: 29 εγγραφές E3 για 34 παραστατικά Ιουλίου).
        """
        params: dict[str, str] = {"mark": (mark or "0").strip() or "0"}
        if date_from:
            params["dateFrom"] = date_from
        if date_to:
            params["dateTo"] = date_to
        if entity_vat:
            params["entityVatNumber"] = entity_vat

        result: dict[str, Classification] = {}
        seen_tokens: set[str] = set()

        while True:
            payload = self._get(URL_REQUEST_E3_INFO, params)
            result.update(parse_e3(payload))

            from xml.etree import ElementTree as ET

            cursors = extract_cursors(ET.fromstring(payload))
            npk, nrk = cursors["nextPartitionKey"], cursors["nextRowKey"]
            token = cursors["nextPartitionToken"]

            if npk or nrk:
                signature = f"{npk}|{nrk}"
                if signature in seen_tokens:
                    break
                seen_tokens.add(signature)
                params.pop("nextPartitionToken", None)
                params["nextPartitionKey"] = npk
                params["nextRowKey"] = nrk
                continue
            if token:
                if token in seen_tokens:
                    break
                seen_tokens.add(token)
                params.pop("nextPartitionKey", None)
                params.pop("nextRowKey", None)
                params["nextPartitionToken"] = token
                continue
            break

        return result

"""Τύποι δεδομένων που περνούν ανάμεσα σε layers (και, στη Φάση 4, ανάμεσα σε threads)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DocStatus(StrEnum):
    PENDING = "pending"
    DOWNLOADED = "downloaded"
    NO_PROVIDER_URL = "no_provider_url"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_PERMANENT = "failed_permanent"
    SKIPPED_NO_KEY = "skipped_no_key"


class ClientStatus(StrEnum):
    READY = "ready"
    MISSING_KEY = "missing_key"
    DISABLED = "disabled"


class Direction(StrEnum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"
    BOTH = "both"


class Classification(StrEnum):
    """Κατάσταση χαρακτηρισμού από το RequestE3Info.

    Τρεις καταστάσεις, όχι δύο: η απουσία εγγραφής E3 δεν σημαίνει
    «αχαρακτήριστο» — σημαίνει ότι δεν υπόκειται σε χαρακτηρισμό εξόδων.
    """

    CLASSIFIED = "classified"
    UNCLASSIFIED = "unclassified"
    UNKNOWN = "unknown"


CLASSIFICATION_LABELS_EL = {
    Classification.CLASSIFIED: "Χαρακτηρισμένο",
    Classification.UNCLASSIFIED: "Αχαρακτήριστο",
    Classification.UNKNOWN: "—",
}

CLASSIFICATION_TOOLTIPS_EL = {
    Classification.CLASSIFIED: "Έχει χαρακτηριστεί στα Ηλεκτρονικά Βιβλία.",
    Classification.UNCLASSIFIED: "Η ΑΑΔΕ το αναφέρει ως «ΜΗ ΧΑΡΑΚΤΗΡΙΣΜΕΝΑ ΕΞΟΔΑ» — θέλει χαρακτηρισμό.",
    Classification.UNKNOWN: "Δεν υπάρχει στοιχείο E3 — δεν υπόκειται σε χαρακτηρισμό εξόδων.",
}


#: Ελληνικά μηνύματα κατάστασης για το UI/CLI.
STATUS_LABELS_EL = {
    DocStatus.PENDING: "Σε αναμονή",
    DocStatus.DOWNLOADED: "Ελήφθη",
    DocStatus.NO_PROVIDER_URL: "Χωρίς PDF παρόχου",
    DocStatus.FAILED_RETRYABLE: "Προσωρινό σφάλμα",
    DocStatus.FAILED_PERMANENT: "Οριστικό σφάλμα",
    DocStatus.SKIPPED_NO_KEY: "Λείπει κλειδί API",
}


@dataclass
class Client:
    vat: str
    label: str = ""
    office_code: str = ""
    mydata_user: str = ""
    mydata_key: str = ""
    source_file: str = ""
    id: int | None = None
    status: ClientStatus = ClientStatus.MISSING_KEY
    last_mark_incoming: str = "0"
    last_mark_outgoing: str = "0"

    def __repr__(self) -> str:  # τα credentials δεν εμφανίζονται ποτέ
        return f"Client(vat={self.vat!r}, label={self.label!r}, status={self.status!r})"


@dataclass
class Document:
    mark: str
    direction: Direction = Direction.INCOMING
    invoice_type: str = ""
    issuer_vat: str = ""
    issuer_name: str = ""
    counter_vat: str = ""
    counter_name: str = ""
    series: str = ""
    aa: str = ""
    issue_date: str = ""
    net_value: float = 0.0
    vat_amount: float = 0.0
    total_value: float = 0.0
    downloading_invoice_url: str = ""
    provider_host: str = ""
    classification: Classification = Classification.UNKNOWN
    xml_blob: bytes | None = field(default=None, repr=False)
    """Το raw <invoice> element — σώζεται μόνο όταν λείπει provider URL."""

    def counterparty(self, client_vat: str) -> tuple[str, str]:
        """(ΑΦΜ, επωνυμία) του «άλλου» σε σχέση με τον πελάτη.

        Χρειάζεται το ΑΦΜ του πελάτη: στα εισερχόμενα ο άλλος είναι ο εκδότης,
        στα εκδοθέντα ο λήπτης. Χωρίς αυτό, τα εκδοθέντα θα ονομάζονταν με το
        ΑΦΜ του ίδιου του πελάτη.
        """
        if self.issuer_vat and self.issuer_vat != client_vat:
            return self.issuer_vat, self.issuer_name
        if self.counter_vat and self.counter_vat != client_vat:
            return self.counter_vat, self.counter_name
        return self.issuer_vat or self.counter_vat, self.issuer_name or self.counter_name


@dataclass
class RunStats:
    docs_found: int = 0
    pdfs_ok: int = 0
    no_url: int = 0
    failed: int = 0
    skipped: int = 0

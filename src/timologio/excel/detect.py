"""Αναγνώριση μορφής και δημιουργία preview.

Το import δεν γράφει ποτέ κατευθείαν: πρώτα φτιάχνει preview με τι θα αλλάξει,
και ο χρήστης εγκρίνει. Στα αρχεία αυτά υπάρχουν εκατοντάδες πραγματικά
credentials — δεν εμφανίζεται ποτέ ολόκληρο μυστικό.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ..models import Client
from ..normalize import mask, valid_afm, valid_subscription_key
from . import format_a, format_b
from .reader import Sheet, read_workbook


class ExcelFormat(StrEnum):
    AADE_BLOCK = "aade_block"
    WIDE_TABLE = "wide_table"


FORMAT_LABELS_EL = {
    ExcelFormat.AADE_BLOCK: "Κωδικοί Υπηρεσιών μέσω Internet (ΑΑΔΕ)",
    ExcelFormat.WIDE_TABLE: "Κωδικοί Υπόχρεων (πλατύς πίνακας)",
}


class Action(StrEnum):
    NEW = "new"
    UPDATE = "update"
    UNCHANGED = "unchanged"


ACTION_LABELS_EL = {
    Action.NEW: "Νέος",
    Action.UPDATE: "Ενημέρωση",
    Action.UNCHANGED: "Αμετάβλητος",
}


@dataclass
class PreviewRow:
    client: Client
    action: Action
    warnings: list[str]

    @property
    def has_key(self) -> bool:
        return bool(self.client.mydata_key)

    def display(self) -> dict[str, str]:
        """Ασφαλής για εμφάνιση — τα μυστικά είναι μασκαρισμένα."""
        return {
            "afm": self.client.vat,
            "label": self.client.label[:40],
            "user": mask(self.client.mydata_user),
            "key": "✓ 32 χαρ." if self.has_key else "— λείπει",
            "action": ACTION_LABELS_EL[self.action],
            "warnings": "· ".join(self.warnings),
        }


@dataclass
class Preview:
    path: Path
    fmt: ExcelFormat
    rows: list[PreviewRow]

    @property
    def ready(self) -> int:
        return sum(1 for r in self.rows if r.has_key)

    @property
    def missing_key(self) -> int:
        return sum(1 for r in self.rows if not r.has_key)

    def summary_el(self) -> str:
        return (
            f"{len(self.rows)} πελάτες · {self.ready} έτοιμοι · "
            f"{self.missing_key} χωρίς κλειδί API"
        )


def detect(sheets: list[Sheet]) -> ExcelFormat:
    # Η Μορφή Α ελέγχεται πρώτη: έχει ξεκάθαρη υπογραφή (μπλοκ κωδικός+ΑΦΜ)
    # και δεν έχει καθόλου γραμμή επικεφαλίδων.
    if format_a.looks_like(sheets):
        return ExcelFormat.AADE_BLOCK
    if format_b.looks_like(sheets):
        return ExcelFormat.WIDE_TABLE
    raise ValueError(
        "Δεν αναγνωρίστηκε η μορφή του αρχείου. Υποστηρίζονται:\n"
        "  • «Κωδικοί Υπηρεσιών μέσω Internet» (εκτύπωση ΑΑΔΕ σε μπλοκ)\n"
        "  • «Κωδικοί Υπόχρεων» (πίνακας με στήλες «Α.Φ.Μ.», «Όνομα χρήστη "
        "myData», «Api myData»)"
    )


def _dedupe(clients: list[Client]) -> tuple[list[Client], dict[str, int]]:
    """Ίδιο ΑΦΜ πολλές φορές: κερδίζει η τελευταία μη-κενή τιμή."""
    order: list[str] = []
    merged: dict[str, Client] = {}
    counts: dict[str, int] = {}
    for client in clients:
        counts[client.vat] = counts.get(client.vat, 0) + 1
        if client.vat not in merged:
            merged[client.vat] = client
            order.append(client.vat)
            continue
        existing = merged[client.vat]
        existing.label = client.label or existing.label
        existing.office_code = client.office_code or existing.office_code
        existing.mydata_user = client.mydata_user or existing.mydata_user
        existing.mydata_key = client.mydata_key or existing.mydata_key
    return [merged[v] for v in order], {k: v for k, v in counts.items() if v > 1}


def build_preview(path: Path | str, conn: sqlite3.Connection | None = None) -> Preview:
    path = Path(path)
    sheets = read_workbook(path)
    fmt = detect(sheets)
    parser = format_a if fmt is ExcelFormat.AADE_BLOCK else format_b
    clients, dupes = _dedupe(parser.parse(sheets, source=path.name))

    existing: dict[str, sqlite3.Row] = {}
    if conn is not None:
        existing = {r["vat"]: r for r in conn.execute("SELECT * FROM clients")}

    rows: list[PreviewRow] = []
    for client in clients:
        warnings: list[str] = []
        if not client.vat:
            continue
        if not valid_afm(client.vat):
            warnings.append("ΑΦΜ δεν περνά τον έλεγχο")
        if client.mydata_key and not valid_subscription_key(client.mydata_key):
            warnings.append("το κλειδί δεν μοιάζει με 32-hex")
            client.mydata_key = ""
        if client.mydata_key and not client.mydata_user:
            warnings.append("κλειδί χωρίς όνομα χρήστη")
        if client.vat in dupes:
            warnings.append(f"{dupes[client.vat]} γραμμές για το ίδιο ΑΦΜ")

        prior = existing.get(client.vat)
        if prior is None:
            action = Action.NEW
        elif client.mydata_key or client.mydata_user or client.label:
            action = Action.UPDATE
        else:
            action = Action.UNCHANGED
        rows.append(PreviewRow(client=client, action=action, warnings=warnings))

    return Preview(path=path, fmt=fmt, rows=rows)

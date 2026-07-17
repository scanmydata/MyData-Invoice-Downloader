"""Μορφή Β — πλατύς πίνακας «Κωδικοί Υπόχρεων».

Μία γραμμή ανά πελάτη, ~83 στήλες, επικεφαλίδες στη γραμμή 1. Οι στήλες που
μας αφορούν (επιβεβαιωμένες):

    B  = Α.Φ.Μ.
    C  = Επωνυμία/Επώνυμο
    BG = Όνομα χρήστη myData        -> aade-user-id
    BI = Api myData                 -> Ocp-Apim-Subscription-Key
    BJ/BK/BL = e-timologio          -> ΑΛΛΟ προϊόν, δεν το αγγίζουμε

Διαβάζουμε **μόνο το πρώτο φύλλο**. Το «Sheet (2)» έχει 43 ΑΦΜ χωρίς καμία
στήλη myDATA και όλα υπάρχουν ήδη στο πρώτο· αν το μπλέκαμε, θα περνούσαμε
κενά credentials πάνω από καλά.

Το αρχείο περιέχει και δεκάδες άσχετους κωδικούς (Taxisnet, ΕΦΚΑ, ΙΚΑ, ΓΕΜΗ).
Το projection γίνεται εδώ, στο parse: αυτές οι στήλες δεν μπαίνουν ποτέ στη
μνήμη της εφαρμογής.
"""

from __future__ import annotations

from ..models import Client
from ..normalize import norm_afm, norm_text
from .aliases import field_for
from .reader import Sheet

#: Πόσες γραμμές ψάχνουμε για τη γραμμή επικεφαλίδων.
_HEADER_SCAN = 10


def find_header(sheet: Sheet) -> tuple[int, dict[str, str]] | None:
    """Βρίσκει τη γραμμή επικεφαλίδων και το mapping πεδίο -> στήλη.

    Απαιτεί ΑΦΜ και τουλάχιστον ένα από τα myDATA πεδία — αλλιώς είναι άλλο
    φύλλο (π.χ. το Sheet (2)).
    """
    for index in range(min(len(sheet.rows), _HEADER_SCAN)):
        mapping: dict[str, str] = {}
        for column, value in sheet.rows[index].items():
            field = field_for(value)
            if field and field not in mapping:
                mapping[field] = column
        if "afm" in mapping and ("mydata_user" in mapping or "mydata_key" in mapping):
            return index, mapping
    return None


def looks_like(sheets: list[Sheet]) -> bool:
    return bool(sheets) and find_header(sheets[0]) is not None


def parse(sheets: list[Sheet], source: str = "") -> list[Client]:
    if not sheets:
        return []
    sheet = sheets[0]  # μόνο το πρώτο φύλλο — βλ. docstring
    found = find_header(sheet)
    if not found:
        return []
    header_index, mapping = found

    clients: list[Client] = []
    for row in sheet.rows[header_index + 1 :]:
        vat = norm_afm(row.get(mapping["afm"], ""))
        if not vat:
            continue

        label = norm_text(row.get(mapping.get("name", ""), ""))
        if "first_name" in mapping:
            first = norm_text(row.get(mapping["first_name"], ""))
            if first:
                label = f"{label} {first}".strip()

        clients.append(
            Client(
                vat=vat,
                label=label,
                mydata_user=norm_text(row.get(mapping.get("mydata_user", ""), "")),
                mydata_key=norm_text(row.get(mapping.get("mydata_key", ""), "")),
                source_file=source,
            )
        )
    return clients

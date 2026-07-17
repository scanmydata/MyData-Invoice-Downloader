"""Μορφή Α — εκτύπωση ΑΑΔΕ «Κωδικοί Υπηρεσιών μέσω Internet».

Δεν είναι πίνακας αλλά μπλοκ ανά υπόχρεο:

    A14: «00250 ΤΟ ΨΑΡΙ Ο Ε 802576637»       <- κωδικός + επωνυμία + ΑΦΜ
    B16: «Taxis Net»                    E16=χρήστης  G16=συνθηματικό
    B18: «Ηλεκτρονικά Βιβλία Α.Α.Δ.Ε. (myDATA)»  E18=χρήστης  G18=κλειδί

Port του e3_brain.py:1321-1380. Το κρίσιμο που κρατάμε: οι τιμές παίρνονται
**θεσιακά ανάμεσα στα μη-κενά κελιά** (vals[1], vals[2]) και όχι από σταθερές
στήλες — γι' αυτό δουλεύει παρότι οι τιμές κάθονται στις E/G ενώ η επικεφαλίδα
«Κωδικός» είναι στην H.

Δεν διαβάζουμε ποτέ τα Taxisnet credentials: ο parser κάνει projection μόνο σε
ό,τι χρειάζεται το REST API.
"""

from __future__ import annotations

import re

from ..models import Client
from ..normalize import norm_afm, norm_text
from .reader import Sheet

BLOCK = re.compile(r"^(\d{3,6})\s+(.+?)\s+(\d{9})$")

_MYDATA_LABELS = ("mydata", "ηλεκτρονικά βιβλία", "ηλεκτρονικα βιβλια")

#: Πόσες γραμμές μετά την κεφαλίδα μπλοκ ψάχνουμε για credentials.
_BLOCK_SPAN = 10


def looks_like(sheets: list[Sheet]) -> bool:
    for sheet in sheets:
        for i in range(min(len(sheet.rows), 80)):
            if BLOCK.match(norm_text(sheet.row_text(i))):
                return True
    return False


def parse(sheets: list[Sheet], source: str = "") -> list[Client]:
    clients: list[Client] = []
    for sheet in sheets:
        i = 0
        while i < len(sheet.rows):
            match = BLOCK.match(norm_text(sheet.row_text(i)))
            if not match:
                i += 1
                continue

            code, name, afm = match.group(1), norm_text(match.group(2)), match.group(3)
            user = key = ""

            j = i + 1
            while j < min(i + _BLOCK_SPAN, len(sheet.rows)):
                text = norm_text(sheet.row_text(j))
                if j > i + 1 and BLOCK.match(text):
                    break  # ξεκίνησε το επόμενο μπλοκ
                low = text.lower()
                if any(label in low for label in _MYDATA_LABELS):
                    values = sheet.row_values(j)
                    if len(values) >= 3:
                        user, key = norm_text(values[1]), norm_text(values[2])
                j += 1

            clients.append(
                Client(
                    vat=norm_afm(afm),
                    label=name,
                    office_code=code,
                    mydata_user=user,
                    mydata_key=key,
                    source_file=source,
                )
            )
            i = j
    return clients

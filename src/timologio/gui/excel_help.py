"""Από πού βγαίνει το Excel με τους κωδικούς.

Ο λογιστής δεν πληκτρολογεί 150 κλειδιά — τα εξάγει από το πρόγραμμα που ήδη
χρησιμοποιεί. Οι διαδρομές όμως δεν είναι προφανείς και αλλάζουν ανά προϊόν,
οπότε τις έχουμε δίπλα στο ίδιο το κουμπί της εισαγωγής αντί να τις κρύβουμε
στο εγχειρίδιο.

Οι δύο εξαγωγές αντιστοιχούν ακριβώς στις δύο μορφές που αναγνωρίζει το
`timologio.excel`: η «Κωδικοί Υπηρεσιών μέσω Internet» είναι η εκτύπωση σε
μπλοκ (Μορφή Α) και η «Κωδικοί Υπόχρεων» ο πλατύς πίνακας (Μορφή Β).
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from .icons import icon
from .theme import CURRENT


@dataclass(frozen=True)
class Source:
    program: str
    steps: list[str]
    produces: str
    url: str


#: Οι πηγές, όπως τις τεκμηριώνει η ίδια η Epsilon Net.
SOURCES: list[Source] = [
    Source(
        program="Hyper / Extra Λογιστική",
        steps=[
            "Παράμετροι → Εταιρεία → <b>Εκτύπωση Κωδικών Υπηρεσιών μέσω Internet</b>",
            "Η εκτύπωση είναι διεταιρική: περιλαμβάνει τους κωδικούς σύνδεσης "
            "για κάθε εταιρεία.",
            "Στην προεπισκόπηση, πατήστε <b>Εξαγωγή</b> και επιλέξτε "
            "<b>Excel</b> (κουμπί με το εικονίδιο του Excel)· αποθηκεύστε το "
            "αρχείο .xlsx.",
        ],
        produces="«Κωδικοί Υπηρεσιών μέσω Internet» (μπλοκ ή Excel)",
        url="https://kb.epsilonnet.gr/ld/dietairiki-ektyposi-kodikon-syndesis/",
    ),
    Source(
        program="TaxSystem",
        steps=[
            "Κεντρικό Μενού → Εκτυπώσεις → <b>Κωδικοί e-Υπηρεσιών</b>",
            "Πατήστε <b>Επιλογή Όλων</b>",
            "Πατήστε <b>Εξαγωγή σε Excel</b>",
            "Δώστε όνομα αρχείου και θέση αποθήκευσης και πατήστε <b>Save</b>",
        ],
        produces="«Κωδικοί Υπόχρεων» (πλατύς πίνακας)",
        url=(
            "https://kb.epsilonnet.gr/taxsystem/"
            "pos-mporo-na-kano-exagogi-kodikon-mazika-gia-toys-ypochreoys/"
        ),
    ),
]


def as_html() -> str:
    """Οι οδηγίες ως HTML — το ίδιο κείμενο μπαίνει και στο εγχειρίδιο."""
    blocks: list[str] = []
    for source in SOURCES:
        steps = "".join(f"<li>{step}</li>" for step in source.steps)
        blocks.append(
            f'<p style="margin-bottom:2px;"><b style="color:{CURRENT.accent};">'
            f"{source.program}</b></p>"
            f"<ol style='margin-top:0;'>{steps}</ol>"
            f'<p style="color:{CURRENT.muted}; margin-top:0;">Δίνει: '
            f"{source.produces} &middot; "
            f'<a href="{source.url}">οδηγίες με εικόνες</a></p>'
        )
    return "".join(blocks)


class ExcelHelpDialog(QDialog):
    """Μικρό παράθυρο με τις διαδρομές εξαγωγής ανά πρόγραμμα."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Από πού βγάζω το Excel;")
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        header = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(icon("excel", CURRENT.ok, 26).pixmap(QSize(26, 26)))
        header.addWidget(mark)
        title = QLabel("Εξαγωγή κωδικών σε Excel")
        title.setObjectName("h1")
        header.addWidget(title, 1)
        root.addLayout(header)

        intro = QLabel(
            "Η εφαρμογή αναγνωρίζει μόνη της και τις δύο μορφές. Βγάλτε το "
            "αρχείο από το πρόγραμμά σας και μετά πατήστε «Εισαγωγή από Excel…»."
        )
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        root.addWidget(intro)

        body = QLabel(as_html())
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        # Χωρίς αυτά τα δύο ο σύνδεσμος δείχνει σαν σύνδεσμος αλλά δεν ανοίγει.
        body.setOpenExternalLinks(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        root.addWidget(body)

        note = QLabel(
            "Διαβάζονται μόνο τα πεδία myDATA. Οι υπόλοιποι κωδικοί (Taxisnet, "
            "ΕΦΚΑ, ΙΚΑ, ΓΕΜΗ) δεν φορτώνονται ποτέ στη μνήμη."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{CURRENT.muted};")
        root.addWidget(note)

        buttons = QDialogButtonBox()
        buttons.addButton("Κλείσιμο", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)


def show(parent=None) -> None:
    ExcelHelpDialog(parent).exec()

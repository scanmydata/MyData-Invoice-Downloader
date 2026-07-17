"""Διάλογος εισαγωγής Excel — preview πριν από κάθε εγγραφή."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..excel import FORMAT_LABELS_EL, Preview, build_preview

_COLUMNS = ["ΑΦΜ", "Επωνυμία", "Χρήστης", "Κλειδί API", "Ενέργεια", "Παρατηρήσεις"]


class ImportDialog(QDialog):
    """Δείχνει τι θα αλλάξει. Τα μυστικά εμφανίζονται πάντα μασκαρισμένα."""

    def __init__(self, path: Path, conn, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Εισαγωγή πελατών από Excel")
        self.resize(940, 560)
        self.preview: Preview | None = None

        layout = QVBoxLayout(self)

        try:
            self.preview = build_preview(path, conn)
        except ValueError as exc:
            QMessageBox.warning(self, "Μη αναγνωρίσιμο αρχείο", str(exc))
            self.reject()
            return
        except Exception as exc:
            QMessageBox.critical(self, "Σφάλμα ανάγνωσης", str(exc))
            self.reject()
            return

        header = QLabel(
            f"<b>{path.name}</b><br>"
            f"Μορφή: {FORMAT_LABELS_EL[self.preview.fmt]}<br>"
            f"<span style='font-size:14px'>{self.preview.summary_el()}</span>"
        )
        header.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(header)

        if self.preview.missing_key:
            note = QLabel(
                f"ℹ Οι {self.preview.missing_key} πελάτες χωρίς «Api myData» θα "
                "εισαχθούν αλλά δεν μπορούν να κατεβάσουν παραστατικά. Το κλειδί "
                "εκδίδεται ανά υπόχρεο από το taxisnet."
            )
            note.setWordWrap(True)
            note.setStyleSheet("color:#8a6d00; background:#fff8e1; padding:6px;")
            layout.addWidget(note)

        self.table = QTableWidget(len(self.preview.rows), len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        for row_index, row in enumerate(self.preview.rows):
            data = row.display()
            values = [
                data["afm"], data["label"], data["user"],
                data["key"], data["action"], data["warnings"],
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 3 and not row.has_key:
                    item.setForeground(QColor("#b00020"))
                if data["warnings"]:
                    item.setBackground(QColor("#fff8e1"))
                self.table.setItem(row_index, col, item)

        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table)

        buttons = QDialogButtonBox()
        self._ok = buttons.addButton(
            f"Εισαγωγή {len(self.preview.rows)} πελατών",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        buttons.addButton("Άκυρο", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        footer = QHBoxLayout()
        footer.addWidget(QLabel("Τίποτα δεν γράφεται πριν πατήσετε Εισαγωγή."))
        footer.addStretch()
        footer.addWidget(buttons)
        layout.addLayout(footer)

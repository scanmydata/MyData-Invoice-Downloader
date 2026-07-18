"""Παράθυρο κοινής χρήσης του φακέλου δεδομένων.

Ο στόχος είναι ένα κλικ αντί για επτά βήματα στα Windows. Αυτό όμως δεν
σημαίνει «χωρίς να το καταλάβει ο χρήστης»: μοιράζουμε στο δίκτυο έναν φάκελο
με φορολογικά δεδομένα και κλειδιά ΑΑΔΕ. Το παράθυρο λέει ρητά τι θα γίνει,
ποιοι θα έχουν πρόσβαση, και προτείνει κύριο κωδικό πριν από αυτό.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .. import sharing
from .icons import icon
from .theme import CURRENT

#: Ποιος θα μπορεί να συνδεθεί. Το «Everyone» είναι το μόνο που δουλεύει σε
#: workgroup χωρίς κοινούς λογαριασμούς — και το μόνο που καταλαβαίνει ο
#: λογιστής. Το λέμε όμως καθαρά τι σημαίνει.
_ACCOUNTS = [
    ("Everyone", "Όλοι στο τοπικό δίκτυο (συνηθισμένο σε γραφείο)"),
    ("Authenticated Users", "Μόνο όσοι έχουν λογαριασμό σε αυτόν τον υπολογιστή"),
]


class ShareDialog(QDialog):
    def __init__(self, data_dir: Path, has_master_password: bool, parent=None) -> None:
        super().__init__(parent)
        self._data_dir = data_dir
        self.setWindowTitle("Κοινή χρήση φακέλου")
        self.setMinimumWidth(560)

        self._existing = sharing.find_share_for(data_dir)

        root = QVBoxLayout(self)
        root.setSpacing(12)

        header = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(icon("network", CURRENT.accent, 26).pixmap(QSize(26, 26)))
        header.addWidget(mark)
        title = QLabel("Κοινή χρήση φακέλου δεδομένων")
        title.setObjectName("h1")
        header.addWidget(title, 1)
        root.addLayout(header)

        intro = QLabel(
            "Τα τερματικά του γραφείου θα βλέπουν αυτόν τον φάκελο μέσω δικτύου. "
            "Η εφαρμογή θα ρυθμίσει την κοινή χρήση, τα δικαιώματα εγγραφής και "
            "το τείχος προστασίας."
        )
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        root.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(8)

        self.folder = QLabel(str(data_dir))
        self.folder.setWordWrap(True)
        form.addRow("Φάκελος:", self.folder)

        self.name = QLineEdit(
            self._existing.name if self._existing else sharing.suggest_name(data_dir)
        )
        self.name.setToolTip("Το όνομα που θα πληκτρολογούν τα τερματικά")
        self.name.textChanged.connect(self._update_preview)
        form.addRow("Όνομα κοινής χρήσης:", self.name)

        self.account = QComboBox()
        for value, label in _ACCOUNTS:
            self.account.addItem(label, value)
        form.addRow("Ποιοι θα έχουν πρόσβαση:", self.account)
        root.addLayout(form)

        # Η διαδρομή που πρέπει να δοθεί στα τερματικά — το μόνο πράγμα που
        # χρειάζεται να μεταφερθεί σωστά, οπότε γίνεται και αντιγραφή.
        path_row = QHBoxLayout()
        self.preview = QLineEdit()
        self.preview.setReadOnly(True)
        self.preview.setObjectName("mono")
        path_row.addWidget(self.preview, 1)
        self.btn_copy = QPushButton("Αντιγραφή")
        self.btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy.setToolTip("Αντιγραφή της διαδρομής για τα τερματικά")
        self.btn_copy.clicked.connect(self._copy)
        path_row.addWidget(self.btn_copy)
        root.addWidget(QLabel("Διαδρομή για τα τερματικά:"))
        root.addLayout(path_row)

        self.warning = QLabel()
        self.warning.setWordWrap(True)
        root.addWidget(self.warning)
        self._set_warning(has_master_password)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setVisible(False)
        root.addWidget(self.status)

        buttons = QDialogButtonBox()
        self.btn_share = buttons.addButton(
            "Διακοπή κοινής χρήσης" if self._existing else "Κοινή χρήση",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        if self._existing:
            self.btn_share.setObjectName("danger")
        else:
            self.btn_share.setObjectName("primary")
        self.btn_share.clicked.connect(self._apply)
        buttons.addButton("Κλείσιμο", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._update_preview()

    # ------------------------------------------------------------------ UI
    def _set_warning(self, has_master_password: bool) -> None:
        if has_master_password:
            self.warning.setText(
                f'<span style="color:{CURRENT.ok};">✓</span> Ο φάκελος '
                "προστατεύεται με κύριο κωδικό: ακόμη κι αν κάποιος αντιγράψει "
                "τα αρχεία, τα κλειδιά ΑΑΔΕ δεν διαβάζονται χωρίς αυτόν."
            )
            return
        self.warning.setText(
            f'<span style="color:{CURRENT.warn};">⚠</span> <b>Δεν έχετε ορίσει '
            "κύριο κωδικό.</b> Όποιος έχει πρόσβαση στο δίκτυο θα μπορεί να "
            "αντιγράψει τη βάση <i>και</i> το κλειδί κρυπτογράφησης, άρα και "
            "τους κωδικούς myDATA των πελατών σας.<br>"
            "Ορίστε πρώτα κύριο κωδικό: μενού → ΑΣΦΑΛΕΙΑ → Κύριος κωδικός."
        )

    def _update_preview(self) -> None:
        name = self.name.text().strip()
        valid = sharing.is_valid_name(name)
        self.preview.setText(
            rf"\\{sharing.host_name()}\{name}" if valid else "—"
        )
        if not self._existing:
            self.btn_share.setEnabled(valid)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.preview.text())
        self.btn_copy.setText("Αντιγράφηκε")
        QTimer.singleShot(1500, lambda: self.btn_copy.setText("Αντιγραφή"))

    def _say(self, text: str, ok: bool) -> None:
        color = CURRENT.ok if ok else CURRENT.bad
        self.status.setText(f'<span style="color:{color};">{text}</span>')
        self.status.setVisible(True)

    # -------------------------------------------------------------- ενέργεια
    def _apply(self) -> None:
        if self._existing:
            script = sharing.build_unshare_script(self._existing.name)
            wanted_after = False
        else:
            name = self.name.text().strip()
            if not sharing.is_valid_name(name):
                self._say("Μη έγκυρο όνομα κοινής χρήσης.", False)
                return
            script = sharing.build_share_script(
                self._data_dir, name, self.account.currentData()
            )
            wanted_after = True

        self.btn_share.setEnabled(False)
        self._say("Ζητείται έγκριση διαχειριστή…", True)
        QApplication.processEvents()

        try:
            started = sharing.run_elevated(script)
        except sharing.NotWindows as exc:
            self._say(str(exc), False)
            self.btn_share.setEnabled(True)
            return

        if not started:
            self._say(
                "Η ενέργεια ακυρώθηκε — χρειάζονται δικαιώματα διαχειριστή.", False
            )
            self.btn_share.setEnabled(True)
            return

        # Δεν εμπιστευόμαστε την έξοδο του script: ρωτάμε τα ίδια τα Windows.
        QTimer.singleShot(1200, lambda: self._verify(wanted_after))

    def _verify(self, wanted: bool, attempt: int = 0) -> None:
        found = sharing.find_share_for(self._data_dir)
        if bool(found) == wanted:
            if wanted:
                self._existing = found
                self._say(
                    f"Έτοιμο. Δώστε στα τερματικά τη διαδρομή {found.unc}", True
                )
            else:
                self._existing = None
                self._say("Η κοινή χρήση διακόπηκε.", True)
            self.accept()
            return

        if attempt < 4:
            QTimer.singleShot(1000, lambda: self._verify(wanted, attempt + 1))
            return

        self._say(
            "Δεν επιβεβαιώθηκε η αλλαγή. Ελέγξτε αν εγκρίθηκε το παράθυρο "
            "διαχειριστή και δοκιμάστε ξανά.",
            False,
        )
        self.btn_share.setEnabled(True)

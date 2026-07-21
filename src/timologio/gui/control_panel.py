"""Πίνακας ελέγχου: ποιος είναι συνδεδεμένος και τι ακριβώς συμβαίνει.

Σε ένα γραφείο με server και τερματικά, οι ερωτήσεις που προκύπτουν στην πράξη
είναι πάντα οι ίδιες τρεις: «είμαι συνδεδεμένος;», «ποιος άλλος δουλεύει τώρα;»
και «γιατί μου λέει ότι τρέχει ήδη λήψη;». Μέχρι τώρα καμία δεν είχε απάντηση
μέσα από την εφαρμογή — ο χρήστης μάντευε από το αν έβλεπε πελάτες ή όχι.

Ο πίνακας ανανεώνεται μόνος του, αλλά ο έλεγχος σύνδεσης γίνεται μόνο όταν
ζητηθεί: αγγίζει το δίκτυο και σε χαλασμένο share μπλοκάρει για δευτερόλεπτα.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import presence, sharing, updates
from ..config import ROLE_LABELS_EL
from ..db import is_network_path
from ..locking import SyncLock
from . import updater
from .icons import icon
from .theme import CURRENT
from .widgets import ToggleSwitch

#: Κάθε πόσο ξαναζωγραφίζεται η λίστα συνδέσεων.
REFRESH_MS = 10_000


def _dot(online: bool) -> str:
    return "🟢" if online else "⚪"


class ControlPanel(QWidget):
    """Σελίδα «Πίνακας ελέγχου» μέσα στο κύριο παράθυρο."""

    #: Ο χρήστης άλλαξε το «εκκίνηση στο tray».
    start_minimized_changed = Signal(bool)
    #: Ζητήθηκε επανέλεγχος σύνδεσης (το κύριο παράθυρο ξαναφορτώνει τη λίστα).
    reconnect_requested = Signal()

    def __init__(
        self,
        *,
        data_dir: Path,
        db_path: Path,
        role: str,
        version: str,
        conn,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._data_dir = data_dir
        self._db_path = db_path
        self._role = role
        self._version = version
        self._conn = conn

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        root.addWidget(self._header())
        root.addWidget(self._identity_box())
        root.addWidget(self._peers_box(), 1)
        root.addWidget(self._settings_box())

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

        self.refresh()
        # Χωριστά από το refresh: κάθε έλεγχος ξεκινά PowerShell, που δεν αξίζει
        # να τρέχει κάθε δέκα δευτερόλεπτα για κάτι που αλλάζει σπάνια.
        QTimer.singleShot(0, self._refresh_share_state)

    # ------------------------------------------------------------------ UI
    def _header(self) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        mark = QLabel()
        mark.setPixmap(icon("network", CURRENT.accent, 24).pixmap(24, 24))
        row.addWidget(mark)

        title = QLabel("Πίνακας ελέγχου")
        title.setObjectName("h1")
        row.addWidget(title)
        row.addStretch()

        self.btn_updates = QPushButton("Έλεγχος για ενημερώσεις")
        self.btn_updates.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_updates.setToolTip(
            "Ρωτά το GitHub αν υπάρχει νεότερη έκδοση. Δεν κατεβαίνει τίποτα "
            "αυτόματα."
        )
        self.btn_updates.clicked.connect(self.check_updates)
        row.addWidget(self.btn_updates)

        self.btn_check = QPushButton("Έλεγχος σύνδεσης")
        self.btn_check.setObjectName("primary")
        self.btn_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_check.setToolTip(
            "Ελέγχει τον φάκελο, το δικαίωμα εγγραφής και τη βάση, ένα προς ένα"
        )
        self.btn_check.clicked.connect(self.run_check)
        row.addWidget(self.btn_check)
        return holder

    # -------------------------------------------------------- ενημερώσεις
    def check_updates(self) -> None:
        """Χειροκίνητος έλεγχος (κουμπί). Δίνει πάντα απάντηση, ακόμη κι όταν
        είμαστε ενημερωμένοι — αλλιώς ο χρήστης δεν ξέρει αν έγινε ο έλεγχος."""
        self.btn_updates.setEnabled(False)
        self.btn_updates.setText("Έλεγχος…")

        self._upd_thread = QThread(self)
        self._upd_worker = updater.CheckWorker(self._version)
        self._upd_worker.moveToThread(self._upd_thread)
        self._upd_thread.started.connect(self._upd_worker.run)
        self._upd_worker.ok.connect(self._on_update_result)
        self._upd_worker.failed.connect(self._on_update_failed)
        self._upd_thread.start()

    def _stop_upd_thread(self) -> None:
        thread = getattr(self, "_upd_thread", None)
        if thread is not None:
            thread.quit()
            thread.wait(3000)
        self._upd_thread = None
        self._upd_worker = None
        self.btn_updates.setEnabled(True)
        self.btn_updates.setText("Έλεγχος για ενημερώσεις")

    def _on_update_result(self, info) -> None:
        self._stop_upd_thread()
        if info.is_newer:
            updater.Updater(self.window()).offer(info)
        else:
            QMessageBox.information(
                self, "Ενημερωμένο",
                f"Έχετε την τελευταία έκδοση (<b>{info.current}</b>).",
            )

    def _on_update_failed(self, detail: str) -> None:
        self._stop_upd_thread()
        QMessageBox.warning(
            self, "Δεν ολοκληρώθηκε ο έλεγχος",
            "Δεν ήταν δυνατή η σύνδεση στο GitHub για έλεγχο ενημερώσεων.<br><br>"
            "Ελέγξτε τη σύνδεσή σας στο internet και δοκιμάστε ξανά, ή δείτε "
            f'απευθείας τη <a href="{updates.RELEASES_URL}">σελίδα εκδόσεων</a>.'
            f"<br><br><span style='color:gray'>{detail[:200]}</span>",
        )

    def _identity_box(self) -> QWidget:
        box = QGroupBox("Αυτός ο υπολογιστής")
        grid = QGridLayout(box)
        grid.setContentsMargins(14, 14, 14, 14)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(7)
        grid.setColumnStretch(1, 1)

        self._rows: dict[str, QLabel] = {}
        for index, name in enumerate(
            ["Ρόλος", "Όνομα υπολογιστή", "Φάκελος δεδομένων", "Βάση", "Κατάσταση λήψης"]
        ):
            key = QLabel(name)
            key.setObjectName("muted")
            value = QLabel("—")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(key, index, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(value, index, 1)
            self._rows[name] = value

        self.health = QLabel("")
        self.health.setWordWrap(True)
        self.health.setVisible(False)
        grid.addWidget(self.health, len(self._rows), 0, 1, 2)
        return box

    def _peers_box(self) -> QWidget:
        box = QGroupBox("Συνδέσεις")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        hint = QLabel(
            "Κάθε υπολογιστής που ανοίγει την εφαρμογή γράφει την παρουσία του "
            "στη βάση. «Ενεργός» σημαίνει ότι έδωσε σημείο ζωής το τελευταίο "
            "ενάμισι λεπτό."
        )
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        layout.addWidget(hint)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["", "Υπολογιστής", "Ρόλος", "Έκδοση", "Τελευταία δραστηριότητα"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)
        return box

    def _settings_box(self) -> QWidget:
        box = QGroupBox("Ρυθμίσεις δικτύου")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        self.chk_tray = ToggleSwitch("Εκκίνηση στο tray")
        self.chk_tray.setToolTip(
            "Η εφαρμογή ξεκινά χωρίς παράθυρο, ως εικονίδιο δίπλα στο ρολόι"
        )
        self.chk_tray.toggled.connect(self.start_minimized_changed.emit)
        layout.addWidget(self.chk_tray)

        note = QLabel(
            "Χρήσιμο στον server: μένει ανοιχτός ώστε ο φάκελος να είναι "
            "διαθέσιμος στα τερματικά, χωρίς να πιάνει χώρο στην επιφάνεια "
            "εργασίας. Διπλό κλικ στο εικονίδιο τον επαναφέρει."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)

        # Κοινή χρήση: μόνο όπου ο φάκελος είναι όντως εδώ. Ένα τερματικό δεν
        # μοιράζει τον φάκελο του server — τον χρησιμοποιεί.
        if self._role != "terminal":
            layout.addSpacing(6)
            share_row = QHBoxLayout()
            self.btn_share = QPushButton("Κοινή χρήση φακέλου…")
            self.btn_share.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_share.setToolTip(
                "Κάνει τον φάκελο προσβάσιμο από τα τερματικά του γραφείου"
            )
            self.btn_share.clicked.connect(self.open_share_dialog)
            share_row.addWidget(self.btn_share)

            self.share_state = QLabel("")
            self.share_state.setWordWrap(True)
            self.share_state.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            share_row.addWidget(self.share_state, 1)
            layout.addLayout(share_row)
        return box

    def open_share_dialog(self) -> None:
        from .share_dialog import ShareDialog

        dialog = ShareDialog(self._data_dir, self._has_master_password(), self)
        dialog.exec()
        self._refresh_share_state()

    def _has_master_password(self) -> bool:
        """Ώστε το παράθυρο να προειδοποιήσει πριν εκθέσει κλειδιά στο δίκτυο."""
        try:
            from ..crypto import is_protected

            return is_protected(self._data_dir / ".enckey")
        except Exception:  # pragma: no cover - η προειδοποίηση δεν πρέπει να σκάει
            return False

    def _refresh_share_state(self) -> None:
        if self._role == "terminal" or not hasattr(self, "share_state"):
            return
        share = sharing.find_share_for(self._data_dir)
        if share:
            self.share_state.setText(
                f'<span style="color:{CURRENT.ok};">✓ Κοινόχρηστος ως</span> '
                f"<b>{share.unc}</b>"
            )
            self.btn_share.setText("Ρυθμίσεις κοινής χρήσης…")
        else:
            self.share_state.setText(
                f'<span style="color:{CURRENT.muted};">Δεν είναι κοινόχρηστος — '
                "τα τερματικά δεν μπορούν να συνδεθούν.</span>"
                if self._role == "server"
                else ""
            )
            self.btn_share.setText("Κοινή χρήση φακέλου…")

    # -------------------------------------------------------------- δεδομένα
    def set_start_minimized(self, value: bool) -> None:
        """Χωρίς blockSignals θα γραφόταν ξανά η ίδια τιμή στο registry."""
        self.chk_tray.blockSignals(True)
        self.chk_tray.setChecked(value)
        self.chk_tray.blockSignals(False)

    def refresh(self) -> None:
        self._refresh_identity()
        self._refresh_peers()

    def _refresh_identity(self) -> None:
        self._rows["Ρόλος"].setText(ROLE_LABELS_EL.get(self._role, self._role))
        self._rows["Όνομα υπολογιστή"].setText(
            f"{presence.host_name()}\\{presence.user_name()}"
        )
        self._rows["Φάκελος δεδομένων"].setText(str(self._data_dir))

        if self._db_path.exists():
            size_mb = self._db_path.stat().st_size / (1024 * 1024)
            where = "δικτυακός φάκελος" if is_network_path(self._db_path) else "τοπικός δίσκος"
            self._rows["Βάση"].setText(f"{size_mb:.1f} MB · {where}")
        else:
            self._rows["Βάση"].setText("Δεν βρέθηκε")

        info = SyncLock(self._data_dir).read_info()
        if info:
            self._rows["Κατάσταση λήψης"].setText(
                f"Εκτελείται λήψη από «{info.holder}» (από {info.since})"
            )
        else:
            self._rows["Κατάσταση λήψης"].setText("Καμία λήψη σε εξέλιξη")

    def _refresh_peers(self) -> None:
        peers = presence.list_peers(self._conn)
        self.table.setRowCount(len(peers))
        for row, peer in enumerate(peers):
            label = peer.label + (" (αυτός ο υπολογιστής)" if peer.is_self else "")
            values = [
                _dot(peer.online),
                label,
                ROLE_LABELS_EL.get(peer.role, peer.role).split(" (")[0],
                peer.version or "—",
                f"{peer.ago_el()} · {peer.last_seen_local()}",
            ]
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                if not peer.online:
                    item.setForeground(Qt.GlobalColor.gray)
                self.table.setItem(row, column, item)

    # ---------------------------------------------------------------- έλεγχος
    def run_check(self) -> None:
        self.btn_check.setEnabled(False)
        try:
            health = presence.check_connection(self._data_dir, self._db_path)
        finally:
            self.btn_check.setEnabled(True)

        lines = [
            f"{'✓' if check.ok else '✗'} <b>{check.name}</b> — {check.detail}"
            for check in health.checks
        ]
        color = CURRENT.ok if health.ok else CURRENT.bad
        head = (
            "Η σύνδεση λειτουργεί."
            if health.ok
            else "Υπάρχει πρόβλημα σύνδεσης."
        )
        self.health.setText(
            f'<div style="color:{color};"><b>{head}</b></div>'
            + "<br>".join(lines)
        )
        self.health.setVisible(True)
        if health.ok:
            self.reconnect_requested.emit()

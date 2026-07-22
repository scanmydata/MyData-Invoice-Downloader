"""Σελίδα λήψης.

Ζει ανάμεσα στους «Πελάτες» και τα «Παραστατικά» στο μενού: εδώ ορίζεται η
περίοδος, ποιοι πελάτες και τι θα κατέβει, ώστε η λίστα πελατών να μένει καθαρή.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from PySide6.QtCore import QSettings, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import Direction
from .icons import icon
from .theme import CURRENT
from .widgets import GrDateEdit, resort, setup_columns

#: (επικεφαλίδα, πλάτος, tooltip). 0 = Stretch.
_COLS: list[tuple[str, int, str]] = [
    ("", 30, "Επιλέξτε ποιοι θα κατέβουν"),
    ("ΑΦΜ", 96, ""),
    ("Επωνυμία", 0, "Διπλό κλικ για επιλογή/αποεπιλογή"),
    ("Παρ.", 70, "Παραστατικά που έχουν ήδη ληφθεί"),
    ("Τελευταία", 100, "Πότε έγινε η τελευταία λήψη"),
]

#: Γρήγορες περίοδοι — ο λογιστής δουλεύει σχεδόν πάντα σε μία από αυτές.
_PRESETS: list[tuple[str, str]] = [
    ("Τρέχων μήνας", "month"),
    ("Προηγούμενος μήνας", "prev_month"),
    ("Τρέχον τρίμηνο", "quarter"),
    ("Προηγούμενο τρίμηνο", "prev_quarter"),
    ("Φέτος", "year"),
    ("Πέρσι", "prev_year"),
]


def _period(key: str) -> tuple[date, date]:
    today = date.today()
    if key == "month":
        return today.replace(day=1), today
    if key == "prev_month":
        first = today.replace(day=1)
        last_prev = first.fromordinal(first.toordinal() - 1)
        return last_prev.replace(day=1), last_prev
    if key == "quarter":
        start_month = 3 * ((today.month - 1) // 3) + 1
        return today.replace(month=start_month, day=1), today
    if key == "prev_quarter":
        # Αρχή τρέχοντος τριμήνου, πίσω μία ημέρα -> μέσα στο προηγούμενο τρίμηνο,
        # μετά η αρχή/τέλος εκείνου του τριμήνου (τέλος = αρχή τρέχοντος − 1 ημέρα).
        cur_start = today.replace(month=3 * ((today.month - 1) // 3) + 1, day=1)
        prev_end = cur_start.fromordinal(cur_start.toordinal() - 1)
        prev_start = prev_end.replace(month=3 * ((prev_end.month - 1) // 3) + 1, day=1)
        return prev_start, prev_end
    if key == "prev_year":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    return today.replace(month=1, day=1), today


class SyncPage(QWidget):
    """Ορισμός περιόδου και είδους, επιλογή πελατών, εκκίνηση λήψης."""

    sync_requested = Signal()
    cancel_requested = Signal()
    selection_changed = Signal(int)

    def __init__(self, prefs: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.checked: set[str] = set()
        self._prefs = prefs
        self._rows: list[sqlite3.Row] = []
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        header = QHBoxLayout()
        self.title_icon = QLabel()
        self.title_icon.setPixmap(
            icon("download", CURRENT.accent, 24).pixmap(QSize(24, 24))
        )
        header.addWidget(self.title_icon)
        title = QLabel("Λήψη παραστατικών")
        title.setObjectName("h1")
        header.addWidget(title)
        header.addStretch()
        root.addLayout(header)

        # --- περίοδος και είδος
        card = QFrame()
        card.setObjectName("card")
        box = QVBoxLayout(card)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(9)

        caption = QLabel("ΠΕΡΙΟΔΟΣ")
        caption.setObjectName("statLabel")
        box.addWidget(caption)

        presets = QHBoxLayout()
        presets.setSpacing(6)
        for text, key in _PRESETS:
            button = QPushButton(text)
            button.setToolTip(f"Ορισμός περιόδου: {text.lower()}")
            button.clicked.connect(lambda _=False, k=key: self._apply_preset(k))
            presets.addWidget(button)
        presets.addStretch()
        box.addLayout(presets)

        dates = QHBoxLayout()
        dates.setSpacing(7)
        dates.addWidget(QLabel("Από:"))
        self.date_from = GrDateEdit(date(date.today().year, 1, 1))
        self.date_from.setToolTip("Αρχή περιόδου έκδοσης")
        dates.addWidget(self.date_from)
        dates.addWidget(QLabel("Έως:"))
        self.date_to = GrDateEdit(date.today())
        self.date_to.setToolTip("Τέλος περιόδου έκδοσης")
        dates.addWidget(self.date_to)

        self.chk_full = QCheckBox("Πλήρης επανάληψη")
        self.chk_full.setToolTip(
            "Κανονικά η εφαρμογή ζητά μόνο ό,τι είναι νεότερο από την τελευταία\n"
            "λήψη, οπότε ένα δεύτερο τρέξιμο είναι σχεδόν ακαριαίο.\n\n"
            "Με την «Πλήρη επανάληψη» ξαναελέγχεται ΟΛΟ το διάστημα από την αρχή.\n"
            "Χρήσιμο αν υποψιάζεστε ότι λείπει κάτι.\n\n"
            "Τα ήδη κατεβασμένα αρχεία ΔΕΝ ξανακατεβαίνουν — απλώς αργεί λίγο."
        )
        dates.addWidget(self.chk_full)
        dates.addStretch()
        box.addLayout(dates)

        kinds = QHBoxLayout()
        kinds.setSpacing(7)
        kind_caption = QLabel("ΕΙΔΟΣ:")
        kind_caption.setObjectName("statLabel")
        kinds.addWidget(kind_caption)

        # Η ΑΑΔΕ δίνει τα δύο είδη από διαφορετικές κλήσεις — ζητώντας μόνο τη
        # μία, ο χρόνος της λήψης πέφτει στο μισό.
        self.chk_income = QCheckBox("Έσοδα (εκδοθέντα)")
        self.chk_income.setChecked(True)
        self.chk_income.setToolTip(
            "Τα παραστατικά που εξέδωσε ο πελάτης (RequestTransmittedDocs).\n\n"
            "Προσοχή: λίγα από αυτά (τύποι 13.x/14.x) τα υποβάλλει ο λήπτης και\n"
            "τελικά μετρώνται ως έξοδα — η κατάταξη γίνεται από το ΑΦΜ εκδότη."
        )
        self.chk_income.toggled.connect(lambda _: self._emit_target())
        kinds.addWidget(self.chk_income)

        self.chk_expense = QCheckBox("Έξοδα (ληφθέντα)")
        self.chk_expense.setChecked(True)
        self.chk_expense.setToolTip(
            "Τα παραστατικά που εξέδωσαν άλλοι προς τον πελάτη (RequestDocs)."
        )
        self.chk_expense.toggled.connect(lambda _: self._emit_target())
        kinds.addWidget(self.chk_expense)
        kinds.addStretch()
        box.addLayout(kinds)
        root.addWidget(card)

        # --- ποιοι πελάτες
        card2 = QFrame()
        card2.setObjectName("card")
        box2 = QVBoxLayout(card2)
        box2.setContentsMargins(14, 12, 14, 12)
        box2.setSpacing(8)

        row = QHBoxLayout()
        self.target = QLabel("—")
        self.target.setStyleSheet("font-size:15px; font-weight:600;")
        self.target.setWordWrap(True)
        row.addWidget(self.target, 1)

        self.btn_sync = QPushButton("  Έναρξη λήψης")
        self.btn_sync.setObjectName("primary")
        self.btn_sync.setIcon(icon("download", CURRENT.on_accent))
        self.btn_sync.setIconSize(QSize(18, 18))
        self.btn_sync.setMinimumHeight(38)
        self.btn_sync.setToolTip("Ξεκινά τη λήψη για τους επιλεγμένους πελάτες")
        self.btn_sync.clicked.connect(self.sync_requested.emit)
        row.addWidget(self.btn_sync)

        self.btn_cancel = QPushButton("Ακύρωση")
        self.btn_cancel.setObjectName("danger")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setMinimumHeight(38)
        self.btn_cancel.setToolTip("Διακοπή μετά τον τρέχοντα πελάτη")
        self.btn_cancel.clicked.connect(self.cancel_requested.emit)
        row.addWidget(self.btn_cancel)
        box2.addLayout(row)
        root.addWidget(card2)

        # --- λίστα πελατών με κλειδί
        head = QHBoxLayout()
        caption2 = QLabel("ΠΕΛΑΤΕΣ ΜΕ ΚΛΕΙΔΙ API")
        caption2.setObjectName("statLabel")
        head.addWidget(caption2)
        head.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Αναζήτηση…")
        self.search.setFixedWidth(200)
        self.search.setToolTip("Φιλτράρει τη λίστα καθώς πληκτρολογείτε")
        self.search.textChanged.connect(lambda _: self._fill())
        head.addWidget(self.search)
        for text, value, tip in [
            ("Επιλογή όλων", True, "Επιλέγει όσους δείχνει η λίστα"),
            ("Αποεπιλογή όλων", False, "Καθαρίζει τις επιλογές"),
        ]:
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, v=value: self._check_all(v))
            head.addWidget(button)
        root.addLayout(head)

        self.table = QTableWidget(0, len(_COLS))
        self.table.setHorizontalHeaderLabels([c[0] for c in _COLS])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(True)
        setup_columns(self.table, _COLS, self._prefs, "sync")
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.doubleClicked.connect(self._toggle_current)
        root.addWidget(self.table, 1)

    def _apply_preset(self, key: str) -> None:
        start, end = _period(key)
        self.date_from.set_gr(start.strftime("%d/%m/%Y"))
        self.date_to.set_gr(end.strftime("%d/%m/%Y"))

    # ------------------------------------------------------------- επιλογές
    def directions(self) -> tuple[Direction, ...]:
        """Ποιες κλήσεις της ΑΑΔΕ θα γίνουν, βάσει των δύο κουτιών."""
        out: list[Direction] = []
        if self.chk_expense.isChecked():
            out.append(Direction.INCOMING)
        if self.chk_income.isChecked():
            out.append(Direction.OUTGOING)
        return tuple(out)

    # ------------------------------------------------------- λίστα πελατών
    def load_clients(self, conn: sqlite3.Connection) -> None:
        """Μόνο όσοι έχουν κλειδί: εδώ η λίστα υπάρχει για να διαλέξεις ποιοι
        θα κατέβουν, και οι υπόλοιποι δεν μπορούν."""
        self._rows = list(
            conn.execute(
                """SELECT c.vat, c.label,
                          COALESCE(MAX(d.updated_at), '') AS last_run,
                          COUNT(d.id) AS docs
                   FROM clients c LEFT JOIN documents d ON d.client_id = c.id
                   WHERE c.status = 'ready'
                   GROUP BY c.id ORDER BY c.label, c.vat"""
            )
        )
        self._fill()

    def _fill(self) -> None:
        needle = self.search.text().strip().lower()
        rows = [
            r for r in getattr(self, "_rows", [])
            if not needle or needle in r["vat"] or needle in (r["label"] or "").lower()
        ]
        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                           | Qt.ItemFlag.ItemIsSelectable)
            check.setCheckState(
                Qt.CheckState.Checked if r["vat"] in self.checked
                else Qt.CheckState.Unchecked
            )
            check.setData(Qt.ItemDataRole.UserRole, r["vat"])
            self.table.setItem(i, 0, check)
            self.table.setItem(i, 1, QTableWidgetItem(r["vat"]))
            self.table.setItem(i, 2, QTableWidgetItem(r["label"] or "—"))
            docs = QTableWidgetItem(str(r["docs"] or 0))
            docs.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                  | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 3, docs)
            last = (r["last_run"] or "")[:10]
            when = QTableWidgetItem(
                f"{last[8:10]}/{last[5:7]}/{last[:4]}" if len(last) == 10 else "—"
            )
            when.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                  | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 4, when)
        self.table.setSortingEnabled(True)
        resort(self.table)
        self.table.blockSignals(False)
        self._emit_target()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        vat = item.data(Qt.ItemDataRole.UserRole)
        if not vat:
            return
        if item.checkState() is Qt.CheckState.Checked:
            self.checked.add(vat)
        else:
            self.checked.discard(vat)
        self._emit_target()

    def _toggle_current(self) -> None:
        """Διπλό κλικ οπουδήποτε στη γραμμή αλλάζει το checkbox."""
        rows = {i.row() for i in self.table.selectedIndexes()}
        self.table.blockSignals(True)
        for row in rows:
            item = self.table.item(row, 0)
            if item is None:
                continue
            checked = item.checkState() is Qt.CheckState.Checked
            item.setCheckState(
                Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked
            )
            vat = item.data(Qt.ItemDataRole.UserRole)
            if checked:
                self.checked.discard(vat)
            else:
                self.checked.add(vat)
        self.table.blockSignals(False)
        self._emit_target()

    def _check_all(self, value: bool) -> None:
        self.table.blockSignals(True)
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item is None:
                continue
            item.setCheckState(
                Qt.CheckState.Checked if value else Qt.CheckState.Unchecked
            )
            vat = item.data(Qt.ItemDataRole.UserRole)
            if value:
                self.checked.add(vat)
            else:
                self.checked.discard(vat)
        self.table.blockSignals(False)
        self._emit_target()

    def set_checked(self, vats: set[str]) -> None:
        self.checked = set(vats)
        self._fill()

    def _emit_target(self) -> None:
        # Η κοινή επιλογή (self.checked) μπορεί να περιέχει και πελάτες χωρίς
        # κλειδί — επιλέξιμους για διαγραφή στη σελίδα Πελατών, αλλά όχι για
        # λήψη. Εδώ μετράμε μόνο όσους όντως κατεβαίνουν (είναι στα _rows).
        ready = {r["vat"] for r in getattr(self, "_rows", [])}
        downloadable = len(self.checked & ready)
        self.set_target(downloadable, len(getattr(self, "_rows", [])))
        self.selection_changed.emit(downloadable)

    def set_target(self, selected: int, ready_total: int) -> None:
        """Δείχνει ρητά τι θα γίνει, πριν πατηθεί το κουμπί."""
        kinds = self.directions()
        if not kinds:
            self.target.setText("Επιλέξτε έσοδα ή έξοδα")
            self.target.setStyleSheet(
                f"font-size:15px; font-weight:600; color:{CURRENT.warn};"
            )
            self.btn_sync.setEnabled(False)
            return

        what = (
            "έσοδα και έξοδα" if len(kinds) == 2
            else "μόνο έσοδα" if Direction.OUTGOING in kinds
            else "μόνο έξοδα"
        )
        if selected:
            self.target.setText(f"Λήψη {what} για {selected} επιλεγμένους πελάτες")
            self.target.setStyleSheet(
                f"font-size:15px; font-weight:600; color:{CURRENT.accent};"
            )
        elif ready_total:
            self.target.setText(f"Λήψη {what} για όλους τους διαθέσιμους ({ready_total})")
            self.target.setStyleSheet(
                f"font-size:15px; font-weight:600; color:{CURRENT.ok};"
            )
        else:
            self.target.setText("Κανένας πελάτης με κλειδί API")
            self.target.setStyleSheet(
                f"font-size:15px; font-weight:600; color:{CURRENT.warn};"
            )
        self.btn_sync.setEnabled(bool(selected or ready_total))

    def restyle(self) -> None:
        self.btn_sync.setIcon(icon("download", CURRENT.on_accent))
        self.title_icon.setPixmap(
            icon("download", CURRENT.accent, 24).pixmap(QSize(24, 24))
        )
        self._emit_target()

    def set_running(self, running: bool) -> None:
        self.btn_sync.setEnabled(not running)
        self.btn_cancel.setEnabled(running)
        self.date_from.setEnabled(not running)
        self.date_to.setEnabled(not running)
        self.chk_full.setEnabled(not running)
        self.chk_income.setEnabled(not running)
        self.chk_expense.setEnabled(not running)
        self.table.setEnabled(not running)

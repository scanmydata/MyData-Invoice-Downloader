"""Πίνακας παραστατικών ενός πελάτη, με έξυπνα φίλτρα και εξαγωγή σε ZIP."""

from __future__ import annotations

import os
import sqlite3
import subprocess
from datetime import date
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings
from ..models import CLASSIFICATION_LABELS_EL, Classification, DocStatus
from ..reports import (
    count_without_pdf,
    documents_for,
    export_zip,
    invoice_types_of,
    suppliers_of,
)
from .icons import icon
from .theme import CURRENT, money
from .widgets import GrDateEdit, resort, setup_columns

#: (επικεφαλίδα, πλάτος, tooltip). 0 = Stretch.
_COLS: list[tuple[str, int, str]] = [
    ("", 30, "Επιλέξτε παραστατικά για εξαγωγή σε ZIP"),
    ("Ημ/νία", 88, "Ημερομηνία έκδοσης"),
    ("Ε/Ξ", 64, "Έσοδο (το εξέδωσε ο πελάτης) ή Έξοδο"),
    ("Τύπος", 54, "Τύπος παραστατικού κατά myDATA"),
    ("Αντισυμβαλλόμενος", 0, "Ο εκδότης (στα έξοδα) ή ο πελάτης του (στα έσοδα)"),
    ("ΑΦΜ", 82, ""),
    ("Σειρά", 66, ""),
    ("Α/Α", 58, "Αύξων αριθμός"),
    ("Καθαρή", 84, "Καθαρή αξία"),
    ("ΦΠΑ", 72, ""),
    ("Σύνολο", 88, "Συνολική αξία"),
    ("Χαρακτ.", 116, "Κατάσταση χαρακτηρισμού κατά RequestE3Info"),
    ("Κατάσταση", 104, "Αν κατέβηκε το PDF του παρόχου"),
    ("", 38, "Άνοιγμα αρχείου"),
]

#: Σύντομες ετικέτες για τον πίνακα. Οι πλήρεις (STATUS_LABELS_EL) θα έτρωγαν
#: 40px από τη στήλη της επωνυμίας για να πουν το ίδιο πράγμα· η πλήρης εξήγηση
#: μένει στο tooltip της κεφαλίδας.
_STATUS_SHORT = {
    DocStatus.DOWNLOADED: "Ελήφθη",
    DocStatus.NO_PROVIDER_URL: "Χωρίς PDF",
    DocStatus.VIEWER_ONLY: "Μόνο online",
    DocStatus.FAILED_RETRYABLE: "Σφάλμα",
    DocStatus.FAILED_PERMANENT: "Σφάλμα",
    DocStatus.SKIPPED_NO_KEY: "Χωρίς κλειδί",
    DocStatus.PENDING: "Αναμονή",
}

_COL_CHECK = 0
_COL_DATE = 1
_COL_KIND = 2
_COL_NET, _COL_VAT, _COL_GROSS = 8, 9, 10
_COL_OPEN = len(_COLS) - 1

#: Τρεις ανεξάρτητοι άξονες αντί για έναν κατάλογο αμοιβαία αποκλειόμενων
#: επιλογών: αλλιώς το «έξοδα ΚΑΙ ελήφθησαν PDF» ήταν αδύνατο να ζητηθεί.
KIND_FILTERS: list[tuple[str, str]] = [
    ("all", "Όλα"),
    ("income", "Έσοδα"),
    ("expense", "Έξοδα"),
]
STATUS_FILTERS: list[tuple[str, str]] = [
    ("all", "Όλα"),
    ("downloaded", "Ελήφθησαν PDF"),
    ("no_provider_url", "Χωρίς PDF παρόχου"),
    ("viewer_only", "Μόνο online προβολή"),
    ("failed", "Σφάλματα"),
    ("pending", "Σε αναμονή"),
]
CLS_FILTERS: list[tuple[str, str]] = [
    ("all", "Όλα"),
    ("unclassified", "Αχαρακτήριστα"),
    ("classified", "Χαρακτηρισμένα"),
    ("unknown_cls", "Χωρίς στοιχείο E3"),
]

#: Ποιο κουτί «κατέχει» κάθε κλειδί, ώστε ένα κλικ σε πλακίδιο της ανάλυσης να
#: πέσει στον σωστό άξονα.
_AXIS = {
    **{key: "kind" for key, _ in KIND_FILTERS},
    **{key: "status" for key, _ in STATUS_FILTERS},
    **{key: "cls" for key, _ in CLS_FILTERS},
}
_LABELS = dict(KIND_FILTERS + STATUS_FILTERS + CLS_FILTERS)

#: Το προεπιλεγμένο φίλτρο. Τα αχαρακτήριστα είναι η μόνη εκκρεμότητα που
#: απαιτεί δουλειά από τον λογιστή — ας τη δει αμέσως αντί να την ψάξει.
DEFAULT_FILTER = "unclassified"

_SORT_ROLE = Qt.ItemDataRole.UserRole + 1
_MARK_ROLE = Qt.ItemDataRole.UserRole + 2


def _cls_color(cls: Classification) -> str:
    # Συνάρτηση και όχι σταθερό dict: τα χρώματα αλλάζουν με το θέμα.
    return {
        Classification.CLASSIFIED: CURRENT.ok,
        Classification.UNCLASSIFIED: CURRENT.warn,
        Classification.UNKNOWN: CURRENT.muted,
    }[cls]


class SortableItem(QTableWidgetItem):
    """Κελί που εμφανίζει ένα κείμενο αλλά ταξινομείται με άλλη τιμή.

    Το QTableWidgetItem κρατά DisplayRole και EditRole στην ίδια θέση: ένα
    setData(EditRole, ...) αλλάζει και το εμφανιζόμενο κείμενο. Έτσι η
    «16/07/2026» γινόταν «2026-07-16» και το «3.348,05» γύριζε σε ωμό float.
    Κρατάμε λοιπόν το κλειδί ταξινόμησης σε δικό μας role.
    """

    def __init__(self, text: str, sort_key: object) -> None:
        super().__init__(text)
        self.setData(_SORT_ROLE, sort_key)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        mine = self.data(_SORT_ROLE)
        theirs = other.data(_SORT_ROLE)
        if mine is None or theirs is None:
            return super().__lt__(other)
        try:
            return mine < theirs
        except TypeError:
            return str(mine) < str(theirs)


class DocumentsView(QWidget):
    """Λίστα παραστατικών με φίλτρα, σύνολα, άνοιγμα αρχείου και εξαγωγή ZIP."""

    back_requested = Signal()

    def __init__(
        self, settings: Settings, prefs: QSettings, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._prefs = prefs
        self._conn: sqlite3.Connection | None = None
        self._vat = ""
        self._label = ""
        self._rows: list[sqlite3.Row] = []
        self._shown: list[sqlite3.Row] = []
        self._checked: set[str] = set()
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(7)
        self.btn_back = QPushButton(" Πελάτες")
        self.btn_back.setIcon(icon("back", CURRENT.muted))
        self.btn_back.setToolTip("Επιστροφή στη λίστα πελατών")
        self.btn_back.clicked.connect(self.back_requested.emit)
        bar.addWidget(self.btn_back)

        self.title_icon = QLabel()
        self.title_icon.setPixmap(icon("pdf", CURRENT.accent, 22).pixmap(QSize(22, 22)))
        bar.addWidget(self.title_icon)
        self.title = QLabel()
        self.title.setObjectName("h1")
        bar.addWidget(self.title)
        bar.addStretch()

        for text, value, tip in [
            ("Επιλογή όλων", True, "Επιλέγει όσα δείχνει η προβολή"),
            ("Αποεπιλογή όλων", False, "Καθαρίζει τις επιλογές"),
        ]:
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, v=value: self._check_all(v))
            bar.addWidget(button)

        self.btn_zip = QPushButton("  Εξαγωγή σε ZIP")
        self.btn_zip.setIcon(icon("backup", CURRENT.muted))
        self.btn_zip.setToolTip(
            "Πακετάρει τα αρχεία των επιλεγμένων παραστατικών σε ένα ZIP.\n"
            "Χωρίς επιλογή, μπαίνουν όσα δείχνει η τρέχουσα προβολή."
        )
        self.btn_zip.clicked.connect(self._export_zip)
        bar.addWidget(self.btn_zip)

        self.btn_print = QPushButton("  Μαζική εκτύπωση")
        self.btn_print.setIcon(icon("pdf", CURRENT.muted))
        self.btn_print.setToolTip(
            "Τυπώνει με μία εργασία τα PDF των επιλεγμένων παραστατικών.\n"
            "Χωρίς επιλογή, τυπώνονται όσα δείχνει η τρέχουσα προβολή.\n"
            "Μόνο όσα έχουν κατεβασμένο PDF μπαίνουν στην εκτύπωση."
        )
        self.btn_print.clicked.connect(self._print_selected)
        bar.addWidget(self.btn_print)
        root.addLayout(bar)

        # --- έξυπνα φίλτρα: δύο γραμμές, τρεις ανεξάρτητοι άξονες
        filters = QFrame()
        filters.setObjectName("card")
        rows = QVBoxLayout(filters)
        rows.setContentsMargins(12, 8, 12, 8)
        rows.setSpacing(7)

        # Πρώτη γραμμή: οι τρεις άξονες μαζί, ώστε να φαίνεται με μια ματιά ότι
        # συνδυάζονται — «Έξοδα» ΚΑΙ «Ελήφθησαν PDF» ΚΑΙ «Αχαρακτήριστα».
        first = QHBoxLayout()
        first.setSpacing(7)
        first.addWidget(QLabel("Είδος:"))
        self.combo_kind = self._combo(KIND_FILTERS, 100,
                                      "Έσοδα ή έξοδα, κατά ΑΦΜ εκδότη")
        first.addWidget(self.combo_kind)

        first.addWidget(QLabel("Λήψη:"))
        self.combo_status = self._combo(STATUS_FILTERS, 156,
                                        "Κατάσταση λήψης του PDF παρόχου")
        first.addWidget(self.combo_status)

        first.addWidget(QLabel("Χαρακτηρισμός:"))
        self.combo_cls = self._combo(CLS_FILTERS, 156,
                                     "Κατάσταση χαρακτηρισμού κατά RequestE3Info")
        first.addWidget(self.combo_cls)
        first.addStretch()

        self.btn_clear = QPushButton("Καθαρισμός")
        self.btn_clear.setToolTip("Επαναφορά όλων των φίλτρων")
        self.btn_clear.clicked.connect(self._clear_filters)
        first.addWidget(self.btn_clear)
        rows.addLayout(first)

        second = QHBoxLayout()
        second.setSpacing(7)
        second.addWidget(QLabel("Προμηθευτής:"))
        self.combo_supplier = QComboBox()
        self.combo_supplier.setMinimumWidth(180)
        self.combo_supplier.setToolTip("Μόνο τα παραστατικά ενός αντισυμβαλλόμενου")
        self.combo_supplier.currentIndexChanged.connect(lambda _: self.reload())
        second.addWidget(self.combo_supplier, 1)

        second.addWidget(QLabel("Τύπος:"))
        self.combo_type = QComboBox()
        self.combo_type.setFixedWidth(94)
        self.combo_type.setToolTip("Μόνο ένας τύπος παραστατικού")
        self.combo_type.currentIndexChanged.connect(lambda _: self.reload())
        second.addWidget(self.combo_type)

        self.chk_dates = QCheckBox("Διάστημα:")
        self.chk_dates.setToolTip("Ενεργοποίηση φίλτρου ημερομηνιών")
        self.chk_dates.toggled.connect(self._on_dates_toggled)
        second.addWidget(self.chk_dates)

        self.date_from = GrDateEdit(date(date.today().year, 1, 1))
        self.date_from.setEnabled(False)
        self.date_from.setToolTip("Μόνο παραστατικά από αυτή την ημερομηνία")
        self.date_from.dateChanged.connect(lambda _: self._on_date_changed())
        second.addWidget(self.date_from)

        second.addWidget(QLabel("–"))
        self.date_to = GrDateEdit(date.today())
        self.date_to.setEnabled(False)
        self.date_to.setToolTip("Μόνο παραστατικά έως αυτή την ημερομηνία")
        self.date_to.dateChanged.connect(lambda _: self._on_date_changed())
        second.addWidget(self.date_to)
        rows.addLayout(second)
        root.addWidget(filters)

        # Ένδειξη ότι η προβολή είναι φιλτραρισμένη — η προεπιλογή δείχνει μόνο
        # τα αχαρακτήριστα και αυτό πρέπει να είναι προφανές.
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        banner_box = QHBoxLayout(self.banner)
        banner_box.setContentsMargins(12, 7, 12, 7)
        self.banner_icon = QLabel()
        self.banner_icon.setPixmap(icon("info", CURRENT.accent, 16).pixmap(QSize(16, 16)))
        banner_box.addWidget(self.banner_icon)
        self.banner_text = QLabel("")
        self.banner_text.setStyleSheet(f"color:{CURRENT.accent}; font-weight:600;")
        banner_box.addWidget(self.banner_text)
        banner_box.addStretch()
        self.banner.setVisible(False)
        root.addWidget(self.banner)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Αναζήτηση επωνυμίας, ΑΦΜ, ΜΑΡΚ, σειράς…")
        self.search.setToolTip("Φιλτράρει όσα δείχνει ήδη ο πίνακας")
        self.search.textChanged.connect(lambda _: self._fill())
        root.addWidget(self.search)

        self.table = QTableWidget(0, len(_COLS))
        self.table.setHorizontalHeaderLabels([c[0] for c in _COLS])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(True)
        setup_columns(self.table, _COLS, self._prefs, "documents")
        self.table.doubleClicked.connect(lambda _: self._toggle_current())
        self.table.itemChanged.connect(self._on_item_changed)
        root.addWidget(self.table, 1)

        self.totals = QFrame()
        self.totals.setObjectName("card")
        row = QHBoxLayout(self.totals)
        row.setContentsMargins(14, 9, 14, 9)
        self._total_labels: dict[str, QLabel] = {}
        self._total_caption = QLabel("Παραστατικά")
        for key, caption in [
            ("count", "Παραστατικά"), ("net", "Καθαρή αξία"),
            ("vat", "ΦΠΑ"), ("gross", "Σύνολο"),
        ]:
            box = QVBoxLayout()
            cap = QLabel(caption)
            cap.setObjectName("statLabel")
            if key == "count":
                self._total_caption = cap
            val = QLabel("—")
            val.setStyleSheet("font-size:15px; font-weight:700;")
            box.addWidget(cap)
            box.addWidget(val)
            row.addLayout(box)
            row.addSpacing(22)
            self._total_labels[key] = val
        row.addStretch()
        root.addWidget(self.totals)

    def _combo(self, options: list[tuple[str, str]], width: int, tip: str) -> QComboBox:
        combo = QComboBox()
        combo.setFixedWidth(width)
        combo.setToolTip(tip)
        for key, label in options:
            combo.addItem(label, key)
        combo.currentIndexChanged.connect(lambda _: self.reload())
        return combo

    @property
    def _axis_combos(self) -> dict[str, QComboBox]:
        return {"kind": self.combo_kind, "status": self.combo_status,
                "cls": self.combo_cls}

    # ------------------------------------------------------------- δεδομένα
    def show_client(
        self,
        conn: sqlite3.Connection,
        vat: str,
        label: str,
        filter_key: str = DEFAULT_FILTER,
        *,
        supplier_vat: str = "",
        invoice_type: str = "",
    ) -> None:
        new_client = vat != self._vat
        self._conn = conn
        self._vat = vat
        self._label = label
        self.title.setText(f"{label}  ·  {vat}")

        combos = [*self._axis_combos.values(), self.combo_supplier, self.combo_type]
        for widget in combos:
            widget.blockSignals(True)
        if new_client:
            self._load_filter_options()
            self.chk_dates.setChecked(False)
            self.search.clear()
            self._checked.clear()

        # Ένα κλικ σε πλακίδιο σημαίνει «δείξε μου αυτά»: οι άλλοι άξονες
        # μηδενίζονται, αλλιώς το αποτέλεσμα θα ήταν σιωπηλά κομμένο από ένα
        # φίλτρο που ο χρήστης είχε ξεχάσει ανοιχτό.
        for axis, combo in self._axis_combos.items():
            wanted = filter_key if _AXIS.get(filter_key) == axis else "all"
            combo.setCurrentIndex(max(combo.findData(wanted), 0))
        self._select_data(self.combo_supplier, supplier_vat)
        self._select_data(self.combo_type, invoice_type)
        for widget in combos:
            widget.blockSignals(False)
        self.reload()

    @staticmethod
    def _select_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value) if value else 0
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _load_filter_options(self) -> None:
        assert self._conn is not None
        self.combo_supplier.clear()
        self.combo_supplier.addItem("Όλοι", "")
        for vat, name, count in suppliers_of(self._conn, self._vat):
            text = f"{name or '—'} ({count})" if name else f"{vat} ({count})"
            self.combo_supplier.addItem(text, vat)

        self.combo_type.clear()
        self.combo_type.addItem("Όλοι", "")
        for itype, count in invoice_types_of(self._conn, self._vat):
            self.combo_type.addItem(f"{itype} ({count})", itype)

    def _on_dates_toggled(self, enabled: bool) -> None:
        self.date_from.setEnabled(enabled)
        self.date_to.setEnabled(enabled)
        self.reload()

    def _on_date_changed(self) -> None:
        if self.chk_dates.isChecked():
            self.reload()

    def _clear_filters(self) -> None:
        for widget in [*self._axis_combos.values(), self.combo_supplier,
                       self.combo_type]:
            widget.blockSignals(True)
            widget.setCurrentIndex(0)
            widget.blockSignals(False)
        self.chk_dates.blockSignals(True)
        self.chk_dates.setChecked(False)
        self.date_from.setEnabled(False)
        self.date_to.setEnabled(False)
        self.chk_dates.blockSignals(False)
        self.search.clear()
        self.reload()

    def _active_keys(self) -> list[str]:
        return [
            combo.currentData()
            for combo in self._axis_combos.values()
            if (combo.currentData() or "all") != "all"
        ]

    def reload(self) -> None:
        if self._conn is None or not self._vat:
            return
        use_dates = self.chk_dates.isChecked()
        keys = self._active_keys()
        self._rows = documents_for(
            self._conn, self._vat,
            keys[0] if keys else "all",
            extra_filters=keys[1:],
            supplier_vat=self.combo_supplier.currentData() or "",
            invoice_type=self.combo_type.currentData() or "",
            date_from=self.date_from.gr() if use_dates else "",
            date_to=self.date_to.gr() if use_dates else "",
        )
        self._update_banner()
        self._fill()

    def _update_banner(self) -> None:
        """Λέει ρητά ότι η προβολή δεν δείχνει τα πάντα.

        Η προεπιλογή είναι τα αχαρακτήριστα· χωρίς ένδειξη, ο χρήστης θα νόμιζε
        ότι λείπουν παραστατικά.
        """
        keys = self._active_keys()
        if not keys:
            self.banner.setVisible(False)
            return
        what = " + ".join(_LABELS.get(k, k) for k in keys)
        self.banner_text.setText(
            f"Η προβολή δείχνει μόνο: {what}.  Πατήστε «Καθαρισμός» για όλα."
        )
        self.banner.setVisible(True)

    def _fill(self) -> None:
        needle = self.search.text().strip().lower()
        rows = self._rows
        if needle:
            rows = [
                r for r in rows
                if needle in (r["issuer_name"] or "").lower()
                or needle in (r["counter_name"] or "").lower()
                or needle in (r["issuer_vat"] or "")
                or needle in (r["counter_vat"] or "")
                or needle in r["mark"]
                or needle in (r["series"] or "").lower()
            ]

        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        net = vat_sum = gross = 0.0

        for i, r in enumerate(rows):
            net += r["net_value"] or 0
            vat_sum += r["vat_amount"] or 0
            gross += r["total_value"] or 0

            is_income = r["issuer_vat"] == self._vat
            other_vat = r["counter_vat"] if is_income else r["issuer_vat"]
            other_name = r["counter_name"] if is_income else r["issuer_name"]
            status = DocStatus(r["status"])
            cls = Classification(r["classification"] or "unknown")

            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                           | Qt.ItemFlag.ItemIsSelectable)
            check.setCheckState(
                Qt.CheckState.Checked if r["mark"] in self._checked
                else Qt.CheckState.Unchecked
            )
            check.setData(_MARK_ROLE, r["mark"])
            self.table.setItem(i, _COL_CHECK, check)

            cells = {
                _COL_DATE: _gr_date(r["issue_date"]),
                _COL_KIND: "Έσοδο" if is_income else "Έξοδο",
                3: r["invoice_type"] or "—",
                4: other_name or "—", 5: other_vat or "—",
                6: r["series"] or "—", 7: r["aa"] or "—",
                _COL_NET: money(r["net_value"] or 0),
                _COL_VAT: money(r["vat_amount"] or 0),
                _COL_GROSS: money(r["total_value"] or 0),
                11: CLASSIFICATION_LABELS_EL[cls],
                12: _STATUS_SHORT[status],
            }
            for col, text in cells.items():
                if col == _COL_DATE:
                    item = SortableItem(text, r["issue_date"] or "")
                elif col in (_COL_NET, _COL_VAT, _COL_GROSS):
                    amount = [r["net_value"], r["vat_amount"], r["total_value"]][
                        col - _COL_NET
                    ] or 0.0
                    item = SortableItem(text, float(amount))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                          | Qt.AlignmentFlag.AlignVCenter)
                else:
                    item = QTableWidgetItem(text)
                if col == _COL_KIND:
                    item.setForeground(QColor(CURRENT.ok if is_income else CURRENT.warn))
                if col == 11:
                    item.setForeground(QColor(_cls_color(cls)))
                if col == 12:
                    item.setForeground(QColor(_status_color(status)))
                item.setData(_MARK_ROLE, r["mark"])
                item.setToolTip(f"ΜΑΡΚ {r['mark']}")
                self.table.setItem(i, col, item)

            self.table.setCellWidget(i, _COL_OPEN, self._open_button(r))

        self.table.setSortingEnabled(True)
        resort(self.table, _COL_DATE)
        self.table.blockSignals(False)
        self._shown = rows
        self._total_labels["count"].setText(str(len(rows)))
        self._total_labels["net"].setText(f"{money(net)} €")
        self._total_labels["vat"].setText(f"{money(vat_sum)} €")
        self._total_labels["gross"].setText(f"{money(gross)} €")
        self._update_totals_caption()

    def _update_totals_caption(self) -> None:
        picked = len(self._checked)
        self._total_caption.setText(
            f"Παραστατικά ({picked} επιλεγμένα)" if picked else "Παραστατικά"
        )

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != _COL_CHECK:
            return
        mark = item.data(_MARK_ROLE)
        if not mark:
            return
        if item.checkState() is Qt.CheckState.Checked:
            self._checked.add(mark)
        else:
            self._checked.discard(mark)
        self._update_totals_caption()

    def _toggle_current(self) -> None:
        """Διπλό κλικ οπουδήποτε στη γραμμή αλλάζει το checkbox."""
        self.table.blockSignals(True)
        for row in {i.row() for i in self.table.selectedIndexes()}:
            item = self.table.item(row, _COL_CHECK)
            if item is None:
                continue
            checked = item.checkState() is Qt.CheckState.Checked
            item.setCheckState(
                Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked
            )
            mark = item.data(_MARK_ROLE)
            if checked:
                self._checked.discard(mark)
            else:
                self._checked.add(mark)
        self.table.blockSignals(False)
        self._update_totals_caption()

    def _check_all(self, value: bool) -> None:
        self.table.blockSignals(True)
        for i in range(self.table.rowCount()):
            item = self.table.item(i, _COL_CHECK)
            if item is None:
                continue
            item.setCheckState(
                Qt.CheckState.Checked if value else Qt.CheckState.Unchecked
            )
            mark = item.data(_MARK_ROLE)
            if value:
                self._checked.add(mark)
            else:
                self._checked.discard(mark)
        self.table.blockSignals(False)
        self._update_totals_caption()

    # ---------------------------------------------------------- αρχεία
    def _selected_rows(self) -> list[sqlite3.Row]:
        """Τα επιλεγμένα (checked) παραστατικά — ανεξάρτητα από ενεργά φίλτρα.

        Παίρνονται απευθείας από τη βάση κατά MARK, ώστε ένα φίλτρο αναζήτησης/
        είδους που κρύβει κάποια επιλεγμένα να μην τα αφήνει έξω από την ενέργεια.
        """
        if not self._checked or self._conn is None:
            return []
        from ..reports import documents_by_marks

        return documents_by_marks(self._conn, self._vat, sorted(self._checked))

    def _export_zip(self) -> None:
        rows = self._selected_rows() or getattr(self, "_shown", [])
        if not rows:
            QMessageBox.information(self, "Εξαγωγή", "Δεν υπάρχουν παραστατικά.")
            return

        # Για όσα δεν έχει δώσει PDF ο πάροχος υπάρχει το XML της ΑΑΔΕ. Άλλοι το
        # θέλουν (έχει εκδότη και αξίες), άλλοι στέλνουν το ZIP σε πελάτη και δεν
        # θέλουν να εξηγούν τι είναι το XML — ας το πει ο χρήστης.
        include_without_pdf = True
        without = count_without_pdf(rows)
        if without:
            answer = QMessageBox.question(
                self, "Παραστατικά χωρίς PDF",
                f"{without} από τα επιλεγμένα δεν έχουν PDF παρόχου.\n\n"
                "Να μπουν στο ZIP με το XML της ΑΑΔΕ;\n\n"
                "«Ναι» — μπαίνουν ως .xml\n"
                "«Όχι» — μπαίνουν μόνο τα PDF",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            include_without_pdf = answer == QMessageBox.StandardButton.Yes

        packable = [
            r for r in rows
            if r["local_path"] or (include_without_pdf and r["xml_path"])
        ]
        if not packable:
            QMessageBox.information(
                self, "Εξαγωγή",
                "Κανένα από τα επιλεγμένα παραστατικά δεν έχει αρχείο.",
            )
            return

        safe = "".join(c for c in self._label if c.isalnum() or c in " -_")[:40].strip()
        default = self._settings.data_dir / f"{self._vat} {safe}.zip".strip()
        path, _ = QFileDialog.getSaveFileName(
            self, f"Εξαγωγή {len(packable)} αρχείων σε ZIP", str(default), "ZIP (*.zip)"
        )
        if not path:
            return

        added, missing = export_zip(
            rows, self._settings.storage_root, Path(path),
            include_without_pdf=include_without_pdf,
        )
        note = f"\n\n{missing} παραστατικά δεν μπήκαν (χωρίς αρχείο)." if missing else ""
        QMessageBox.information(
            self, "Η εξαγωγή ολοκληρώθηκε",
            f"{added} αρχεία -> {Path(path).name}{note}",
        )

    def _print_selected(self) -> None:
        """Μαζική εκτύπωση των PDF των επιλεγμένων (ή, χωρίς επιλογή, όσων
        δείχνει η προβολή). Τυπώνονται μόνο όσα έχουν κατεβασμένο PDF — το XML
        της ΑΑΔΕ δεν έχει νόημα στον εκτυπωτή."""
        rows = self._selected_rows() or getattr(self, "_shown", [])
        if not rows:
            QMessageBox.information(self, "Εκτύπωση", "Δεν υπάρχουν παραστατικά.")
            return

        paths: list[Path] = []
        for r in rows:
            if r["local_path"]:
                candidate = self._settings.storage_root / r["local_path"]
                if candidate.exists():
                    paths.append(candidate)
        if not paths:
            QMessageBox.information(
                self, "Εκτύπωση",
                "Κανένα από τα επιλεγμένα παραστατικά δεν έχει κατεβασμένο PDF.\n\n"
                "Η μαζική εκτύπωση αφορά μόνο τα PDF — τα «μόνο online» ανοίγουν "
                "στον πάροχο και τυπώνονται από εκεί.",
            )
            return

        without = len(rows) - len(paths)
        if without:
            answer = QMessageBox.question(
                self, "Εκτύπωση",
                f"{len(paths)} παραστατικά έχουν PDF και θα τυπωθούν.\n"
                f"{without} δεν έχουν PDF και θα παραλειφθούν.\n\nΣυνέχεια;",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        # Το import είναι τοπικό: το QtPdf φορτώνεται μόνο όταν πραγματικά
        # τυπώνει κάποιος, όχι σε κάθε άνοιγμα της λίστας παραστατικών.
        from .printing import print_pdfs

        # Ανοίγει προεπισκόπηση· η εκτύπωση γίνεται από εκεί. Δεν δείχνουμε
        # μήνυμα «στάλθηκε» — το preview είναι η ίδια η επιβεβαίωση.
        prepared, failed = print_pdfs(paths, self)
        if failed and not prepared:
            QMessageBox.warning(
                self, "Εκτύπωση",
                "Κανένα από τα επιλεγμένα PDF δεν μπόρεσε να διαβαστεί.",
            )

    def _open_button(self, row: sqlite3.Row) -> QWidget:
        """Κουμπί ανοίγματος — ενεργό μόνο όταν υπάρχει όντως αρχείο."""
        path = row["local_path"] or row["xml_path"]
        holder = QWidget()
        box = QHBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)

        button = QPushButton()
        button.setObjectName("rowButton")
        button.setFixedSize(QSize(26, 24))
        online_url = (
            row["downloading_invoice_url"]
            if row["status"] == DocStatus.VIEWER_ONLY.value else ""
        )
        if path and (self._settings.storage_root / path).exists():
            is_pdf = bool(row["local_path"])
            button.setIcon(
                icon("pdf" if is_pdf else "csv",
                     CURRENT.ok if is_pdf else CURRENT.muted)
            )
            button.setToolTip(
                "Άνοιγμα του PDF" if is_pdf
                else "Άνοιγμα του XML (δεν υπάρχει PDF παρόχου)"
            )
            button.clicked.connect(lambda _=False, p=path: self._open(p))
        elif online_url:
            # Μόνο online: καθοδηγούμενη λήψη μέσω του browser, με αυτόματη
            # αρχειοθέτηση — ίδια ροή/αποθήκευση με το popup «Λήψη μόνο-online».
            button.setIcon(icon("link", CURRENT.accent))
            button.setToolTip(
                "Λήψη μόνο-online μέσω του browser σας (αποθηκεύεται αυτόματα)"
            )
            button.clicked.connect(lambda _=False, r=row: self._download_online_row(r))
        else:
            button.setIcon(icon("cancel", CURRENT.muted))
            button.setEnabled(False)
            button.setToolTip("Δεν υπάρχει αρχείο για αυτό το παραστατικό")
        box.addWidget(button)
        return holder

    def _download_online_row(self, row: sqlite3.Row) -> None:
        """Λήψη ενός «μόνο online» παραστατικού μέσω του browser (όπως το popup).

        Η γραμμή προέρχεται από `documents_for` που πλέον έχει `client_label` —
        ό,τι χρειάζεται ο διάλογος για την αρχειοθέτηση (`save_online_only_pdf`).
        """
        if self._conn is None:
            return
        from .online_only import OnlineOnlyDialog

        dialog = OnlineOnlyDialog(self._conn, self._settings, [row], self)
        dialog.exec()
        if dialog.changed:
            self.reload()

    def restyle(self) -> None:
        """Μετά από αλλαγή θέματος: εικονίδια και χρώματα κελιών."""
        self.btn_back.setIcon(icon("back", CURRENT.muted))
        self.btn_zip.setIcon(icon("backup", CURRENT.muted))
        self.btn_print.setIcon(icon("pdf", CURRENT.muted))
        self.title_icon.setPixmap(icon("pdf", CURRENT.accent, 22).pixmap(QSize(22, 22)))
        self.banner_icon.setPixmap(
            icon("info", CURRENT.accent, 16).pixmap(QSize(16, 16))
        )
        self.banner_text.setStyleSheet(f"color:{CURRENT.accent}; font-weight:600;")
        self._fill()

    def _open(self, relative: str) -> None:
        target = self._settings.storage_root / relative
        if not target.exists():
            return
        if os.name == "nt":
            os.startfile(target)  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(target)])


def _gr_date(iso: str) -> str:
    if not iso or len(iso) < 10:
        return iso or "—"
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"


def _status_color(status: DocStatus) -> str:
    return {
        DocStatus.DOWNLOADED: CURRENT.ok,
        DocStatus.NO_PROVIDER_URL: CURRENT.muted,
        DocStatus.VIEWER_ONLY: CURRENT.accent,
        DocStatus.FAILED_RETRYABLE: CURRENT.warn,
        DocStatus.FAILED_PERMANENT: CURRENT.bad,
        DocStatus.SKIPPED_NO_KEY: CURRENT.bad,
        DocStatus.PENDING: CURRENT.accent,
    }.get(status, CURRENT.muted)

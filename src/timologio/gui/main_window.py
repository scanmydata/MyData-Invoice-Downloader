"""Κύριο παράθυρο.

Ροή: Πελάτες (ποιοι) → Λήψη (πότε) → Παραστατικά (τι κατέβηκε). Ό,τι δεν είναι
αυτή η ροή ζει στο πλαϊνό μενού.
"""

from __future__ import annotations

import logging
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QSettings,
    QSize,
    Qt,
    QThread,
    QTimer,
)
from PySide6.QtGui import QAction, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtWidgets import QApplication, QCheckBox

from .. import logs, repo
from ..backup import create_backup, list_backups, restore
from ..config import load_settings
from ..coverage import to_gr
from ..crypto import Crypto
from ..db import init_db
from ..download.storage import find_client_folder
from ..reports import export_documents
from .analysis_panel import AnalysisPanel
from .busy import BusyOverlay
from .client_dialog import ClientDialog
from .documents_view import DEFAULT_FILTER, DocumentsView, SortableItem
from .icons import icon, logo_pixmap
from .import_dialog import ImportDialog
from .manual import ensure_manual
from .side_menu import SideMenu
from .sync_page import SyncPage
from .theme import CURRENT, apply_theme, money, paint_title_bar
from .tour import Step, Tour
from .widgets import resort, setup_columns
from .workers import SyncWorker

log = logging.getLogger(__name__)

#: (επικεφαλίδα, πλάτος, tooltip). 0 = Stretch.
_COLUMN_SPEC: list[tuple[str, int, str]] = [
    ("", 30, "Επιλέξτε για ποιους πελάτες θα γίνει λήψη"),
    ("ΑΦΜ", 84, ""),
    ("Επωνυμία", 0, "Διπλό κλικ για τα παραστατικά του πελάτη"),
    ("Κατάσταση", 96, "Αν ο πελάτης έχει κλειδί myDATA API"),
    ("Παρ.", 54, "Σύνολο παραστατικών"),
    ("PDF", 54, "Παραστατικά που κατέβηκαν ως PDF"),
    ("Αχαρ.", 54, "Αχαρακτήριστα κατά το RequestE3Info"),
    ("Έσοδα", 88, "Αξία όσων εξέδωσε ο πελάτης"),
    ("Έξοδα", 88, "Αξία όσων εξέδωσαν άλλοι προς αυτόν"),
]

#: Σύντομη ετικέτα: το «Λείπει κλειδί API» έτρωγε 110px για να πει το ίδιο.
_STATUS_READY = "Διαθέσιμος"
_STATUS_NO_KEY = "Χωρίς κλειδί"
_COLUMNS = [c[0] for c in _COLUMN_SPEC]
_COL_CHECK, _COL_VAT, _COL_LABEL, _COL_STATUS = 0, 1, 2, 3

_FILTERS = ["Όλοι", "Διαθέσιμοι", "Χωρίς κλειδί API", "Με αχαρακτήριστα"]

#: Η σειρά τους είναι η σειρά τους στο QStackedWidget.
_PAGES = ("clients", "sync", "documents")

#: Πλάτος του δεξιού panel όταν είναι ανοιχτό. Κάτω από ~400 ο πίνακας
#: εσόδων/εξόδων κόβεται στα δεξιά.
_PANEL_W = 440


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Λήψη Παραστατικών myDATA")
        self.resize(1340, 840)
        # Κάτω από αυτό, ο πίνακας πελατών (9 στήλες) και η ανάλυση δεν χωρούν
        # μαζί και εμφανίζεται οριζόντια μπάρα. Όποιος έχει μικρότερη οθόνη
        # μαζεύει το πλαϊνό μενού και κερδίζει 142 pixel.
        self.setMinimumSize(1180, 700)

        self.settings = load_settings()
        self.log_path = logs.setup(self.settings.data_dir)
        self.conn = init_db(self.settings.db_path)
        self.crypto = Crypto(self.settings.enckey_path)
        self._prefs = QSettings("scanmydata", "TimologioDownloader")
        self._thread: QThread | None = None
        self._worker: SyncWorker | None = None
        self._checked: set[str] = set()
        self._tooltips_on = True
        self._tour: Tour | None = None
        self._stale: set[str] = set()
        self._title_bar_done = False

        # Το θέμα εφαρμόζεται πριν χτιστούν τα widgets, ώστε τα εικονίδια να
        # βαφτούν σωστά από την πρώτη φορά. Προεπιλογή το σκούρο.
        theme = str(self._prefs.value("theme", "dark"))
        apply_theme(QApplication.instance(), theme)

        self._build_ui()
        self.menu.chk_light.blockSignals(True)
        self.menu.chk_light.setChecked(theme == "light")
        self.menu.chk_light.blockSignals(False)
        if self._prefs.value("menu_collapsed", False, type=bool):
            self.menu.set_collapsed(True, animate=False)
        self.busy = BusyOverlay(self)
        self.reload_clients()
        QTimer.singleShot(400, self._maybe_first_run_tour)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        self.menu = SideMenu()
        self.menu.triggered.connect(self._on_menu)
        self.menu.tooltips_toggled.connect(self._apply_tooltips)
        self.menu.theme_toggled.connect(self._on_theme)
        self.menu.collapsed_changed.connect(
            lambda value: self._prefs.setValue("menu_collapsed", value)
        )
        shell.addWidget(self.menu)

        right = QWidget()
        root = QVBoxLayout(right)
        root.setContentsMargins(12, 10, 12, 8)
        root.setSpacing(9)
        shell.addWidget(right, 1)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._clients_page())

        self.sync_page = SyncPage(self._prefs)
        self.sync_page.sync_requested.connect(self.on_sync)
        self.sync_page.cancel_requested.connect(self.on_cancel)
        self.sync_page.selection_changed.connect(self._on_sync_selection)
        self.stack.addWidget(self.sync_page)

        self.docs = DocumentsView(self.settings, self._prefs)
        self.docs.back_requested.connect(lambda: self._show_page("clients"))
        self.stack.addWidget(self.docs)
        root.addWidget(self.stack, 1)

        root.addWidget(self._progress_strip())

        self.status = self.statusBar()
        self._build_status_bar()
        self.menu.set_active("clients")
        self.menu.set_enabled_action("documents", False)

    def _build_status_bar(self) -> None:
        """Ο επιλεγμένος πελάτης μένει μόνιμα ορατός.

        Το showMessage γράφει στην αριστερή, προσωρινή περιοχή — ένα μήνυμα
        προόδου θα έσβηνε τον πελάτη. Γι' αυτό μπαίνει ως permanent widget.
        """
        self.status_client = QLabel("Κανένας πελάτης επιλεγμένος")
        self.status_client.setToolTip("Ο πελάτης στον οποίο δουλεύετε τώρα")
        self.status_client.setStyleSheet(f"color:{CURRENT.muted}; padding-right:6px;")
        self.status.addPermanentWidget(self.status_client)
        self._set_status_client([])

    def _progress_strip(self) -> QWidget:
        """Ζει έξω από το stack, ώστε η πρόοδος να φαίνεται σε όποια σελίδα κι
        αν βρίσκεται ο χρήστης."""
        strip = QWidget()
        box = QVBoxLayout(strip)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(3)

        line = QHBoxLayout()
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("muted")
        line.addWidget(self.progress_label, 1)
        self.progress_stats = QLabel("")
        self.progress_stats.setStyleSheet("font-weight:600;")
        line.addWidget(self.progress_stats)
        box.addLayout(line)

        self.progress = QProgressBar()
        self.progress.setFormat("%v / %m πελάτες")
        box.addWidget(self.progress)

        # Η τελευταία γραμμή του ιστορικού. Το πλήρες ιστορικό έφυγε από την
        # οθόνη· εδώ μένει μόνο το «τι κάνει τώρα», που είναι και το μόνο που
        # κοιτάει κανείς όσο τρέχει η λήψη.
        self.progress_detail = QLabel("")
        self.progress_detail.setObjectName("muted")
        self.progress_detail.setToolTip(
            "Η τελευταία ενέργεια. Το πλήρες ιστορικό γράφεται στο αρχείο "
            "καταγραφής (μενού: Βοήθεια → Αρχείο καταγραφής)."
        )
        box.addWidget(self.progress_detail)

        strip.setVisible(False)
        self._strip = strip
        return strip

    def _clients_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        filters = QHBoxLayout()
        filters.setSpacing(7)
        self.combo_filter = QComboBox()
        self.combo_filter.addItems(_FILTERS)
        self.combo_filter.setFixedWidth(160)
        self.combo_filter.setToolTip("Ποιους πελάτες να δείχνει ο πίνακας")
        self.combo_filter.currentIndexChanged.connect(self.reload_clients)
        filters.addWidget(self.combo_filter)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Αναζήτηση ΑΦΜ ή επωνυμίας…")
        self.search.setToolTip("Φιλτράρει τη λίστα καθώς πληκτρολογείτε")
        self.search.textChanged.connect(self.reload_clients)
        filters.addWidget(self.search)

        self.btn_check_all = QPushButton("Επιλογή όλων")
        self.btn_check_all.setToolTip("Επιλέγει όσους πελάτες δείχνει ο πίνακας")
        self.btn_check_all.clicked.connect(lambda: self._check_shown(True))
        filters.addWidget(self.btn_check_all)

        self.btn_check_none = QPushButton("Αποεπιλογή όλων")
        self.btn_check_none.setToolTip("Καθαρίζει όλες τις επιλογές")
        self.btn_check_none.clicked.connect(lambda: self._check_shown(False))
        filters.addWidget(self.btn_check_none)
        layout.addLayout(filters)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(True)
        setup_columns(self.table, _COLUMN_SPEC, self._prefs, "clients")
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        # Πλήκτρο Delete: σβήνει όσους πελάτες είναι φωτισμένοι (έναν ή πολλούς),
        # χωρίς να χρειάζεται δεξί κλικ. Περιορίζεται στον πίνακα ώστε να μη
        # «σβήνει» τυχαία όταν ο χρήστης δουλεύει αλλού.
        delete_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Delete), self.table)
        delete_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        delete_shortcut.activated.connect(self._delete_selected)
        splitter.addWidget(self.table)

        self.analysis = AnalysisPanel()
        self.analysis.filter_requested.connect(self._open_documents_filtered)
        self.analysis.supplier_requested.connect(self._open_documents_supplier)
        self.analysis.type_requested.connect(self._open_documents_type)
        self.analysis.fill_gaps_requested.connect(self._fill_gap)
        splitter.addWidget(self.analysis)
        # Ο πίνακας παίρνει τη μερίδα του λέοντος: με 9 στήλες, ό,τι δώσουμε στην
        # ανάλυση το πληρώνει η στήλη της επωνυμίας.
        splitter.setSizes([840, _PANEL_W])
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

        # Κλειστό μέχρι να επιλεγεί πελάτης: χωρίς επιλογή δεν έχει τι να δείξει,
        # και ένα άδειο panel απλώς τρώει 440 pixel από τον πίνακα.
        self.analysis.setVisible(False)
        self._panel_open = False
        self._panel_anim: QPropertyAnimation | None = None
        return page

    # ------------------------------------------------------------- tooltips
    def _apply_tooltips(self, enabled: bool) -> None:
        """Ανάβει/σβήνει όλα τα βοηθητικά μηνύματα.

        Το αρχικό κείμενο αποθηκεύεται τη στιγμή που το συναντάμε, όχι μία φορά
        στην εκκίνηση: τα πλακίδια και οι γραμμές των πινάκων φτιάχνονται ξανά
        συνέχεια, οπότε μια εφάπαξ συλλογή θα τα έχανε.
        """
        self._tooltips_on = enabled
        for w in self.findChildren(QWidget):
            stored = w.property("help_text")
            if not stored and w.toolTip():
                stored = w.toolTip()
                w.setProperty("help_text", stored)
            if stored:
                w.setToolTip(stored if enabled else "")

    def _refresh_tooltips(self) -> None:
        if not self._tooltips_on:
            self._apply_tooltips(False)

    # ------------------------------------------------------------- δεδομένα
    def reload_clients(self) -> None:
        rows = repo.list_clients(self.conn)
        stats = {
            r["client_id"]: r
            for r in self.conn.execute(
                """SELECT d.client_id, COUNT(*) c,
                          SUM(d.status='downloaded') dn,
                          SUM(d.classification='unclassified') u,
                          COALESCE(SUM(CASE WHEN d.issuer_vat = c.vat
                                            THEN d.total_value ELSE 0 END),0) income,
                          COALESCE(SUM(CASE WHEN d.issuer_vat <> c.vat
                                            THEN d.total_value ELSE 0 END),0) expense
                   FROM documents d JOIN clients c ON c.id = d.client_id
                   GROUP BY d.client_id"""
            )
        }
        needle = self.search.text().strip().lower()
        mode = self.combo_filter.currentText()

        if mode == "Διαθέσιμοι":
            rows = [r for r in rows if r["status"] == "ready"]
        elif mode == "Χωρίς κλειδί API":
            rows = [r for r in rows if r["status"] != "ready"]
        elif mode == "Με αχαρακτήριστα":
            rows = [r for r in rows
                    if stats.get(r["id"]) and (stats[r["id"]]["u"] or 0) > 0]
        if needle:
            rows = [r for r in rows
                    if needle in r["vat"].lower() or needle in (r["label"] or "").lower()]

        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            s = stats.get(row["id"])
            total = (s["c"] if s else 0) or 0
            done = (s["dn"] if s else 0) or 0
            uncls = (s["u"] if s else 0) or 0
            income = (s["income"] if s else 0.0) or 0.0
            expense = (s["expense"] if s else 0.0) or 0.0
            is_ready = row["status"] == "ready"

            check = QTableWidgetItem()
            check.setFlags(
                (Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                 | Qt.ItemFlag.ItemIsSelectable)
                if is_ready else Qt.ItemFlag.ItemIsSelectable
            )
            check.setCheckState(
                Qt.CheckState.Checked if row["vat"] in self._checked
                else Qt.CheckState.Unchecked
            )
            check.setData(Qt.ItemDataRole.UserRole, row["vat"])
            if not is_ready:
                check.setToolTip("Χωρίς κλειδί API — δεν μπορεί να κατεβάσει")
            self.table.setItem(i, _COL_CHECK, check)

            cells = {
                _COL_VAT: row["vat"],
                _COL_LABEL: row["label"] or "",
                _COL_STATUS: _STATUS_READY if is_ready else _STATUS_NO_KEY,
                4: str(total), 5: str(done), 6: str(uncls),
                7: money(income) if income else "—",
                8: money(expense) if expense else "—",
            }
            sort_keys: dict[int, float] = {4: total, 5: done, 6: uncls,
                                           7: income, 8: expense}
            for col, text in cells.items():
                if col in sort_keys:
                    item = SortableItem(text, sort_keys[col])
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                          | Qt.AlignmentFlag.AlignVCenter)
                else:
                    item = QTableWidgetItem(text)
                if col == _COL_STATUS:
                    item.setForeground(QColor(CURRENT.ok if is_ready else CURRENT.bad))
                if col == 5 and done:
                    item.setForeground(QColor(CURRENT.ok))
                if col == 6 and uncls:
                    item.setForeground(QColor(CURRENT.warn))
                if col == 7 and income:
                    item.setForeground(QColor(CURRENT.ok))
                if col == 8 and expense:
                    item.setForeground(QColor(CURRENT.warn))
                self.table.setItem(i, col, item)

        self.table.setSortingEnabled(True)
        resort(self.table)
        self.table.blockSignals(False)

        all_rows = repo.list_clients(self.conn)
        ready = sum(1 for r in all_rows if r["status"] == "ready")
        self.status.showMessage(
            f"{len(all_rows)} πελάτες · {ready} διαθέσιμοι · "
            f"{len(all_rows) - ready} χωρίς κλειδί API · "
            f"{len(self._checked)} επιλεγμένοι για λήψη"
        )
        self.sync_page.checked = set(self._checked)
        self.sync_page.load_clients(self.conn)
        self._refresh_tooltips()

    def _on_double_click(self) -> None:
        """Διπλό κλικ σε γραμμή πελάτη.

        Χωρίς κλειδί, το μόνο χρήσιμο είναι να το συμπληρώσει· με κλειδί, το
        πιο συχνό είναι να τον (απο)επιλέξει για λήψη.
        """
        rows = {i.row() for i in self.table.selectedIndexes()}
        if len(rows) == 1:
            row = next(iter(rows))
            status = self.table.item(row, _COL_STATUS)
            vat_item = self.table.item(row, _COL_VAT)
            if status is not None and vat_item is not None:
                if status.text() != _STATUS_READY:
                    self.on_edit_client(vat_item.text())
                    return
        self._toggle_checked(rows)

    def _toggle_checked(self, rows: set[int]) -> None:
        self.table.blockSignals(True)
        for row in rows:
            item = self.table.item(row, _COL_CHECK)
            if item is None or not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                continue
            checked = item.checkState() is Qt.CheckState.Checked
            item.setCheckState(
                Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked
            )
            vat = item.data(Qt.ItemDataRole.UserRole)
            if checked:
                self._checked.discard(vat)
            else:
                self._checked.add(vat)
        self.table.blockSignals(False)
        self._sync_checked()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != _COL_CHECK:
            return
        vat = item.data(Qt.ItemDataRole.UserRole)
        if not vat:
            return
        if item.checkState() is Qt.CheckState.Checked:
            self._checked.add(vat)
        else:
            self._checked.discard(vat)
        self._sync_checked()

    def _sync_checked(self) -> None:
        """Οι δύο λίστες (Πελάτες / Λήψη) δείχνουν την ίδια επιλογή."""
        self.sync_page.set_checked(self._checked)
        self.status.showMessage(
            f"{len(self._checked)} πελάτες επιλεγμένοι για λήψη"
            if self._checked else "Κανένας επιλεγμένος — η λήψη θα γίνει για όλους"
        )

    def _on_sync_selection(self, _: int) -> None:
        """Η επιλογή άλλαξε από τη σελίδα Λήψης."""
        if self._checked != self.sync_page.checked:
            self._checked = set(self.sync_page.checked)
            self.reload_clients()

    def _check_shown(self, checked: bool) -> None:
        self.table.blockSignals(True)
        for i in range(self.table.rowCount()):
            item = self.table.item(i, _COL_CHECK)
            if item is None or not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                continue
            item.setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )
            vat = item.data(Qt.ItemDataRole.UserRole)
            if checked:
                self._checked.add(vat)
            else:
                self._checked.discard(vat)
        self.table.blockSignals(False)
        ready = sum(1 for r in repo.list_clients(self.conn) if r["status"] == "ready")
        self.sync_page.set_target(len(self._checked), ready)
        self.reload_clients()

    def _selected_vats(self, only_ready: bool = True) -> list[str]:
        """Οι *φωτισμένες* γραμμές — για ανάλυση και εξαγωγές.

        Διαφορετικό από το _checked, που ορίζει ποιοι θα κατέβουν.
        """
        rows = {i.row() for i in self.table.selectedIndexes()}
        out: list[str] = []
        for r in sorted(rows):
            vat_item = self.table.item(r, _COL_VAT)
            status_item = self.table.item(r, _COL_STATUS)
            if not vat_item or not status_item:
                continue
            if only_ready and status_item.text() != _STATUS_READY:
                continue
            out.append(vat_item.text())
        return out

    def _label_for(self, vat: str) -> str:
        row = self.conn.execute("SELECT label FROM clients WHERE vat=?", (vat,)).fetchone()
        return (row["label"] if row else "") or vat

    def _on_selection(self, animate: bool = True) -> None:
        vats = self._selected_vats(only_ready=False)
        self.menu.set_enabled_action("documents", len(vats) == 1)
        if vats:
            if len(vats) == 1:
                self.analysis.show_client(self.conn, vats[0])
            else:
                self.analysis.show_placeholder(f"{len(vats)} πελάτες επιλεγμένοι.")
            already = self._panel_open
            self._set_panel_open(True, animate=animate)
            if already and animate:
                self._nudge_panel()
        else:
            # Καμία επιλογή: το panel κλείνει αντί να δείχνει άδειο κουτί.
            self._set_panel_open(False, animate=animate)
        self._set_status_client(vats)
        self._refresh_tooltips()

    def _set_status_client(self, vats: list[str]) -> None:
        if len(vats) == 1:
            self.status_client.setText(f"Πελάτης: {self._label_for(vats[0])} · {vats[0]}")
            self.status_client.setStyleSheet(
                f"color:{CURRENT.accent}; font-weight:600; padding-right:6px;"
            )
        else:
            self.status_client.setText(
                f"{len(vats)} πελάτες επιλεγμένοι" if vats
                else "Κανένας πελάτης επιλεγμένος"
            )
            self.status_client.setStyleSheet(
                f"color:{CURRENT.muted}; padding-right:6px;"
            )

    def _set_panel_open(self, open_: bool, *, animate: bool = True) -> None:
        """Ανοίγει/κλείνει το δεξί panel με συρόμενο εφέ.

        Το εφέ είναι πλάτος και όχι διαφάνεια: το fade έκανε το panel να
        τρεμοπαίζει στη θέση του χωρίς να λέει ότι άνοιξε κάτι, ενώ το σύρσιμο
        δείχνει από πού ήρθε.

        Το minimumWidth μηδενίζεται όσο τρέχει η κίνηση — αλλιώς το layout θα
        κρατούσε το panel στα 440 pixel και η «κίνηση» θα ήταν ένα αναπήδημα.
        """
        if self._panel_anim is not None:
            self._panel_anim.stop()
            self._panel_anim = None
        if open_ == self._panel_open and self.analysis.isVisible() == open_:
            return
        self._panel_open = open_

        if not animate:
            self.analysis.setVisible(open_)
            self.analysis.setMinimumWidth(_PANEL_W if open_ else 0)
            self.analysis.setMaximumWidth(16777215 if open_ else 0)
            return

        self.analysis.setMinimumWidth(0)
        start = self.analysis.width() if self.analysis.isVisible() else 0
        if open_:
            self.analysis.setMaximumWidth(0)
            self.analysis.setVisible(True)
            start = 0

        animation = QPropertyAnimation(self.analysis, b"maximumWidth", self)
        animation.setDuration(200)
        animation.setStartValue(start)
        animation.setEndValue(_PANEL_W if open_ else 0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda: self._panel_settled(open_))
        self._panel_anim = animation
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _panel_settled(self, open_: bool) -> None:
        self._panel_anim = None
        if open_:
            # Ξεκλειδώνουμε το πλάτος ώστε ο χρήστης να σύρει το χώρισμα όπως
            # θέλει, και ξαναβάζουμε το κατώφλι αναγνωσιμότητας.
            self.analysis.setMaximumWidth(16777215)
            self.analysis.setMinimumWidth(_PANEL_W)
        else:
            self.analysis.setVisible(False)

    def _nudge_panel(self) -> None:
        """Σύντομο «σπρώξιμο» όταν αλλάζει πελάτης με το panel ήδη ανοιχτό.

        Το panel ξαναχτίζεται σε κάθε επιλογή· χωρίς ένδειξη η αλλαγή περνά
        απαρατήρητη και δεν φαίνεται ότι αφορά τη γραμμή που μόλις πατήθηκε.
        """
        if self._panel_anim is not None:
            return
        width = self.analysis.width()
        if width < 40:
            return
        self.analysis.setMinimumWidth(0)
        animation = QPropertyAnimation(self.analysis, b"maximumWidth", self)
        animation.setDuration(150)
        animation.setStartValue(int(width * 0.88))
        animation.setEndValue(width)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda: self._panel_settled(True))
        self._panel_anim = animation
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    # ---------------------------------------------------------- πλοήγηση
    def _show_page(self, name: str) -> None:
        self.stack.setCurrentIndex(_PAGES.index(name))
        self.menu.set_active(name)
        self._restyle_page(name)

    def _current_page(self) -> str:
        return _PAGES[self.stack.currentIndex()]

    def _open_documents(self) -> None:
        self._open_documents_filtered("all")

    def _current_doc_client(self) -> str | None:
        vats = self._selected_vats(only_ready=False)
        return vats[0] if len(vats) == 1 else None

    def _open_documents_filtered(self, filter_key: str) -> None:
        self._open_documents_with(filter_key=filter_key)

    def _open_documents_supplier(self, supplier_vat: str) -> None:
        self._open_documents_with(supplier_vat=supplier_vat)

    def _open_documents_type(self, invoice_type: str) -> None:
        self._open_documents_with(invoice_type=invoice_type)

    def _open_documents_with(
        self, *, filter_key: str = "all", supplier_vat: str = "", invoice_type: str = ""
    ) -> None:
        vat = self._current_doc_client()
        if vat is None:
            return
        # Ένας πελάτης με τρεις χιλιάδες παραστατικά χρειάζεται αισθητό χρόνο
        # για να στηθεί ο πίνακας — χωρίς πέπλο μοιάζει με κόλλημα.
        with self._busy("Φόρτωση παραστατικών…"):
            self.docs.show_client(
                self.conn, vat, self._label_for(vat), filter_key,
                supplier_vat=supplier_vat, invoice_type=invoice_type,
            )
            self._show_page("documents")
            self._refresh_tooltips()

    def _on_menu(self, action: str) -> None:
        handlers = {
            "clients": lambda: self._show_page("clients"),
            "sync": lambda: self._show_page("sync"),
            "documents": self._open_documents,
            "add_client": self.on_add_client,
            "import": self.on_import,
            "folder": self.on_open_folder,
            "csv": self.on_export,
            "backup": self.on_backup,
            "restore": self.on_restore,
            "wipe": lambda: self.on_wipe(),
            "tour": self.start_tour,
            "manual": self.on_manual,
            "logfile": self.on_open_log,
        }
        handler = handlers.get(action)
        if handler:
            handler()

    # ---------------------------------------------------------- θέμα
    def _on_theme(self, light: bool) -> None:
        """Αλλαγή θέματος — μόνο για ό,τι φαίνεται.

        Πριν, κάθε εναλλαγή ξανάχτιζε και τους τρεις πίνακες: τρία ερωτήματα στη
        βάση και εκατοντάδες κελιά, από τα οποία ο χρήστης έβλεπε το ένα τρίτο.
        Τώρα ξαναχτίζεται η τρέχουσα σελίδα και οι άλλες σημειώνονται ως
        ξεπερασμένες — πληρώνονται όταν και αν ανοίξουν.
        """
        name = "light" if light else "dark"
        apply_theme(QApplication.instance(), name)
        self._prefs.setValue("theme", name)
        paint_title_bar(self, not light)
        # Τα εικονίδια είναι bitmaps βαμμένα σε χρώμα και οι πίνακες βάφουν
        # κελιά προγραμματιστικά — τίποτα από τα δύο δεν αλλάζει μόνο του από
        # το νέο stylesheet.
        self.menu.restyle()
        self.sync_page.restyle()  # φθηνό: εικονίδια, χωρίς ξαναγέμισμα
        self._set_status_client(self._selected_vats(only_ready=False))
        self._stale = {"clients", "documents"}
        self._restyle_page(self._current_page())
        self._refresh_tooltips()
        self._repaint_everything()

    def _repaint_everything(self) -> None:
        """Αναγκάζει κάθε widget να ξαναζωγραφιστεί με το νέο θέμα.

        Το setStyleSheet ζητά από μόνο του update() σε όλο το δέντρο, αλλά όσα
        widgets δεν τα αγγίζει ο χρήστης κρατούσαν τα παλιά pixel: το πλαϊνό
        μενού έμενε σκούρο πάνω σε φωτεινή εφαρμογή μέχρι να περάσει από πάνω
        του το ποντίκι. Ο πίνακας «διορθωνόταν» μόνος του απλώς επειδή τον
        σκροllάρει κανείς.

        Είναι φθηνό: το update() σημειώνει, δεν ζωγραφίζει.
        """
        for widget in self.findChildren(QWidget):
            widget.update()
        self.update()

    @contextmanager
    def _busy(self, text: str):
        """Πέπλο αναμονής γύρω από δουλειά που κρατά αισθητά.

        Δεν κάνει τη δουλειά πιο γρήγορη — λέει όμως ότι γίνεται, και μπλοκάρει
        τα κλικ ώστε ένα ανυπόμονο διπλό κλικ να μην την ξεκινήσει δεύτερη φορά.
        """
        self.busy.start(text)
        try:
            yield
        finally:
            self.busy.stop()

    def _restyle_page(self, name: str) -> None:
        """Ξαναχτίζει μια σελίδα μόνο αν την έχει ακουμπήσει αλλαγή θέματος."""
        if name not in self._stale:
            return
        self._stale.discard(name)
        if name == "clients":
            self.reload_clients()
            self._on_selection(animate=False)
        elif name == "documents":
            self.docs.restyle()

    # -------------------------------------------------------------- actions
    def _context_menu(self, point) -> None:
        row = self.table.rowAt(point.y())
        if row < 0:
            return
        vat_item = self.table.item(row, _COL_VAT)
        if vat_item is None:
            return
        vat = vat_item.text()
        selected = self._selected_vats(only_ready=False)
        if vat not in selected:
            selected = [vat]

        menu = QMenu(self)
        edit = QAction(icon("edit", CURRENT.muted), "Επεξεργασία…", self)
        edit.triggered.connect(lambda: self.on_edit_client(vat))
        edit.setEnabled(len(selected) == 1)
        menu.addAction(edit)

        docs = QAction(icon("pdf", CURRENT.muted), "Παραστατικά", self)
        docs.triggered.connect(self._open_documents)
        docs.setEnabled(len(selected) == 1)
        menu.addAction(docs)
        menu.addSeparator()

        wipe = QAction(icon("wipe", CURRENT.warn), "Εκκαθάριση ληφθέντων", self)
        wipe.triggered.connect(lambda: self.on_wipe(selected))
        menu.addAction(wipe)

        label = ("Διαγραφή πελάτη" if len(selected) == 1
                 else f"Διαγραφή {len(selected)} πελατών")
        delete = QAction(icon("delete", CURRENT.bad), label, self)
        delete.triggered.connect(lambda: self.on_delete_clients(selected))
        menu.addAction(delete)
        menu.exec(self.table.viewport().mapToGlobal(point))

    def on_edit_client(self, vat: str) -> None:
        client = repo.get_client(self.conn, vat, self.crypto)
        if client is None:
            return
        dialog = ClientDialog(self.conn, existing=client, parent=self)
        if not dialog.exec() or dialog.client is None:
            return
        create_backup(self.settings.db_path, reason="edit-client")
        repo.upsert_client(self.conn, dialog.client, self.crypto)
        repo.seed_suppliers_from_clients(self.conn)
        self.conn.commit()
        self.reload_clients()
        self._log(f"Ενημερώθηκε ο πελάτης {vat}")

    def _delete_selected(self) -> None:
        """Το πλήκτρο Delete σβήνει όσους πελάτες είναι φωτισμένοι — έναν ή
        πολλούς. Χωρίς επιλογή δεν κάνει τίποτα (δεν σβήνει «όλους» κατά λάθος)."""
        self.on_delete_clients(self._selected_vats(only_ready=False))

    def on_delete_clients(self, vats: list[str]) -> None:
        if not vats:
            return
        docs = self.conn.execute(
            f"""SELECT COUNT(*) c FROM documents WHERE client_id IN
                (SELECT id FROM clients WHERE vat IN ({",".join("?" * len(vats))}))""",
            vats,
        ).fetchone()["c"]
        who = self._label_for(vats[0]) if len(vats) == 1 else f"{len(vats)} πελάτες"
        answer = QMessageBox.warning(
            self, "Διαγραφή πελατών",
            f"Διαγραφή: {who}\n\n"
            f"Θα σβηστούν και {docs} εγγραφές παραστατικών από τη βάση.\n"
            "Τα αρχεία PDF στον δίσκο ΔΕΝ διαγράφονται.\n\n"
            "Η ενέργεια δεν αναιρείται (υπάρχει όμως αντίγραφο ασφαλείας).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        with self._busy("Διαγραφή…"):
            create_backup(self.settings.db_path, reason="delete-clients")
            count = repo.delete_clients(self.conn, vats)
            self.conn.commit()
            self._checked -= set(vats)
            self.reload_clients()
            self._set_panel_open(False, animate=False)
        self._log(f"Διαγράφηκαν {count} πελάτες")

    def on_wipe(self, vats: list[str] | None = None) -> None:
        """Σβήνει τα ληφθέντα και, προαιρετικά, τους ίδιους τους πελάτες.

        Δύο επιλογές μέσα στο ίδιο παράθυρο: διαγραφή και των αρχείων από τον
        δίσκο, και **μαζική διαγραφή των πελατών** (όχι μόνο των παραστατικών
        τους). Χωρίς επιλογή πελατών αφορά όλους· με επιλεγμένους, μόνο αυτούς.
        """
        vats = vats or self._selected_vats(only_ready=False)
        # Οι πραγματικοί στόχοι για μαζική διαγραφή: οι επιλεγμένοι ή, χωρίς
        # επιλογή, όλοι οι πελάτες.
        targets = vats or [r["vat"] for r in repo.list_clients(self.conn)]
        if not targets:
            QMessageBox.information(self, "Εκκαθάριση", "Δεν υπάρχουν πελάτες.")
            return
        scope = (
            self._label_for(vats[0]) if len(vats) == 1
            else f"{len(vats)} πελάτες" if vats
            else "ΟΛΟΥΣ τους πελάτες"
        )
        docs = self.conn.execute(
            "SELECT COUNT(*) c FROM documents" if not vats else
            f"""SELECT COUNT(*) c FROM documents WHERE client_id IN
                (SELECT id FROM clients WHERE vat IN ({",".join("?" * len(vats))}))""",
            vats or [],
        ).fetchone()["c"]

        proceed, delete_files, delete_clients = self._ask_wipe(scope, docs, len(targets))
        if not proceed:
            return

        with self._busy("Εκκαθάριση…"):
            create_backup(self.settings.db_path, reason="wipe")
            removed_files = self._delete_files(vats) if delete_files else 0
            count = repo.wipe_documents(self.conn, vats or None)
            deleted_clients = 0
            if delete_clients:
                deleted_clients = repo.delete_clients(self.conn, targets)
                self._checked -= set(targets)
            self.conn.commit()
            self.reload_clients()
            # Το reload καθαρίζει την επιλογή με μπλοκαρισμένα signals, οπότε το
            # _on_selection δεν τρέχει· χωρίς αυτό το panel θα έμενε ανοιχτό
            # δείχνοντας αριθμούς που μόλις σβήστηκαν.
            self._set_panel_open(False, animate=False)

        parts = [f"{count} εγγραφές"]
        if removed_files:
            parts.append(f"{removed_files} αρχεία")
        if deleted_clients:
            parts.append(f"{deleted_clients} πελάτες")
        summary = ", ".join(parts)
        self._log(f"Εκκαθάριση: {summary}")
        QMessageBox.information(
            self, "Η εκκαθάριση ολοκληρώθηκε", f"Σβήστηκαν: {summary}."
        )

    def _ask_wipe(self, scope: str, docs: int, n_targets: int) -> tuple[bool, bool, bool]:
        """Παράθυρο επιβεβαίωσης εκκαθάρισης με δύο επιλογές.

        Το QMessageBox δέχεται ένα μόνο checkbox, οπότε φτιάχνουμε δικό μας
        παράθυρο για να χωρέσουν και οι δύο (αρχεία + μαζική διαγραφή πελατών).
        Επιστρέφει (προχώρα, διαγραφή αρχείων, διαγραφή πελατών).
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("Εκκαθάριση ληφθέντων")
        dialog.setMinimumWidth(440)
        root = QVBoxLayout(dialog)
        root.setSpacing(10)

        header = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(icon("wipe", CURRENT.warn, 26).pixmap(QSize(26, 26)))
        header.addWidget(mark)
        title = QLabel(f"Εκκαθάριση για: {scope}")
        title.setObjectName("h1")
        title.setWordWrap(True)
        header.addWidget(title, 1)
        root.addLayout(header)

        info = QLabel(
            f"Θα σβηστούν {docs} εγγραφές παραστατικών και θα μηδενιστεί το "
            "ιστορικό λήψης, ώστε η επόμενη λήψη να τα ξαναφέρει όλα.\n\n"
            "Από προεπιλογή οι πελάτες και τα κλειδιά τους παραμένουν."
        )
        info.setWordWrap(True)
        info.setObjectName("muted")
        root.addWidget(info)

        chk_files = QCheckBox("Διαγραφή και των αρχείων PDF/XML από τον δίσκο")
        chk_clients = QCheckBox(
            "Διαγραφή και των ίδιων των πελατών από τη βάση (μαζική διαγραφή)"
        )
        root.addWidget(chk_files)
        root.addWidget(chk_clients)

        warn = QLabel("")
        warn.setWordWrap(True)
        warn.setStyleSheet(f"color:{CURRENT.bad}; font-weight:600;")
        root.addWidget(warn)

        def _update_warn() -> None:
            if chk_clients.isChecked():
                warn.setText(
                    f"⚠ Θα διαγραφούν ΟΛΟΚΛΗΡΩΤΙΚΑ {n_targets} πελάτες μαζί με τα "
                    "κλειδιά τους. Η ενέργεια δεν αναιρείται (υπάρχει όμως "
                    "αντίγραφο ασφαλείας)."
                )
            else:
                warn.setText("")

        chk_clients.toggled.connect(_update_warn)

        buttons = QDialogButtonBox()
        buttons.addButton("Εκκαθάριση", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Άκυρο", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        root.addWidget(buttons)

        if not dialog.exec():
            return False, False, False
        return True, chk_files.isChecked(), chk_clients.isChecked()

    def _delete_files(self, vats: list[str]) -> int:
        """Διαγράφει τα αρχεία των πελατών από τον δίσκο.

        Μόνο μέσα στον φάκελο του κάθε πελάτη — ποτέ ολόκληρη τη ρίζα, ώστε ένα
        λάθος εδώ να μη σβήσει δεδομένα άλλων.
        """
        root = self.settings.storage_root
        targets = vats or [r["vat"] for r in repo.list_clients(self.conn)]
        removed = 0
        for vat in targets:
            folder = find_client_folder(root, vat, self._label_for(vat))
            if not folder.exists() or not folder.is_relative_to(root):
                continue
            for path in sorted(folder.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                try:
                    if path.is_file():
                        path.unlink()
                        removed += 1
                    else:
                        path.rmdir()
                except OSError:
                    pass
        return removed

    def on_add_client(self) -> None:
        dialog = ClientDialog(self.conn, parent=self)
        if not dialog.exec():
            return
        if dialog.excel_path:
            self._import_excel(Path(dialog.excel_path))
            return
        if dialog.client is None:
            return
        create_backup(self.settings.db_path, reason="manual-client")
        repo.upsert_client(self.conn, dialog.client, self.crypto)
        repo.seed_suppliers_from_clients(self.conn)
        self.conn.commit()
        self.reload_clients()
        self._log(f"Προστέθηκε ο πελάτης {dialog.client.vat} {dialog.client.label}")
        self._show_page("clients")
        self.search.setText(dialog.client.vat)

    def on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Επιλέξτε αρχείο Excel", "", "Excel (*.xlsx)"
        )
        if path:
            self._import_excel(Path(path))

    def _import_excel(self, path: Path) -> None:
        dialog = ImportDialog(Path(path), self.conn, self)
        if dialog.preview is None or not dialog.exec():
            return
        with self._busy(f"Εισαγωγή {len(dialog.preview.rows)} πελατών…"):
            create_backup(self.settings.db_path, reason="import")
            for row in dialog.preview.rows:
                repo.upsert_client(self.conn, row.client, self.crypto)
            repo.seed_suppliers_from_clients(self.conn)
            self.conn.commit()
            self.reload_clients()
        self._log(
            f"Εισήχθησαν {len(dialog.preview.rows)} πελάτες από {Path(path).name} "
            f"({dialog.preview.ready} έτοιμοι, {dialog.preview.missing_key} χωρίς κλειδί)."
        )

    def _fill_gap(self, spec: str) -> None:
        start, _, end = spec.partition("|")
        self.sync_page.date_from.set_gr(to_gr(start))
        self.sync_page.date_to.set_gr(to_gr(end))
        vat = self._current_doc_client()
        if vat:
            self._checked = {vat}
            self.reload_clients()
        self._show_page("sync")
        self._log(f"Συμπλήρωση κενού {to_gr(start)} – {to_gr(end)}")
        self.on_sync()

    def on_sync(self) -> None:
        if self._thread is not None:
            return
        vats = sorted(self._checked)
        if not vats:
            vats = [r["vat"] for r in repo.list_clients(self.conn, only_ready=True)]
        if not vats:
            QMessageBox.information(
                self, "Κανένας πελάτης",
                "Δεν υπάρχουν πελάτες με κλειδί API.\n\n"
                "Προσθέστε πελάτη ή κάντε εισαγωγή από Excel.",
            )
            return

        directions = self.sync_page.directions()
        if not directions:
            QMessageBox.information(
                self, "Τίποτα να κατέβει",
                "Επιλέξτε αν θα κατέβουν έσοδα, έξοδα ή και τα δύο.",
            )
            self._show_page("sync")
            return

        create_backup(self.settings.db_path, reason="sync")
        self._set_running(True, len(vats))
        self._show_page("sync")
        self._log(
            f"── Έναρξη λήψης για {len(vats)} πελάτες "
            f"({', '.join(d.value for d in directions)}) "
            f"{self.sync_page.date_from.gr()} – {self.sync_page.date_to.gr()}"
        )

        self._thread = QThread(self)
        self._worker = SyncWorker(
            vats,
            self.sync_page.date_from.gr(),
            self.sync_page.date_to.gr(),
            self.sync_page.chk_full.isChecked(),
            directions,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.message.connect(self._log)
        self._worker.client_started.connect(self._on_client_started)
        self._worker.client_finished.connect(self._on_client_finished)
        self._worker.totals.connect(self._on_totals)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.busy.connect(self._on_busy)
        self._thread.start()

    def on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
            self.sync_page.btn_cancel.setEnabled(False)

    def on_open_folder(self) -> None:
        root = self.settings.storage_root
        root.mkdir(parents=True, exist_ok=True)
        _reveal(root)

    def on_open_log(self) -> None:
        if not self.log_path.exists():
            QMessageBox.information(
                self, "Αρχείο καταγραφής", "Δεν έχει γραφτεί ακόμη τίποτα."
            )
            return
        _reveal(self.log_path)

    def on_manual(self) -> None:
        """Ανοίγει το εγχειρίδιο· αν λείπει από το bundle, το φτιάχνει τώρα."""
        try:
            path = ensure_manual(self.settings.data_dir)
        except Exception as exc:  # noqa: BLE001
            log.exception("Το εγχειρίδιο δεν δημιουργήθηκε")
            QMessageBox.warning(
                self, "Εγχειρίδιο",
                f"Το εγχειρίδιο δεν μπόρεσε να ανοίξει.\n\n{exc}",
            )
            return
        _reveal(path)

    # ------------------------------------------------------------- ξενάγηση
    def _tour_steps(self) -> list[Step]:
        return [
            Step(
                "Καλώς ήρθατε",
                "Η εφαρμογή κατεβάζει τα παραστατικά των πελατών σας από το "
                "myDATA και τα αποθηκεύει ως PDF στον υπολογιστή σας.\n\n"
                "Η ροή είναι τρία βήματα: Πελάτες → Λήψη → Παραστατικά.",
                lambda: self.menu,
            ),
            Step(
                "1. Νέος πελάτης",
                "Ξεκινήστε εδώ. Γράψτε το ΑΦΜ και η επωνυμία έρχεται μόνη της "
                "από το VIES· μετά συμπληρώστε το κλειδί myDATA.\n\n"
                "Στο ίδιο παράθυρο υπάρχει και η μαζική εισαγωγή από Excel.",
                lambda: self.menu.button("add_client"),
            ),
            Step(
                "2. Οι πελάτες σας",
                "Διπλό κλικ σε πελάτη τον (απο)επιλέγει για λήψη. Αν δεν έχει "
                "κλειδί, το διπλό κλικ ανοίγει το παράθυρο για να το βάλετε.\n\n"
                "Με δεξί κλικ: επεξεργασία, εκκαθάριση ή διαγραφή.\n"
                "Με Ctrl ή Shift + κλικ διαλέγετε πολλούς μαζί.",
                lambda: self.table,
                lambda: self._show_page("clients"),
            ),
            Step(
                "3. Φτιάξτε τους πίνακες όπως θέλετε",
                "Σε κάθε πίνακα της εφαρμογής:\n\n"
                "• Σύρετε το όριο μιας επικεφαλίδας για να αλλάξετε πλάτος.\n"
                "• Σύρετε την ίδια την επικεφαλίδα για να αλλάξετε σειρά.\n"
                "• Κλικ στην επικεφαλίδα ταξινομεί.\n\n"
                "Ό,τι ρυθμίσετε αποθηκεύεται και σας περιμένει την επόμενη φορά. "
                "Η στήλη της επωνυμίας γεμίζει μόνη της τον χώρο που περισσεύει, "
                "μέχρι να της δώσετε εσείς πλάτος.",
                lambda: self.table.horizontalHeader(),
                lambda: self._show_page("clients"),
            ),
            Step(
                "4. Η ανάλυση",
                "Για τον επιλεγμένο πελάτη βλέπετε έσοδα, έξοδα, τι κατέβηκε "
                "και τι έμεινε αχαρακτήριστο.\n\n"
                "Κάθε πλακίδιο είναι κουμπί: πατήστε το και ο πίνακας "
                "παραστατικών ανοίγει φιλτραρισμένος σε αυτό ακριβώς.",
                lambda: self.analysis,
                self._tour_show_analysis,
            ),
            Step(
                "5. Η λήψη",
                "Διαλέξτε περίοδο, αν θέλετε έσοδα, έξοδα ή και τα δύο, και "
                "ποιοι πελάτες θα κατέβουν.\n\n"
                "Η εφαρμογή ζητά μόνο ό,τι είναι νεότερο από την προηγούμενη "
                "φορά, οπότε η δεύτερη λήψη είναι σχεδόν ακαριαία.",
                lambda: self.sync_page,
                lambda: self._show_page("sync"),
            ),
            Step(
                "6. Τα παραστατικά",
                "Ο πίνακας ανοίγει στα αχαρακτήριστα — αυτά που θέλουν δουλειά "
                "από εσάς. Η μπλε ταινία σας το θυμίζει· «Καθαρισμός» για όλα.\n\n"
                "Τα φίλτρα συνδυάζονται: π.χ. έξοδα ΚΑΙ ελήφθησαν PDF.",
                lambda: self.menu.button("documents"),
            ),
            Step(
                "Ασφάλεια και βοήθεια",
                "Πριν από κάθε επικίνδυνη ενέργεια κρατιέται αντίγραφο της "
                "βάσης, οπότε η «Επαναφορά» σας γυρίζει πίσω.\n\n"
                "Το «Εγχειρίδιο PDF» τα εξηγεί όλα αναλυτικά. Καλή δουλειά!",
                lambda: self.menu,
            ),
        ]

    def _tour_show_analysis(self) -> None:
        """Ανοίγει το panel για να έχει τι να δείξει η ξενάγηση.

        Το panel είναι πλέον κλειστό όσο δεν υπάρχει επιλεγμένος πελάτης, οπότε
        το βήμα θα φώτιζε το τίποτα. Διαλέγουμε τον πρώτο πελάτη και ανοίγουμε
        ακαριαία: μια κίνηση 200ms θα τελείωνε αφού η ξενάγηση είχε ήδη μετρήσει
        πού να ζωγραφίσει το πλαίσιο.
        """
        self._show_page("clients")
        if not self._selected_vats(only_ready=False) and self.table.rowCount():
            self.table.selectRow(0)
        if self._panel_anim is not None:
            self._panel_anim.stop()
            self._panel_anim = None
        if self.table.rowCount():
            self._panel_open = True
            self.analysis.setVisible(True)
            self._panel_settled(True)

    def start_tour(self) -> None:
        if self._tour is not None:
            self._tour.deleteLater()
        self._tour = Tour(self, self._tour_steps())
        self._tour.finished.connect(
            lambda: self._prefs.setValue("tour_seen", True)
        )
        self._tour.start()
        self._tour.setFocus()

    def _maybe_first_run_tour(self) -> None:
        """Μία φορά, στην πρώτη εκκίνηση.

        Δεν ξαναρωτάει: όποιος τη θέλει ξανά την έχει στο μενού, και μια
        ξενάγηση που εμφανίζεται κάθε πρωί γίνεται εμπόδιο.
        """
        if self._prefs.value("tour_seen", False, type=bool):
            return
        self._prefs.setValue("tour_seen", True)
        self.start_tour()

    def on_backup(self) -> None:
        path = create_backup(self.settings.db_path, reason="manual")
        if path is None:
            QMessageBox.warning(self, "Αντίγραφο", "Δεν υπάρχει βάση για αντίγραφο.")
            return
        self._log(f"Αντίγραφο ασφαλείας: {path.name}")
        QMessageBox.information(
            self, "Αντίγραφο ασφαλείας",
            f"Δημιουργήθηκε:\n{path}\n\nΚρατούνται τα 10 πιο πρόσφατα ανά είδος.",
        )

    def on_restore(self) -> None:
        backups = list_backups(self.settings.data_dir)
        if not backups:
            QMessageBox.information(self, "Επαναφορά", "Δεν υπάρχουν αντίγραφα.")
            return
        newest, when, size = backups[0]
        answer = QMessageBox.question(
            self, "Επαναφορά βάσης",
            f"Επαναφορά από το πιο πρόσφατο αντίγραφο;\n\n"
            f"{newest.name}\n{when:%d/%m/%Y %H:%M} · {size/1024:.0f} KB\n\n"
            "Η τρέχουσα βάση θα κρατηθεί ως αντίγραφο «pre-restore», "
            "οπότε η ενέργεια είναι αναστρέψιμη.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        with self._busy("Επαναφορά βάσης…"):
            self.conn.close()
            restore(newest, self.settings.db_path)
            self.conn = init_db(self.settings.db_path)
            self.reload_clients()
        self._log(f"Έγινε επαναφορά από {newest.name}")

    def on_export(self) -> None:
        """Απαιτεί ρητά επιλεγμένο πελάτη: μια σιωπηλή εξαγωγή «όλων» δεν είναι
        ό,τι περιμένει κανείς όταν κοιτάει έναν συγκεκριμένο πελάτη."""
        vats = self._selected_vats(only_ready=False)
        if not vats:
            QMessageBox.information(
                self, "Εξαγωγή CSV",
                "Επιλέξτε πρώτα έναν ή περισσότερους πελάτες από τη λίστα.\n\n"
                "Κάντε κλικ σε γραμμή (ή Ctrl/Shift+κλικ για πολλούς) και "
                "ξαναπατήστε «Εξαγωγή CSV».",
            )
            self._show_page("clients")
            return

        who = self._label_for(vats[0]) if len(vats) == 1 else f"{len(vats)} πελάτες"
        default = self.settings.data_dir / (
            f"παραστατικά {vats[0]} {_safe_name(self._label_for(vats[0]))}.csv".strip()
            if len(vats) == 1 else "παραστατικά.csv"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, f"Εξαγωγή CSV — {who}", str(default), "CSV (*.csv)"
        )
        if not path:
            return
        total = 0
        with self._busy(f"Εξαγωγή CSV — {who}…"):
            for vat in vats:
                target = Path(path)
                if len(vats) > 1:
                    # Ένα αρχείο ανά πελάτη: το ΑΦΜ ξεχωρίζει, η επωνυμία εξηγεί.
                    target = target.with_name(
                        f"{target.stem} {vat} {_safe_name(self._label_for(vat))}"
                        f"{target.suffix}".replace("  ", " ")
                    )
                total += export_documents(self.conn, target, vat)
        self._log(f"Εξήχθησαν {total} παραστατικά για {who}")
        QMessageBox.information(
            self, "Η εξαγωγή ολοκληρώθηκε",
            f"{total} παραστατικά για {who}\n\n{Path(path).parent}",
        )

    # --------------------------------------------------------------- slots
    def _on_client_started(self, vat: str, label: str) -> None:
        self._log(f"── {vat} {label}")
        self.progress_label.setText(f"Λήψη: {label or vat}")

    def _on_client_finished(self, vat: str, found: int, pdfs: int, failed: int) -> None:
        self.progress.setValue(self.progress.value() + 1)
        note = f", {failed} σφάλματα" if failed else ""
        self._log(f"   {vat}: {found} παραστατικά, {pdfs} PDF{note}")
        self.reload_clients()

    def _on_totals(self, found: int, pdfs: int, no_url: int, failed: int) -> None:
        text = f"{found} παραστατικά · {pdfs} PDF · {no_url} χωρίς PDF"
        if failed:
            text += f" · {failed} σφάλματα"
        self.progress_stats.setText(text)
        self.status.showMessage(text)

    def _on_finished(self, completed: bool) -> None:
        self._log("Ολοκληρώθηκε." if completed else "Ακυρώθηκε από τον χρήστη.")
        self.progress_label.setText(
            "Η λήψη ολοκληρώθηκε." if completed else "Η λήψη ακυρώθηκε."
        )
        self._teardown()
        self.reload_clients()
        self._on_selection()

    def _on_busy(self, message: str) -> None:
        self._log("Η λήψη ακυρώθηκε: εκτελείται ήδη από άλλον υπολογιστή.")
        QMessageBox.information(self, "Εκτελείται ήδη λήψη", message)

    def _on_failed(self, detail: str) -> None:
        self._log(f"ΣΦΑΛΜΑ: {detail.splitlines()[0]}")
        QMessageBox.critical(self, "Σφάλμα", detail[:2000])
        self._teardown()

    def _teardown(self) -> None:
        if self._thread:
            self._thread.quit()
            self._thread.wait(5000)
        self._thread = None
        self._worker = None
        self._set_running(False, 0)

    def _set_running(self, running: bool, total: int) -> None:
        self.sync_page.set_running(running)
        self.menu.set_enabled_action("import", not running)
        self.menu.set_enabled_action("restore", not running)
        self.menu.set_enabled_action("add_client", not running)
        self._strip.setVisible(running)
        if running:
            self.progress.setRange(0, total)
            self.progress.setValue(0)
            self.progress_stats.setText("")
            self.progress_label.setText("Έναρξη…")

    def _log(self, text: str) -> None:
        """Το ιστορικό έφυγε από την οθόνη και ζει πλέον στο αρχείο καταγραφής.

        Στην οθόνη μένει μόνο η τελευταία γραμμή, πάνω από την μπάρα προόδου:
        αυτό που θέλει ο χρήστης εκείνη τη στιγμή είναι «πού είμαστε τώρα», όχι
        τετρακόσιες γραμμές ιστορικού.
        """
        log.info("%s", text)
        if self._strip.isVisible():
            self.progress_detail.setText(text.strip().lstrip("─ "))

    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        """Η γραμμή τίτλου βάφεται μόλις υπάρξει παράθυρο.

        Το DwmSetWindowAttribute θέλει έγκυρο HWND, που δεν υπάρχει πριν το
        show() — γι' αυτό δεν γίνεται στον constructor.
        """
        super().showEvent(event)
        if not self._title_bar_done:
            self._title_bar_done = paint_title_bar(
                self, not self.menu.chk_light.isChecked()
            )

    def closeEvent(self, event) -> None:
        if self._worker:
            self._worker.cancel()
            self._teardown()
        log.info("── Τερματισμός εφαρμογής")
        self.conn.close()
        super().closeEvent(event)


def _safe_name(label: str) -> str:
    """Επωνυμία που αντέχει ως όνομα αρχείου."""
    return "".join(c for c in label if c.isalnum() or c in " -_").strip()[:40]


def _reveal(path: Path) -> None:
    if os.name == "nt":
        os.startfile(path)  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", str(path)])

"""Καθοδηγούμενη λήψη «μόνο online» παραστατικών μέσω του browser του χρήστη.

Κάποιοι πάροχοι (Epsilon, Megasoft…) δείχνουν το παραστατικό μόνο σε δική τους
online προβολή, συχνά πίσω από έλεγχο «επιβεβαιώστε ότι είστε άνθρωπος»
(Cloudflare). Δεν υπάρχει PDF να κατεβεί αυτόματα — και δεν παρακάμπτουμε τον
έλεγχο. Αντ' αυτού βοηθάμε τον χρήστη να το κάνει ο ίδιος γρήγορα:

1. Ανοίγουμε το παραστατικό στον **δικό του** browser, όπου περνά τον έλεγχο ως
   άνθρωπος και το αποθηκεύει (Ctrl+P → «Αποθήκευση ως PDF», ή το κουμπί του
   παρόχου).
2. Παρακολουθούμε τον φάκελο «Λήψεις»· μόλις εμφανιστεί το νέο PDF, το
   **αρχειοθετούμε μόνοι μας** στο σωστό όνομα/φάκελο και το σημειώνουμε ως
   «Ελήφθη».

Ό,τι δεν πετυχαίνει (π.χ. δεν ανοίγει η σελίδα, ή ο σύνδεσμος έληξε και δεν
υπάρχει παραστατικό) ο χρήστης μπορεί είτε να το **παρακάμψει** (μένει «μόνο
online» για αργότερα) είτε να το **σημάνει ως σφάλμα** από το κουτάκι της
γραμμής του. Καμία αυτοματοποιημένη επικοινωνία με τον πάροχο.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
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

from ..config import Settings

log = logging.getLogger(__name__)

#: Πόσο συχνά κοιτάμε τον φάκελο λήψεων για νέο PDF.
_POLL_MS = 1500

_COL_STATUS, _COL_DATE, _COL_PARTY, _COL_HOST, _COL_ERR = range(5)
_MARK_ROLE = Qt.ItemDataRole.UserRole + 1
_SORT_ROLE = Qt.ItemDataRole.UserRole + 2


class _SortItem(QTableWidgetItem):
    """Κελί που ταξινομείται με βάση κρυφό κλειδί (π.χ. ISO ημερομηνία) αντί για
    το εμφανιζόμενο κείμενο (dd/mm/yyyy), ώστε η ταξινόμηση να είναι σωστή."""

    def __lt__(self, other: QTableWidgetItem) -> bool:  # noqa: D401 - Qt override
        a = self.data(_SORT_ROLE)
        b = other.data(_SORT_ROLE)
        if a is not None and b is not None:
            return a < b
        return super().__lt__(other)


def _downloads_dir() -> Path:
    from PySide6.QtCore import QStandardPaths

    loc = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DownloadLocation
    )
    return Path(loc) if loc else Path.home() / "Downloads"


def _gr_date(iso: str) -> str:
    if not iso or len(iso) < 10:
        return iso or "—"
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"


class OnlineOnlyDialog(QDialog):
    """Καθοδηγεί: άνοιγμα στον browser → αυτόματη αρχειοθέτηση, με παράκαμψη
    και σήμανση σφάλματος για όσα δεν πετυχαίνουν."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        rows: list[sqlite3.Row],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._settings = settings
        self._rows = list(rows)
        self._downloads = _downloads_dir()

        self._done: set[str] = set()      # αρχειοθετήθηκαν (Ελήφθη)
        self._errors: set[str] = set()    # σημάνθηκαν ως σφάλμα
        self._skipped: set[str] = set()   # παρακάμφθηκαν για αυτή τη συνεδρία

        # Παρακολούθηση του φακέλου λήψεων για το τρέχον ανοιγμένο παραστατικό.
        self._watch_mark: str | None = None
        self._snapshot: dict[str, float] = {}
        self._open_ts: float = 0.0
        self._candidate: tuple[str, int] | None = None
        self._loading = False

        self.setWindowTitle("Λήψη μόνο-online μέσω του browser σας")
        self.setMinimumSize(720, 480)
        self._build()
        self._populate()

        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._scan_downloads)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        intro = QLabel(
            "Αυτά τα παραστατικά ο πάροχος τα δείχνει <b>μόνο online</b>, συχνά "
            "πίσω από έλεγχο «είστε άνθρωπος». Διαλέξτε μια γραμμή και πατήστε "
            "<b>«Άνοιγμα»</b> (αλλιώς ανοίγει το επόμενο σε σειρά): ανοίγει στον "
            "browser σας, όπου το αποθηκεύετε ως PDF "
            "(Ctrl+P → «Αποθήκευση ως PDF», ή το κουμπί του παρόχου) και η "
            "εφαρμογή το αρχειοθετεί <b>μόνη της</b>.<br>"
            "Κάντε κλικ σε μια επικεφαλίδα στήλης για <b>ταξινόμηση</b>· η σειρά "
            "επεξεργασίας ακολουθεί την ταξινόμηση. Αν κάτι δεν ανοίγει ή δεν "
            "υπάρχει PDF: <b>«Παράκαμψη»</b>, ή τσεκάρετε <b>«Σφάλμα»</b> στη γραμμή."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Κατάσταση", "Ημ/νία", "Αντισυμβαλλόμενος", "Πάροχος", "Σφάλμα"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(_COL_PARTY, QHeaderView.ResizeMode.Stretch)
        for col in (_COL_STATUS, _COL_DATE, _COL_HOST, _COL_ERR):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        # Ταξινόμηση με κλικ στην επικεφαλίδα· η σειρά επεξεργασίας ακολουθεί την
        # οπτική σειρά του πίνακα (βλ. _open_next / _current).
        self.table.setSortingEnabled(True)
        hh.setSortIndicatorShown(True)
        self.table.itemChanged.connect(self._on_item_changed)
        root.addWidget(self.table, 1)

        folder = QHBoxLayout()
        self.lbl_folder = QLabel()
        self.lbl_folder.setStyleSheet("color:gray;")
        folder.addWidget(self.lbl_folder, 1)
        btn_folder = QPushButton("Αλλαγή φακέλου λήψεων…")
        btn_folder.clicked.connect(self._choose_folder)
        folder.addWidget(btn_folder)
        root.addLayout(folder)
        self._update_folder_label()

        self.lbl_status = QLabel()
        self.lbl_status.setStyleSheet("font-weight:600;")
        root.addWidget(self.lbl_status)

        buttons = QHBoxLayout()
        self.btn_open = QPushButton("Άνοιγμα στον browser")
        self.btn_open.setToolTip(
            "Ανοίγει την επιλεγμένη γραμμή· αν δεν έχετε επιλέξει, το επόμενο σε "
            "σειρά (με βάση την ταξινόμηση)."
        )
        self.btn_open.clicked.connect(self._open_next)
        buttons.addWidget(self.btn_open)

        self.btn_save = QPushButton("Αποθήκευση")
        self.btn_save.setToolTip(
            "Ψάχνει τώρα τον φάκελο λήψεων για το PDF που αποθηκεύσατε και το "
            "αρχειοθετεί."
        )
        self.btn_save.clicked.connect(self._scan_downloads)
        buttons.addWidget(self.btn_save)

        self.btn_skip = QPushButton("Παράκαμψη →")
        self.btn_skip.setToolTip(
            "Παραλείπει το τρέχον (μένει «μόνο online») και προχωρά στο επόμενο."
        )
        self.btn_skip.clicked.connect(self._skip_current)
        buttons.addWidget(self.btn_skip)

        buttons.addStretch()
        btn_close = QPushButton("Κλείσιμο")
        btn_close.clicked.connect(self.accept)
        buttons.addWidget(btn_close)
        root.addLayout(buttons)

    # ------------------------------------------------------------- helpers
    def _party(self, row: sqlite3.Row) -> str:
        return row["issuer_name"] or row["counter_name"] or row["issuer_vat"] or "—"

    def _state(self, mark: str) -> tuple[str, QColor | None]:
        if mark in self._done:
            return "✓ Αποθηκεύτηκε", QColor("#2e7d32")
        if mark in self._errors:
            return "✗ Σφάλμα", QColor("#c62828")
        if mark in self._skipped:
            return "⤳ Παράκαμψη", QColor("#9e9e9e")
        if mark == self._watch_mark:
            return "▶ Ανοιχτό — αποθηκεύστε", QColor("#1565c0")
        return "⧗ Αναμονή", None

    def _visual_marks(self) -> list[str]:
        """Τα marks με τη σειρά που φαίνονται τώρα στον πίνακα (μετά ταξινόμηση)."""
        out: list[str] = []
        for i in range(self.table.rowCount()):
            item = self.table.item(i, _COL_STATUS)
            if item is not None:
                out.append(item.data(_MARK_ROLE))
        return out

    def _is_pending(self, mark: str) -> bool:
        return (
            mark not in self._done and mark not in self._errors
            and mark not in self._skipped
        )

    def _current(self) -> sqlite3.Row | None:
        """Το επόμενο που περιμένει δουλειά, με τη σειρά που ταξινόμησε ο χρήστης.

        Ακολουθεί την οπτική σειρά του πίνακα ώστε η ταξινόμηση/επιλογή του χρήστη
        να καθορίζει τη σειρά επεξεργασίας.
        """
        for mark in self._visual_marks():
            if self._is_pending(mark):
                return self._row_by_mark(mark)
        return None

    def _selected_pending_row(self) -> sqlite3.Row | None:
        """Η επιλεγμένη γραμμή, αν ο χρήστης έχει επιλέξει μία που εκκρεμεί."""
        items = self.table.selectedItems()
        if not items:
            return None
        mark = items[0].data(_MARK_ROLE)
        if mark and self._is_pending(mark):
            return self._row_by_mark(mark)
        return None

    def _row_by_mark(self, mark: str) -> sqlite3.Row | None:
        for row in self._rows:
            if row["mark"] == mark:
                return row
        return None

    def _populate(self) -> None:
        """Αρχικό γέμισμα του πίνακα (μία φορά), με ταξινόμηση απενεργοποιημένη
        ώστε να κρατηθεί η αρχική σειρά (κατά ημερομηνία)."""
        self._loading = True
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._rows))
        for i, row in enumerate(self._rows):
            mark = row["mark"]
            text, color = self._state(mark)

            status = _SortItem(text)
            status.setData(_MARK_ROLE, mark)
            status.setData(_SORT_ROLE, text)
            if color:
                status.setForeground(color)
            self.table.setItem(i, _COL_STATUS, status)

            date = _SortItem(_gr_date(row["issue_date"]))
            date.setData(_SORT_ROLE, row["issue_date"] or "")
            self.table.setItem(i, _COL_DATE, date)
            self.table.setItem(i, _COL_PARTY, QTableWidgetItem(self._party(row)))
            self.table.setItem(i, _COL_HOST, QTableWidgetItem(row["provider_host"] or "—"))

            err = QTableWidgetItem()
            err.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            err.setCheckState(
                Qt.CheckState.Checked if mark in self._errors else Qt.CheckState.Unchecked
            )
            err.setData(_MARK_ROLE, mark)
            err.setToolTip("Σήμανση ως σφάλμα (π.χ. δεν ανοίγει ή δεν υπάρχει PDF)")
            self.table.setItem(i, _COL_ERR, err)
        self.table.setSortingEnabled(True)
        self._loading = False
        self._update_status()
        self._highlight_current()

    def _refresh(self) -> None:
        """Ενημερώνει κατάσταση/σήμανση **επί τόπου**, χωρίς να ξαναχτίζει τον
        πίνακα — έτσι διατηρείται η ταξινόμηση/σειρά που επέλεξε ο χρήστης."""
        if self.table.rowCount() != len(self._rows):
            self._populate()
            return
        self._loading = True
        for i in range(self.table.rowCount()):
            status = self.table.item(i, _COL_STATUS)
            if status is None:
                continue
            mark = status.data(_MARK_ROLE)
            text, color = self._state(mark)
            status.setText(text)
            status.setData(_SORT_ROLE, text)
            status.setForeground(color if color else QColor())
            err = self.table.item(i, _COL_ERR)
            if err is not None:
                want = (
                    Qt.CheckState.Checked if mark in self._errors
                    else Qt.CheckState.Unchecked
                )
                if err.checkState() != want:
                    err.setCheckState(want)
        self._loading = False
        self._update_status()
        self._highlight_current()

    def _highlight_current(self) -> None:
        # Μη «κλέβεις» την επιλογή του χρήστη: αν έχει επιλέξει μια γραμμή που
        # εκκρεμεί, σεβόμαστε την επιλογή του (θα ανοίξει αυτή).
        if self._selected_pending_row() is not None and self._watch_mark is None:
            return
        target = self._watch_mark or (self._current()["mark"] if self._current() else None)
        if not target:
            return
        for i in range(self.table.rowCount()):
            item = self.table.item(i, _COL_STATUS)
            if item is not None and item.data(_MARK_ROLE) == target:
                self.table.selectRow(i)
                self.table.scrollToItem(item)
                break

    def _update_folder_label(self) -> None:
        self.lbl_folder.setText(f"Φάκελος λήψεων: {self._downloads}")

    def _update_status(self) -> None:
        total = len(self._rows)
        done = len(self._done)
        err = len(self._errors)
        parts = [f"Αρχειοθετήθηκαν {done} από {total}"]
        if err:
            parts.append(f"{err} σφάλματα")
        if self._watch_mark is not None:
            row = self._row_by_mark(self._watch_mark)
            if row is not None:
                parts.append(f"Αναμονή αποθήκευσης: {self._party(row)} — αποθηκεύστε το PDF")
        self.lbl_status.setText("   ·   ".join(parts))

    # --------------------------------------------------------------- ροή
    def _choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Φάκελος λήψεων του browser", str(self._downloads)
        )
        if path:
            self._downloads = Path(path)
            self._update_folder_label()

    def _open_next(self) -> None:
        # Αν ο χρήστης έχει επιλέξει μια γραμμή που εκκρεμεί, ανοίγουμε αυτή·
        # αλλιώς το επόμενο σε σειρά (με βάση την ταξινόμηση του πίνακα).
        row = self._selected_pending_row() or self._current()
        if row is None:
            self._timer.stop()
            self._watch_mark = None
            QMessageBox.information(
                self, "Τέλος",
                "Δεν έμειναν άλλα παραστατικά μόνο-online προς επεξεργασία.",
            )
            self._refresh()
            return
        url = row["downloading_invoice_url"]
        if not url:
            self._skipped.add(row["mark"])
            self._refresh()
            return
        self._snapshot = self._pdf_snapshot()
        self._open_ts = self._now()
        self._candidate = None
        self._watch_mark = row["mark"]
        QDesktopServices.openUrl(QUrl(url))
        self._timer.start()
        self._refresh()

    def _skip_current(self) -> None:
        if self._watch_mark:
            row = self._row_by_mark(self._watch_mark)
        else:
            row = self._selected_pending_row() or self._current()
        if row is None:
            return
        self._timer.stop()
        self._skipped.add(row["mark"])
        self._watch_mark = None
        self._candidate = None
        self._refresh()
        # Προχωράμε αμέσως στο επόμενο, ανοίγοντάς το στον browser.
        if self._current() is not None:
            self._open_next()

    def _pdf_snapshot(self) -> dict[str, float]:
        snap: dict[str, float] = {}
        try:
            for p in self._downloads.glob("*.pdf"):
                try:
                    snap[str(p)] = p.stat().st_mtime
                except OSError:
                    continue
        except OSError:
            pass
        return snap

    @staticmethod
    def _now() -> float:
        import time

        return time.time()

    def _scan_downloads(self) -> None:
        if self._watch_mark is None:
            return
        from ..download import is_complete_pdf

        candidates: list[tuple[float, Path]] = []
        for p in self._downloads.glob("*.pdf"):
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            prev = self._snapshot.get(str(p))
            is_new = prev is None or mtime > prev
            if is_new and mtime >= self._open_ts - 1 and is_complete_pdf(p):
                candidates.append((mtime, p))
        if not candidates:
            return
        candidates.sort()
        newest = candidates[-1][1]
        try:
            size = newest.stat().st_size
        except OSError:
            return
        # Σταθερότητα: ίδιο αρχείο, ίδιο μέγεθος σε δύο ελέγχους — αλλιώς μπορεί
        # να το πιάσουμε μισογραμμένο.
        if self._candidate != (str(newest), size):
            self._candidate = (str(newest), size)
            return
        self._file_pdf(newest)

    def _file_pdf(self, source: Path) -> None:
        from ..sync import save_online_only_pdf

        mark = self._watch_mark
        row = self._row_by_mark(mark) if mark else None
        if row is None:
            return
        try:
            data = source.read_bytes()
            path, saved = save_online_only_pdf(self._conn, self._settings, row, data)
        except Exception as exc:  # noqa: BLE001
            log.warning("Αποτυχία αρχειοθέτησης %s: %s", source, exc)
            self._timer.stop()
            self._watch_mark = None
            self._candidate = None
            QMessageBox.warning(
                self, "Δεν αρχειοθετήθηκε",
                f"Το αρχείο {source.name} δεν αρχειοθετήθηκε:\n{exc}",
            )
            self._refresh()
            return

        self._timer.stop()
        self._done.add(mark)
        self._errors.discard(mark)
        self._skipped.discard(mark)
        self._watch_mark = None
        self._candidate = None
        log.info("Μόνο-online αρχειοθετήθηκε: %s (%d B)", path.name, saved)
        self._refresh()
        self.btn_open.setFocus()

    # --------------------------------------------------------- σήμανση σφάλματος
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != _COL_ERR:
            return
        mark = item.data(_MARK_ROLE)
        row = self._row_by_mark(mark)
        if row is None:
            return
        from .. import repo

        if item.checkState() is Qt.CheckState.Checked:
            self._errors.add(mark)
            self._skipped.discard(mark)
            if self._watch_mark == mark:
                self._timer.stop()
                self._watch_mark = None
            repo.mark_failed(
                self._conn, row["client_id"], mark,
                "Μόνο online — δεν ανοίγει/δεν υπάρχει PDF (σήμανση χρήστη)",
                retryable=False,
            )
        else:
            self._errors.discard(mark)
            repo.mark_viewer_only(self._conn, row["client_id"], mark)
        self._conn.commit()
        self._refresh()

    def reject(self) -> None:  # noqa: D401 - Qt override
        self._timer.stop()
        super().reject()

    def accept(self) -> None:  # noqa: D401 - Qt override
        self._timer.stop()
        super().accept()

    @property
    def filed_count(self) -> int:
        return len(self._done)

    @property
    def changed(self) -> bool:
        """Άλλαξε κάτι στη βάση (αρχειοθέτηση ή σήμανση σφάλματος);"""
        return bool(self._done or self._errors)

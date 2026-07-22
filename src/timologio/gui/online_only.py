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
   «Ελήφθη». Έτσι ο χρήστης δεν ψάχνει φακέλους ούτε μετονομάζει τίποτα.

Καμία αυτοματοποιημένη επικοινωνία με τον πάροχο και καμία παράκαμψη ελέγχου:
δουλεύουμε πάνω σε αρχείο που ο χρήστης ήδη κατέβασε ο ίδιος.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings

log = logging.getLogger(__name__)

#: Πόσο συχνά κοιτάμε τον φάκελο λήψεων για νέο PDF.
_POLL_MS = 1500


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
    """Καθοδηγεί: άνοιγμα στον browser → αυτόματη αρχειοθέτηση του PDF."""

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
        self._done: set[str] = set()
        self._downloads = _downloads_dir()

        # Κατάσταση παρακολούθησης του φακέλου λήψεων.
        self._watch_row: sqlite3.Row | None = None
        self._snapshot: dict[str, float] = {}
        self._open_ts: float = 0.0
        self._candidate: tuple[str, int] | None = None

        self.setWindowTitle("Λήψη μόνο-online μέσω του browser σας")
        self.setMinimumWidth(640)
        self._build()
        self._refresh_list()

        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._scan_downloads)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        intro = QLabel(
            "Αυτά τα παραστατικά ο πάροχος τα δείχνει <b>μόνο online</b>, συχνά "
            "πίσω από έλεγχο «είστε άνθρωπος». Πατήστε <b>«Άνοιγμα επόμενου»</b>: "
            "ανοίγει στον browser σας, όπου το αποθηκεύετε ως PDF "
            "(Ctrl+P → «Αποθήκευση ως PDF», ή το κουμπί του παρόχου).<br>"
            "Μόλις το αποθηκεύσετε στις <b>Λήψεις</b>, η εφαρμογή το "
            "αρχειοθετεί <b>μόνη της</b> στον σωστό φάκελο του πελάτη."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        root.addWidget(self.list, 1)

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
        self.btn_open = QPushButton("Άνοιγμα επόμενου στον browser")
        self.btn_open.clicked.connect(self._open_next)
        buttons.addWidget(self.btn_open)

        self.btn_scan = QPushButton("Το αποθήκευσα — έλεγχος τώρα")
        self.btn_scan.setToolTip(
            "Ψάχνει αμέσως τον φάκελο λήψεων για το PDF που μόλις αποθηκεύσατε."
        )
        self.btn_scan.clicked.connect(self._scan_downloads)
        buttons.addWidget(self.btn_scan)

        buttons.addStretch()
        btn_close = QPushButton("Κλείσιμο")
        btn_close.clicked.connect(self.accept)
        buttons.addWidget(btn_close)
        root.addLayout(buttons)
        self._update_status()

    # ------------------------------------------------------------- helpers
    def _pending(self) -> list[sqlite3.Row]:
        return [r for r in self._rows if r["mark"] not in self._done]

    def _label_for(self, row: sqlite3.Row) -> str:
        supplier = row["issuer_name"] or row["counter_name"] or row["issuer_vat"] or "—"
        host = row["provider_host"] or ""
        return f"{_gr_date(row['issue_date'])} · {supplier} · {host}"

    def _refresh_list(self) -> None:
        self.list.clear()
        for row in self._rows:
            done = row["mark"] in self._done
            item = QListWidgetItem(
                f"{'✓' if done else '⧗'}  {self._label_for(row)}"
            )
            if done:
                item.setForeground(Qt.GlobalColor.gray)
            self.list.addItem(item)

    def _update_folder_label(self) -> None:
        self.lbl_folder.setText(f"Φάκελος λήψεων: {self._downloads}")

    def _update_status(self) -> None:
        total = len(self._rows)
        done = len(self._done)
        if self._watch_row is not None:
            self.lbl_status.setText(
                f"Αναμονή αποθήκευσης: {self._label_for(self._watch_row)}  "
                f"—  αποθηκεύστε το PDF στις Λήψεις…   ({done}/{total})"
            )
        elif done >= total and total:
            self.lbl_status.setText(f"Ολοκληρώθηκαν όλα ({done}/{total}).")
        else:
            self.lbl_status.setText(f"Αρχειοθετήθηκαν {done} από {total}.")

    # --------------------------------------------------------------- ροή
    def _choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Φάκελος λήψεων του browser", str(self._downloads)
        )
        if path:
            self._downloads = Path(path)
            self._update_folder_label()

    def _open_next(self) -> None:
        pending = self._pending()
        if not pending:
            QMessageBox.information(
                self, "Τέλος", "Δεν έμειναν άλλα παραστατικά μόνο-online."
            )
            return
        row = pending[0]
        url = row["downloading_invoice_url"]
        if not url:
            self._done.add(row["mark"])
            self._refresh_list()
            self._update_status()
            return

        # Στιγμιότυπο των υπαρχόντων PDF ώστε να ξεχωρίσουμε το νέο.
        self._snapshot = self._pdf_snapshot()
        self._open_ts = self._now()
        self._candidate = None
        self._watch_row = row
        QDesktopServices.openUrl(QUrl(url))
        self._timer.start()
        self._update_status()

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
        if self._watch_row is None:
            return
        from ..download import is_complete_pdf

        # Νέο ή μόλις τροποποιημένο PDF μετά το άνοιγμα (καλύπτει και το
        # «Invoice.pdf» που ξαναγράφεται με το ίδιο όνομα).
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

        # Σταθερότητα: το ίδιο αρχείο με ίδιο μέγεθος σε δύο διαδοχικούς
        # ελέγχους — αλλιώς μπορεί να το πιάσουμε μισογραμμένο.
        if self._candidate != (str(newest), size):
            self._candidate = (str(newest), size)
            return

        self._file_pdf(newest)

    def _file_pdf(self, source: Path) -> None:
        from ..sync import save_online_only_pdf

        row = self._watch_row
        assert row is not None
        try:
            data = source.read_bytes()
            path, saved = save_online_only_pdf(self._conn, self._settings, row, data)
        except Exception as exc:  # noqa: BLE001
            log.warning("Αποτυχία αρχειοθέτησης %s: %s", source, exc)
            self._timer.stop()
            self._watch_row = None
            self._candidate = None
            QMessageBox.warning(
                self, "Δεν αρχειοθετήθηκε",
                f"Το αρχείο {source.name} δεν αρχειοθετήθηκε:\n{exc}",
            )
            self._update_status()
            return

        self._timer.stop()
        self._done.add(row["mark"])
        self._watch_row = None
        self._candidate = None
        log.info("Μόνο-online αρχειοθετήθηκε: %s (%d B)", path.name, saved)
        self._refresh_list()
        self._update_status()

        # Αν έμειναν κι άλλα, προτείνουμε το επόμενο αμέσως.
        if self._pending():
            self.btn_open.setText("Άνοιγμα επόμενου στον browser")
            self.btn_open.setFocus()

    def reject(self) -> None:  # noqa: D401 - Qt override
        self._timer.stop()
        super().reject()

    def accept(self) -> None:  # noqa: D401 - Qt override
        self._timer.stop()
        super().accept()

    @property
    def filed_count(self) -> int:
        return len(self._done)

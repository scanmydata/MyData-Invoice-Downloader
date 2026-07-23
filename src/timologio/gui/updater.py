"""Ενημέρωση με ένα κλικ.

Ροή, μετά την επιβεβαίωση του χρήστη:

1. **Αντίγραφο ασφαλείας της βάσης** — πάντα, πριν από οτιδήποτε άλλο.
2. Κατέβασμα του νέου installer (με μπάρα προόδου).
3. Κλείσιμο της εφαρμογής και σιωπηλή εγκατάσταση από ένα μικρό script που
   περιμένει πρώτα να ξεκλειδώσουν τα αρχεία, και μετά ξαναανοίγει την εφαρμογή.

Δεν υπάρχει «κρυφή» ενημέρωση: τίποτα δεν κατεβαίνει ή εγκαθίσταται χωρίς το
ρητό «Ενημέρωση τώρα». Η αυτόματη εγκατάσταση δουλεύει μόνο στο πακεταρισμένο
exe· από πηγαίο κώδικα προσφέρουμε μόνο τον σύνδεσμο.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QTextBrowser,
    QVBoxLayout,
)

from .. import updates
from ..backup import create_backup
from ..config import load_start_minimized

log = logging.getLogger(__name__)


def can_self_update() -> bool:
    """Μόνο το πακεταρισμένο exe στα Windows μπορεί να αυτο-ενημερωθεί."""
    return bool(getattr(sys, "frozen", False)) and os.name == "nt"


class CheckWorker(QObject):
    """Ρωτά το GitHub εκτός GUI thread. Εκπέμπει ολόκληρο το UpdateInfo."""

    ok = Signal(object)   # updates.UpdateInfo
    failed = Signal(str)

    def __init__(self, current: str) -> None:
        super().__init__()
        self._current = current

    def run(self) -> None:
        try:
            info = updates.check(self._current)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.ok.emit(info)


class _Downloader(QObject):
    progress = Signal(int, int)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, url: str, dest: Path) -> None:
        super().__init__()
        self._url = url
        self._dest = dest

    def run(self) -> None:
        try:
            updates.download(
                self._url, self._dest,
                progress=lambda d, t: self.progress.emit(d, t),
            )
        except Exception as exc:  # δίκτυο/δίσκος — το αναφέρουμε, δεν σκάμε
            self.failed.emit(str(exc))
            return
        self.done.emit(str(self._dest))


class Updater(QObject):
    """Κρατά ζωντανά το thread και τον διάλογο προόδου κατά τη λήψη."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self._thread: QThread | None = None
        self._worker: _Downloader | None = None
        self._dialog: QProgressDialog | None = None

    # ------------------------------------------------------------ προσφορά
    def offer(self, info: updates.UpdateInfo) -> None:
        """Δείχνει την προσφορά ενημέρωσης με τις σημειώσεις της νέας έκδοσης.

        Καλείται μόνο όταν υπάρχει νεότερη έκδοση.
        """
        auto = can_self_update() and info.can_auto_install
        dialog = QDialog(self._window)
        dialog.setWindowTitle("Διαθέσιμη ενημέρωση")
        dialog.setMinimumWidth(560)
        root = QVBoxLayout(dialog)
        root.setSpacing(10)

        head = QLabel(
            f"Υπάρχει νεότερη έκδοση: <b>{info.latest}</b>  "
            f"(έχετε την {info.current})."
        )
        head.setTextFormat(Qt.TextFormat.RichText)
        head.setWordWrap(True)
        root.addWidget(head)

        # --- Σημειώσεις έκδοσης (τι νέο υπάρχει), σε κυλιόμενο πλαίσιο.
        if info.notes:
            caption = QLabel("Τι νέο υπάρχει σε αυτή την έκδοση:")
            caption.setStyleSheet("font-weight:600;")
            root.addWidget(caption)
            notes = QTextBrowser()
            notes.setOpenExternalLinks(True)
            notes.setMarkdown(info.notes)
            notes.setMinimumHeight(220)
            root.addWidget(notes, 1)

        info_text = QLabel(
            "Θα κρατηθεί <b>αντίγραφο ασφαλείας</b> της βάσης, θα κατέβει και θα "
            "εγκατασταθεί η νέα έκδοση, και η εφαρμογή θα ανοίξει ξανά. Τα "
            "δεδομένα σας δεν αγγίζονται."
            if auto else
            "Θα ανοίξει η σελίδα λήψης στον browser για να κατεβάσετε τη νέα "
            "έκδοση."
        )
        info_text.setTextFormat(Qt.TextFormat.RichText)
        info_text.setWordWrap(True)
        info_text.setObjectName("muted")
        root.addWidget(info_text)

        buttons = QDialogButtonBox()
        buttons.addButton(
            "Ενημέρωση τώρα" if auto else "Άνοιγμα σελίδας λήψης",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        buttons.addButton("Αργότερα", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        root.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if auto:
            self._start(info)
        else:
            QDesktopServices.openUrl(QUrl(info.url))

    # ------------------------------------------------------------ εκτέλεση
    def _start(self, info: updates.UpdateInfo) -> None:
        # 1) Αντίγραφο ασφαλείας — πάντα, πριν από οτιδήποτε.
        try:
            backup = create_backup(self._window.settings.db_path, reason="update")
            log.info("Αντίγραφο πριν την ενημέρωση: %s", backup)
        except Exception as exc:
            QMessageBox.critical(
                self._window, "Απέτυχε το αντίγραφο ασφαλείας",
                "Δεν κρατήθηκε αντίγραφο της βάσης, οπότε η ενημέρωση "
                f"ματαιώθηκε για ασφάλεια.\n\n{exc}",
            )
            return

        # 2) Λήψη installer με μπάρα προόδου.
        dest = Path(tempfile.gettempdir()) / (info.asset_name or "setup.exe")
        self._dialog = QProgressDialog(
            "Λήψη ενημέρωσης…", "Ακύρωση", 0, 100, self._window
        )
        self._dialog.setWindowTitle("Ενημέρωση")
        self._dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._dialog.setMinimumDuration(0)
        self._dialog.setAutoClose(False)
        self._dialog.canceled.connect(self._cancel)

        self._thread = QThread(self)
        self._worker = _Downloader(info.asset_url, dest)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_downloaded)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    def _on_progress(self, done: int, total: int) -> None:
        if self._dialog is None:
            return
        if total:
            self._dialog.setValue(int(done * 100 / total))
            self._dialog.setLabelText(
                f"Λήψη ενημέρωσης… {done // (1024*1024)} / {total // (1024*1024)} MB"
            )
        else:
            self._dialog.setValue(0)

    def _cancel(self) -> None:
        self._teardown()

    def _teardown(self) -> None:
        if self._thread:
            self._thread.quit()
            self._thread.wait(3000)
        self._thread = None
        self._worker = None
        if self._dialog:
            self._dialog.close()
            self._dialog = None

    def _on_failed(self, detail: str) -> None:
        self._teardown()
        QMessageBox.warning(
            self._window, "Η ενημέρωση δεν ολοκληρώθηκε",
            "Δεν ήταν δυνατή η λήψη της νέας έκδοσης.\n\n"
            f"{detail[:300]}\n\nΔοκιμάστε ξανά αργότερα.",
        )

    def _on_downloaded(self, path: str) -> None:
        setup = Path(path)
        self._teardown()
        self._launch_installer(setup)

    def _launch_installer(self, setup: Path) -> None:
        window = self._window
        app_exe = Path(sys.executable)
        script = updates.build_updater_script(
            pid=os.getpid(),
            setup=setup,
            app_exe=app_exe,
            data_dir=window.settings.data_dir,
            role=window._role,
            tray=load_start_minimized(),
            # Ο φάκελος όπου τρέχει ΤΩΡΑ η εφαρμογή — εκεί ακριβώς εγκαθιστούμε τη
            # νέα έκδοση, ώστε να μη «χαθεί» σε άλλον φάκελο (βλ. build_updater_script).
            install_dir=app_exe.parent,
        )
        script_path = Path(tempfile.gettempdir()) / "timologio_update.ps1"
        # UTF-8 με BOM: το Windows PowerShell 5.1 διαβάζει αλλιώς ANSI και θα
        # χαλούσε τις ελληνικές διαδρομές.
        script_path.write_text(script, encoding="utf-8-sig")

        log.info("Εκκίνηση ενημέρωσης — η εφαρμογή κλείνει.")
        # Πλήρης διαδρομή του PowerShell: το PATH δεν είναι εγγυημένο μέσα στο
        # πακεταρισμένο περιβάλλον, και ένα σκέτο "powershell" μπορεί να μη βρεθεί.
        powershell = str(
            Path(os.environ.get("SystemRoot", r"C:\Windows"))
            / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        )
        if not Path(powershell).exists():
            powershell = "powershell"
        cmd = [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-WindowStyle", "Hidden", "-File", str(script_path)]
        detached = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        # ΚΡΙΣΙΜΟ: πολλά περιβάλλοντα (installers, launchers, ακόμη κι ο Explorer
        # σε ορισμένες περιπτώσεις) βάζουν την εφαρμογή σε Job Object με
        # «kill-on-close». Όταν κλείνει η εφαρμογή, το job σκοτώνει ΚΑΙ το
        # detached PowerShell πριν προλάβει να εγκαταστήσει — γι' αυτό «κατέβαινε
        # το αρχείο αλλά δεν γινόταν install». Το CREATE_BREAKAWAY_FROM_JOB το
        # βγάζει από το job ώστε να επιβιώσει. Αν το job δεν επιτρέπει breakaway,
        # η CreateProcess αποτυγχάνει — τότε ξαναδοκιμάζουμε χωρίς αυτό.
        CREATE_BREAKAWAY_FROM_JOB = 0x01000000
        try:
            subprocess.Popen(
                cmd, creationflags=detached | CREATE_BREAKAWAY_FROM_JOB,
                close_fds=True,
            )
        except OSError:
            log.warning("Breakaway from job απέτυχε — εκκίνηση χωρίς αυτό.")
            subprocess.Popen(cmd, creationflags=detached, close_fds=True)
        # Κλείνουμε «στα σοβαρά»: το script περιμένει να τερματίσουμε πριν
        # αντικαταστήσει τα αρχεία.
        window._really_quit = True
        try:
            window.conn.close()
        except Exception:
            pass
        QApplication.quit()

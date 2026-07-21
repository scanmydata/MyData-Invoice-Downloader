"""Background worker για το GUI.

Ο πυρήνας (sync.py) δεν ξέρει τίποτα για Qt. Εδώ είναι το μόνο σημείο
συνάντησης: ένα QObject που ζει σε QThread και μεταφράζει την πρόοδο σε signals.

Από τα signals περνούν μόνο απλοί τύποι — ποτέ sqlite3 objects ή connections.
"""

from __future__ import annotations

import threading
import traceback
from collections.abc import Sequence

from PySide6.QtCore import QObject, Signal, Slot

from .. import repo
from ..config import load_settings
from ..crypto import Crypto
from ..db import init_db
from ..models import ClientStatus, Direction


class SyncWorker(QObject):
    """Τρέχει έναν πλήρη κύκλο συγχρονισμού."""

    client_started = Signal(str, str)      # vat, label
    client_finished = Signal(str, int, int, int)  # vat, found, pdfs, failed
    message = Signal(str)
    totals = Signal(int, int, int, int, int)  # found, pdfs, no_url, viewer_only, failed
    finished = Signal(bool)                # ολοκληρώθηκε χωρίς ακύρωση
    failed = Signal(str)
    busy = Signal(str)                     # άλλος υπολογιστής κατεβάζει ήδη

    def __init__(
        self,
        vats: list[str],
        date_from: str,
        date_to: str,
        full: bool,
        directions: Sequence[Direction] | None = None,
        use_vies: bool = True,
    ) -> None:
        super().__init__()
        self._vats = vats
        self._date_from = date_from
        self._date_to = date_to
        self._full = full
        self._directions = tuple(directions) if directions else (
            Direction.INCOMING, Direction.OUTGOING
        )
        self._use_vies = use_vies
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()
        self.message.emit("Ακύρωση… ολοκληρώνεται ο τρέχων πελάτης.")

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @Slot()
    def run(self) -> None:
        from ..locking import LockBusy, SyncLock
        from ..sync import sync_client

        settings = load_settings()
        lock = SyncLock(settings.data_dir)
        try:
            lock.acquire()
        except LockBusy as exc:
            # Άλλο τερματικό κατεβάζει ήδη — μην κάνουμε τη δουλειά δύο φορές.
            self.busy.emit(exc.message_el)
            self.finished.emit(False)
            return

        try:
            # Η σύνδεση ανοίγει ΜΕΣΑ στο thread: τα sqlite connections δεν
            # μοιράζονται με ασφάλεια ανάμεσα σε threads.
            conn = init_db(settings.db_path)
            crypto = Crypto(settings.enckey_path)

            run_id = repo.start_run(conn, self._date_from, self._date_to, len(self._vats))
            found = pdfs = no_url = viewer_only = failed = 0

            for vat in self._vats:
                if self._cancel.is_set():
                    break
                client = repo.get_client(conn, vat, crypto)
                if client is None or client.status is not ClientStatus.READY:
                    continue

                self.client_started.emit(client.vat, client.label)
                lock.touch()
                stats = sync_client(
                    conn,
                    client,
                    settings,
                    date_from=self._date_from,
                    date_to=self._date_to,
                    incremental=not self._full,
                    directions=self._directions,
                    use_vies=self._use_vies,
                    progress=lambda m: self.message.emit(m),
                )
                found += stats.docs_found
                pdfs += stats.pdfs_ok
                no_url += stats.no_url
                viewer_only += stats.viewer_only
                failed += stats.failed
                repo.log_event(
                    conn, run_id, client_vat=client.vat, event="sync",
                    detail=f"found={stats.docs_found} pdf={stats.pdfs_ok}",
                )
                conn.commit()
                self.client_finished.emit(
                    client.vat, stats.docs_found, stats.pdfs_ok, stats.failed
                )
                self.totals.emit(found, pdfs, no_url, viewer_only, failed)

            repo.finish_run(conn, run_id, "aborted" if self._cancel.is_set() else "completed")
            conn.close()
            self.finished.emit(not self._cancel.is_set())
        except Exception as exc:  # το thread δεν πρέπει ποτέ να πεθάνει σιωπηλά
            self.failed.emit(f"{exc}\n\n{traceback.format_exc()}")
        finally:
            lock.release()

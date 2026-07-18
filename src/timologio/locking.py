"""Κλείδωμα λήψης μεταξύ υπολογιστών.

Όταν η βάση κάθεται σε δικτυακό φάκελο, δύο τερματικά μπορεί να πατήσουν «Λήψη»
ταυτόχρονα. Το SQLite θα σεριάριζε τις εγγραφές, αλλά η δουλειά θα γινόταν δύο
φορές και τα δύο μηχανήματα θα κατέβαζαν τα ίδια PDF.

Χρησιμοποιούμε αποκλειστικό άνοιγμα αρχείου (O_EXCL), που λειτουργεί αξιόπιστα
και πάνω από SMB — σε αντίθεση με τα advisory locks του SQLite σε WAL.
Το lock κρατά ποιος το πήρε και πότε, ώστε ένα ορφανό lock από crash να
αναγνωρίζεται και να σπάει μετά από STALE_AFTER.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

#: Μετά από τόση ώρα χωρίς ανανέωση, το lock θεωρείται ορφανό (crash/restart).
STALE_AFTER = timedelta(minutes=30)

LOCK_NAME = "sync.lock"


class LockBusy(Exception):
    """Κάποιος άλλος τρέχει ήδη λήψη."""

    def __init__(self, holder: str, since: str) -> None:
        super().__init__(f"{holder} από {since}")
        self.holder = holder
        self.since = since

    @property
    def message_el(self) -> str:
        return (
            f"Εκτελείται ήδη λήψη από «{self.holder}» (από {self.since}).\n\n"
            "Περιμένετε να ολοκληρωθεί ή δοκιμάστε αργότερα."
        )


@dataclass
class LockInfo:
    holder: str
    since: str


class SyncLock:
    """Context manager: `with SyncLock(data_dir): ...`"""

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / LOCK_NAME
        self._fd: int | None = None

    @property
    def holder_name(self) -> str:
        try:
            user = os.environ.get("USERNAME") or os.environ.get("USER") or "?"
            return f"{socket.gethostname()}\\{user}"
        except Exception:
            return "άγνωστος"

    def _read(self) -> LockInfo | None:
        try:
            data = json.loads(self._path.read_text("utf-8"))
            return LockInfo(holder=data.get("holder", "?"), since=data.get("since", "?"))
        except (OSError, ValueError):
            return None

    def read_info(self) -> LockInfo | None:
        """Ποιος κρατά το lock αυτή τη στιγμή — None αν δεν το κρατά κανείς.

        Για εμφάνιση μόνο: ανάμεσα στην ανάγνωση και σε ό,τι κάνει ο καλών, το
        lock μπορεί να έχει ήδη ελευθερωθεί. Για αποκλεισμό χρησιμοποιήστε το
        ``acquire()``, που είναι ατομικό.
        """
        return self._read() if self._path.exists() else None

    def _is_stale(self) -> bool:
        try:
            age = time.time() - self._path.stat().st_mtime
            return age > STALE_AFTER.total_seconds()
        except OSError:
            return False

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        except FileExistsError:
            info = self._read()
            if self._is_stale():
                log.warning("Σπάω ορφανό lock από %s", info.holder if info else "άγνωστο")
                try:
                    self._path.unlink()
                except PermissionError:
                    # Τα Windows δεν αφήνουν διαγραφή ανοιχτού αρχείου: κάποιος
                    # ζωντανός το κρατά ακόμη, όσο παλιό κι αν δείχνει. Μια
                    # μακρά λήψη που ξέχασε να κάνει touch δεν είναι λόγος να
                    # τρέξουν δύο μηχανήματα μαζί.
                    log.info("Το lock φαίνεται ορφανό αλλά είναι σε χρήση.")
                except OSError:
                    pass
                else:
                    self.acquire()
                    return
            raise LockBusy(
                info.holder if info else "άλλον υπολογιστή",
                info.since if info else "άγνωστη ώρα",
            ) from None

        payload = json.dumps(
            {"holder": self.holder_name, "since": datetime.now().strftime("%d/%m/%Y %H:%M")},
            ensure_ascii=False,
        )
        os.write(self._fd, payload.encode("utf-8"))

    def touch(self) -> None:
        """Ανανεώνει το mtime ώστε μια μακρά λήψη να μη θεωρηθεί ορφανή."""
        try:
            os.utime(self._path, None)
        except OSError:
            pass

    def release(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        self._path.unlink(missing_ok=True)

    def __enter__(self) -> SyncLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()

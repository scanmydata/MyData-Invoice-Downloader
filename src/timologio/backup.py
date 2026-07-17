"""Αντίγραφα ασφαλείας της βάσης.

Η βάση κρατά τα credentials και το ιστορικό λήψεων· τα PDF ξανακατεβαίνουν, η
βάση όχι. Παίρνουμε αντίγραφο **πριν** από κάθε import και κάθε sync — δηλαδή
πριν από κάθε ενέργεια που γράφει.

Χρησιμοποιείται το sqlite3 backup API αντί για απλό copy: δουλεύει σωστά ακόμη
κι όταν η βάση είναι ανοιχτή σε WAL mode, όπου ένα σκέτο copy μπορεί να πιάσει
ασυνεπές snapshot.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

#: Πόσα αντίγραφα κρατάμε ανά είδος.
KEEP = 10

_STAMP = "%Y%m%d-%H%M%S"


def backup_dir(data_dir: Path) -> Path:
    return data_dir / "backups"


def create_backup(db_path: Path, reason: str = "manual") -> Path | None:
    """Φτιάχνει αντίγραφο. Επιστρέφει τη διαδρομή, ή None αν δεν υπάρχει βάση.

    Ποτέ δεν σηκώνει εξαίρεση προς τα πάνω: ένα αποτυχημένο backup δεν πρέπει
    να εμποδίσει τη δουλειά του χρήστη — απλώς καταγράφεται.
    """
    if not db_path.exists():
        return None
    target_dir = backup_dir(db_path.parent)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime(_STAMP)
    target = target_dir / f"timologio-{stamp}-{reason}.db"

    try:
        source = sqlite3.connect(db_path)
        dest = sqlite3.connect(target)
        with dest:
            source.backup(dest)  # συνεπές snapshot ακόμη και σε WAL
        dest.close()
        source.close()
    except sqlite3.Error as exc:
        log.warning("Αποτυχία αντιγράφου ασφαλείας: %s", exc)
        target.unlink(missing_ok=True)
        return None

    prune(target_dir, reason)
    log.info("Αντίγραφο ασφαλείας: %s", target.name)
    return target


def prune(target_dir: Path, reason: str, keep: int = KEEP) -> int:
    """Κρατά τα `keep` νεότερα αντίγραφα του ίδιου είδους."""
    files = sorted(
        target_dir.glob(f"timologio-*-{reason}.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for old in files[keep:]:
        try:
            old.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def list_backups(data_dir: Path) -> list[tuple[Path, datetime, int]]:
    """(διαδρομή, ημερομηνία, μέγεθος) — νεότερα πρώτα."""
    target_dir = backup_dir(data_dir)
    if not target_dir.exists():
        return []
    out = []
    for path in target_dir.glob("timologio-*.db"):
        stat = path.stat()
        out.append((path, datetime.fromtimestamp(stat.st_mtime), stat.st_size))
    return sorted(out, key=lambda row: row[1], reverse=True)


def restore(backup_path: Path, db_path: Path) -> Path:
    """Επαναφέρει αντίγραφο.

    Η τρέχουσα βάση δεν διαγράφεται: κρατιέται ως αντίγραφο «pre-restore», ώστε
    μια λάθος επαναφορά να είναι αναστρέψιμη.
    """
    if not backup_path.exists():
        raise FileNotFoundError(f"Δεν βρέθηκε το αντίγραφο: {backup_path}")

    safety = create_backup(db_path, reason="pre-restore")

    # Τα WAL/SHM του τρέχοντος αρχείου πρέπει να φύγουν, αλλιώς η SQLite μπορεί
    # να τα ξαναπαίξει πάνω στην επαναφερμένη βάση.
    for extra in (db_path.with_suffix(db_path.suffix + "-wal"),
                  db_path.with_suffix(db_path.suffix + "-shm")):
        extra.unlink(missing_ok=True)

    source = sqlite3.connect(backup_path)
    dest = sqlite3.connect(db_path)
    with dest:
        source.backup(dest)
    dest.close()
    source.close()

    log.info("Έγινε επαναφορά από %s (ασφάλεια: %s)", backup_path.name,
             safety.name if safety else "—")
    return db_path

"""Ποιος είναι συνδεδεμένος, και είναι όντως προσβάσιμη η βάση;

Δεν υπάρχει διεργασία-διακομιστής να κρατά συνεδρίες: ο «server» είναι απλώς ο
υπολογιστής που φιλοξενεί τον φάκελο, και τα τερματικά ανοίγουν το ίδιο αρχείο
SQLite μέσω SMB. Άρα «συνδεδεμένος» δεν είναι κάτι που μπορούμε να ρωτήσουμε —
πρέπει να το **καταγράψουμε**.

Κάθε instance γράφει έναν παλμό στον πίνακα ``peers`` κάθε
``HEARTBEAT_SECONDS``. Όποιος έγραψε μέσα στο ``ONLINE_WINDOW`` θεωρείται
ενεργός. Ένα μηχάνημα που κλείνει απότομα (crash, διακοπή ρεύματος, χαμένο
δίκτυο) απλώς σταματά να γράφει και σβήνει μόνο του από τη λίστα — δεν
χρειάζεται καθαρισμός που, ούτως ή άλλως, δεν θα προλάβαινε να τρέξει.

Ο παλμός είναι **best-effort**: αν η βάση είναι κλειδωμένη από μια λήψη που
τρέχει, ο παλμός χάνεται σιωπηλά. Ένα χαμένο heartbeat δεν είναι λόγος να δει ο
χρήστης σφάλμα, και σίγουρα δεν είναι λόγος να διακοπεί η λήψη.
"""

from __future__ import annotations

import logging
import os
import socket
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

#: Κάθε πόσο γράφει παλμό το κάθε instance.
HEARTBEAT_SECONDS = 30

#: Πόσο μετά τον τελευταίο παλμό θεωρείται κάποιος ακόμη ενεργός. Τρεις παλμοί:
#: ένας χαμένος λόγω κλειδωμένης βάσης δεν πρέπει να τον βγάζει «εκτός».
ONLINE_WINDOW = timedelta(seconds=HEARTBEAT_SECONDS * 3)

#: Μετά από τόσο καιρό αδράνειας, η θέση εργασίας φεύγει εντελώς από τη λίστα.
FORGET_AFTER = timedelta(days=30)

_TS = "%Y-%m-%d %H:%M:%S"


def _now() -> str:
    return datetime.now(timezone.utc).strftime(_TS)


def _parse(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, _TS).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def host_name() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "άγνωστος"


def user_name() -> str:
    return os.environ.get("USERNAME") or os.environ.get("USER") or "?"


def this_id() -> str:
    return f"{host_name()}|{user_name()}"


@dataclass(frozen=True)
class Peer:
    host: str
    username: str
    role: str
    version: str
    data_dir: str
    first_seen: str
    last_seen: str
    online: bool
    is_self: bool

    @property
    def label(self) -> str:
        return f"{self.host}\\{self.username}"

    def last_seen_local(self) -> str:
        """Ο χρόνος αποθηκεύεται σε UTC — εδώ γίνεται τοπική ώρα για τον χρήστη."""
        stamp = _parse(self.last_seen)
        if stamp is None:
            return "—"
        return stamp.astimezone().strftime("%d/%m/%Y %H:%M")

    def ago_el(self) -> str:
        stamp = _parse(self.last_seen)
        if stamp is None:
            return "—"
        seconds = int((datetime.now(timezone.utc) - stamp).total_seconds())
        if seconds < HEARTBEAT_SECONDS * 2:
            return "τώρα"
        if seconds < 3600:
            return f"πριν {seconds // 60} λεπτά"
        if seconds < 86400:
            return f"πριν {seconds // 3600} ώρες"
        return f"πριν {seconds // 86400} ημέρες"


def heartbeat(
    conn: sqlite3.Connection, *, role: str, version: str, data_dir: Path
) -> bool:
    """Γράφει τον παλμό αυτού του instance. False αν δεν τα κατάφερε."""
    now = _now()
    try:
        conn.execute(
            "INSERT INTO peers(id, host, username, role, version, pid, data_dir,"
            "                  first_seen, last_seen) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "  role = excluded.role, version = excluded.version, "
            "  pid = excluded.pid, data_dir = excluded.data_dir, "
            "  last_seen = excluded.last_seen",
            (
                this_id(), host_name(), user_name(), role, version,
                os.getpid(), str(data_dir), now, now,
            ),
        )
        conn.commit()
        return True
    except sqlite3.Error as exc:
        # Κλειδωμένη βάση από τρέχουσα λήψη, ή share που έπεσε στιγμιαία.
        log.debug("Ο παλμός παρουσίας δεν γράφτηκε: %s", exc)
        return False


def forget_old(conn: sqlite3.Connection) -> int:
    """Καθαρίζει θέσεις εργασίας που έχουν πάψει να εμφανίζονται."""
    cutoff = (datetime.now(timezone.utc) - FORGET_AFTER).strftime(_TS)
    try:
        cur = conn.execute("DELETE FROM peers WHERE last_seen < ?", (cutoff,))
        conn.commit()
        return cur.rowcount
    except sqlite3.Error:
        return 0


def list_peers(conn: sqlite3.Connection) -> list[Peer]:
    """Όλες οι θέσεις εργασίας, ενεργές πρώτα."""
    threshold = datetime.now(timezone.utc) - ONLINE_WINDOW
    me = this_id()
    peers: list[Peer] = []
    try:
        rows = conn.execute(
            "SELECT * FROM peers ORDER BY last_seen DESC"
        ).fetchall()
    except sqlite3.Error:
        return []
    for row in rows:
        stamp = _parse(row["last_seen"])
        peers.append(
            Peer(
                host=row["host"],
                username=row["username"],
                role=row["role"],
                version=row["version"],
                data_dir=row["data_dir"],
                first_seen=row["first_seen"],
                last_seen=row["last_seen"],
                online=bool(stamp and stamp >= threshold),
                is_self=row["id"] == me,
            )
        )
    peers.sort(key=lambda p: (not p.online, not p.is_self, p.label.lower()))
    return peers


# --- έλεγχος σύνδεσης -------------------------------------------------------


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class Health:
    checks: list[Check]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def first_problem(self) -> Check | None:
        return next((c for c in self.checks if not c.ok), None)


def check_connection(data_dir: Path, db_path: Path) -> Health:
    """Τι ακριβώς δεν δουλεύει, όταν «δεν δουλεύει».

    Το τερματικό που δεν βλέπει τον server εμφάνιζε μέχρι τώρα απλώς άδεια
    λίστα πελατών — ένα σύμπτωμα που μοιάζει με «χάθηκαν τα δεδομένα». Εδώ
    ξεχωρίζουμε τα βήματα ώστε το μήνυμα να λέει *ποιο* έσπασε.
    """
    from .db import is_network_path

    checks: list[Check] = []

    reachable = data_dir.is_dir()
    checks.append(
        Check(
            "Φάκελος δεδομένων",
            reachable,
            str(data_dir) if reachable else f"Δεν είναι προσβάσιμος: {data_dir}",
        )
    )
    if not reachable:
        checks.append(
            Check(
                "Δικαίωμα εγγραφής", False,
                "Δεν ελέγχθηκε — ο φάκελος δεν είναι προσβάσιμος.",
            )
        )
        checks.append(Check("Βάση δεδομένων", False, "Δεν ελέγχθηκε."))
        return Health(checks)

    probe = data_dir / ".σύνδεση.tmp"
    try:
        probe.write_bytes(b"ok")
        probe.unlink()
        checks.append(Check("Δικαίωμα εγγραφής", True, "Εντάξει"))
    except OSError as exc:
        checks.append(
            Check(
                "Δικαίωμα εγγραφής", False,
                f"Ο φάκελος είναι μόνο για ανάγνωση ({exc.strerror or exc}). "
                "Χρειάζεται δικαίωμα εγγραφής στον κοινόχρηστο φάκελο.",
            )
        )

    if not db_path.exists():
        checks.append(
            Check(
                "Βάση δεδομένων", False,
                "Δεν βρέθηκε βάση. Αν αυτός είναι τερματικό, ελέγξτε ότι "
                "δείχνει στον σωστό φάκελο του server.",
            )
        )
        return Health(checks)

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        clients = conn.execute("SELECT COUNT(*) c FROM clients").fetchone()["c"]
        conn.close()
        size_mb = db_path.stat().st_size / (1024 * 1024)
        checks.append(
            Check("Βάση δεδομένων", True, f"{clients} πελάτες · {size_mb:.1f} MB")
        )
    except (sqlite3.Error, OSError) as exc:
        checks.append(Check("Βάση δεδομένων", False, f"Δεν ανοίγει: {exc}"))
        return Health(checks)

    network = is_network_path(db_path)
    checks.append(
        Check(
            "Τρόπος πρόσβασης",
            True,
            "Μέσω δικτύου — η βάση λειτουργεί σε ασφαλή λειτουργία (rollback "
            "journal)" if network else "Τοπικός δίσκος",
        )
    )
    return Health(checks)

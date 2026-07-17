"""Παρακολούθηση καλυμμένων διαστημάτων και ανίχνευση κενών.

Γιατί υπάρχει αυτό
------------------
Το RequestDocs φιλτράρει ταυτόχρονα με **MARK > mark** και με ημερομηνίες. Ο
incremental cursor (το τελευταίο MARK που είδαμε) είναι σωστός μόνο όσο
προχωράμε μπροστά στον χρόνο. Παράδειγμα που σπάει:

    1. Λήψη 01/01–31/03  -> cursor = 4000123...  (max MARK Μαρτίου)
    2. Λήψη 01/06–30/06  -> cursor = 4000145...  (max MARK Ιουνίου)
    3. Λήψη 01/04–31/05  -> τα MARK του Απριλίου είναι ΜΙΚΡΟΤΕΡΑ του cursor
                            -> η ΑΑΔΕ δεν επιστρέφει τίποτα -> σιωπηλό κενό

Κρατάμε λοιπόν ποια διαστήματα έχουν όντως ζητηθεί. Ο cursor χρησιμοποιείται
μόνο όταν επεκτείνουμε συνεχόμενα ένα ήδη καλυμμένο διάστημα· αλλιώς ζητάμε από
mark=0 και βασιζόμαστε στο UNIQUE(client_id, mark) για να μη διπλογραφτεί τίποτα.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from .models import Direction

ONE_DAY = timedelta(days=1)


def to_iso(value: str) -> str:
    """dd/mm/yyyy -> yyyy-mm-dd (και ISO -> ISO)."""
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) >= 10 and value[4] == "-":
        return value[:10]
    parts = value.split("/")
    if len(parts) == 3:
        d, m, y = (p.strip() for p in parts)
        if len(y) == 4:
            return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    return value


def to_gr(iso: str) -> str:
    """yyyy-mm-dd -> dd/mm/yyyy"""
    if not iso or len(iso) < 10:
        return iso
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"


def _d(iso: str) -> date:
    return date.fromisoformat(iso)


@dataclass(frozen=True)
class Range:
    start: str  # ISO
    end: str    # ISO

    @property
    def days(self) -> int:
        return (_d(self.end) - _d(self.start)).days + 1

    def label(self) -> str:
        return f"{to_gr(self.start)} – {to_gr(self.end)}"


def merge(ranges: list[Range]) -> list[Range]:
    """Ενώνει επικαλυπτόμενα και γειτονικά διαστήματα.

    Γειτονικά = το ένα τελειώνει την προηγούμενη μέρα από την αρχή του άλλου·
    δεν θέλουμε να αναφέρεται «κενό» ανάμεσα σε 31/03 και 01/04.
    """
    valid = [r for r in ranges if r.start and r.end and r.start <= r.end]
    if not valid:
        return []
    out: list[Range] = []
    for r in sorted(valid, key=lambda x: (x.start, x.end)):
        if out and _d(r.start) <= _d(out[-1].end) + ONE_DAY:
            if r.end > out[-1].end:
                out[-1] = Range(out[-1].start, r.end)
        else:
            out.append(r)
    return out


def gaps(ranges: list[Range], within: Range | None = None) -> list[Range]:
    """Τα ακάλυπτα διαστήματα ανάμεσα στα καλυμμένα.

    Με `within` υπολογίζει τα κενά μέσα σε συγκεκριμένο παράθυρο (π.χ. «η
    χρήση 2026»), αλλιώς μόνο ανάμεσα στο πρώτο και το τελευταίο καλυμμένο.
    """
    merged = merge(ranges)
    if within:
        merged = [r for r in merged if not (r.end < within.start or r.start > within.end)]
        merged = [
            Range(max(r.start, within.start), min(r.end, within.end)) for r in merged
        ]
        merged = merge(merged)
        if not merged:
            return [within]

    out: list[Range] = []
    if within and merged and merged[0].start > within.start:
        out.append(Range(within.start, (_d(merged[0].start) - ONE_DAY).isoformat()))
    for a, b in zip(merged, merged[1:]):
        out.append(
            Range((_d(a.end) + ONE_DAY).isoformat(), (_d(b.start) - ONE_DAY).isoformat())
        )
    if within and merged and merged[-1].end < within.end:
        out.append(Range((_d(merged[-1].end) + ONE_DAY).isoformat(), within.end))
    return out


# --------------------------------------------------------------------------
# Πρόσβαση στη βάση
# --------------------------------------------------------------------------

def record(
    conn: sqlite3.Connection, client_id: int, direction: Direction, start: str, end: str
) -> None:
    """Καταγράφει ότι το [start, end] ζητήθηκε ολόκληρο και ολοκληρώθηκε καθαρά."""
    start, end = to_iso(start), to_iso(end)
    if not start or not end or start > end:
        return
    conn.execute(
        """INSERT INTO coverage(client_id, direction, date_from, date_to)
           VALUES(?,?,?,?)""",
        (client_id, direction.value, start, end),
    )
    _compact(conn, client_id, direction)


def _compact(conn: sqlite3.Connection, client_id: int, direction: Direction) -> None:
    """Ενοποιεί τις γραμμές ώστε ο πίνακας να μη φουσκώνει με κάθε sync."""
    rows = fetch(conn, client_id, direction)
    merged = merge(rows)
    if len(merged) == len(rows):
        return
    conn.execute(
        "DELETE FROM coverage WHERE client_id=? AND direction=?",
        (client_id, direction.value),
    )
    conn.executemany(
        """INSERT INTO coverage(client_id, direction, date_from, date_to)
           VALUES(?,?,?,?)""",
        [(client_id, direction.value, r.start, r.end) for r in merged],
    )


def fetch(
    conn: sqlite3.Connection, client_id: int, direction: Direction | None = None
) -> list[Range]:
    sql = "SELECT date_from, date_to FROM coverage WHERE client_id=?"
    params: list = [client_id]
    if direction is not None:
        sql += " AND direction=?"
        params.append(direction.value)
    return [Range(r["date_from"], r["date_to"]) for r in conn.execute(sql, params)]


def can_use_cursor(
    conn: sqlite3.Connection, client_id: int, direction: Direction, start: str, end: str
) -> bool:
    """Αληθές μόνο αν επεκτείνουμε συνεχόμενα ένα ήδη καλυμμένο διάστημα.

    Δηλαδή υπάρχει καλυμμένο [cs, ce] με cs <= start και ce >= start-1: ό,τι
    ζητάμε αρχίζει μέσα (ή ακριβώς μετά) από κάτι που ήδη έχουμε, οπότε όλα τα
    νέα παραστατικά θα έχουν MARK μεγαλύτερο του cursor.

    Σε κάθε άλλη περίπτωση (κενό πριν, ή αναδρομική περίοδος) ο cursor θα έκρυβε
    εγγραφές και πρέπει να ζητήσουμε από mark=0.
    """
    start, end = to_iso(start), to_iso(end)
    if not start:
        return False
    for r in merge(fetch(conn, client_id, direction)):
        if r.start <= start and _d(r.end) + ONE_DAY >= _d(start):
            return True
    return False


def summary(
    conn: sqlite3.Connection, client_id: int, direction: Direction | None = None
) -> tuple[list[Range], list[Range]]:
    """(καλυμμένα, κενά) — τα κενά μόνο ανάμεσα στο πρώτο και το τελευταίο."""
    merged = merge(fetch(conn, client_id, direction))
    return merged, gaps(merged)


def gaps_for_client(conn: sqlite3.Connection, client_id: int) -> list[Range]:
    """Κενά που ισχύουν και για τις δύο κατευθύνσεις.

    Ένα διάστημα θεωρείται κενό μόνο αν λείπει και από τα εισερχόμενα και από τα
    εκδοθέντα: αν λείπει μόνο από τη μία, τα παραστατικά της άλλης υπάρχουν και
    δεν θέλουμε ψεύτικο συναγερμό.
    """
    inc, _ = summary(conn, client_id, Direction.INCOMING)
    out, _ = summary(conn, client_id, Direction.OUTGOING)
    both = merge(inc + out)
    return gaps(both)

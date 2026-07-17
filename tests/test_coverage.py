"""Tests για την κάλυψη διαστημάτων και τα κενά ημερομηνιών."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from timologio import coverage
from timologio.coverage import Range, can_use_cursor, gaps, merge, record, to_gr, to_iso
from timologio.crypto import Crypto
from timologio.db import init_db
from timologio.models import Client, Direction
from timologio.repo import upsert_client


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return init_db(tmp_path / "t.db")


@pytest.fixture
def cid(conn: sqlite3.Connection, tmp_path: Path) -> int:
    crypto = Crypto(tmp_path / ".enckey")
    return upsert_client(
        conn, Client(vat="802576637", mydata_user="u", mydata_key="k" * 32), crypto
    )


# --------------------------------------------------------------------------
# Ημερομηνίες
# --------------------------------------------------------------------------

def test_date_conversions() -> None:
    assert to_iso("01/07/2026") == "2026-07-01"
    assert to_iso("2026-07-01") == "2026-07-01"
    assert to_gr("2026-07-01") == "01/07/2026"


# --------------------------------------------------------------------------
# merge / gaps
# --------------------------------------------------------------------------

def test_merge_joins_overlapping() -> None:
    out = merge([Range("2026-01-01", "2026-03-31"), Range("2026-03-01", "2026-04-30")])
    assert out == [Range("2026-01-01", "2026-04-30")]


def test_merge_joins_adjacent_days() -> None:
    """31/03 και 01/04 είναι συνεχόμενα — δεν υπάρχει κενό ανάμεσά τους."""
    out = merge([Range("2026-01-01", "2026-03-31"), Range("2026-04-01", "2026-06-30")])
    assert out == [Range("2026-01-01", "2026-06-30")]


def test_merge_keeps_real_gap_separate() -> None:
    out = merge([Range("2026-01-01", "2026-03-31"), Range("2026-06-01", "2026-06-30")])
    assert len(out) == 2


def test_gaps_between_ranges() -> None:
    found = gaps([Range("2026-01-01", "2026-03-31"), Range("2026-06-01", "2026-06-30")])
    assert found == [Range("2026-04-01", "2026-05-31")]


def test_no_gaps_when_contiguous() -> None:
    assert gaps([Range("2026-01-01", "2026-03-31"), Range("2026-04-01", "2026-06-30")]) == []


def test_gaps_within_window_reports_edges() -> None:
    """Με παράθυρο «η χρήση 2026», λείπουν και οι άκρες."""
    found = gaps([Range("2026-03-01", "2026-03-31")],
                 within=Range("2026-01-01", "2026-12-31"))
    assert found == [Range("2026-01-01", "2026-02-28"), Range("2026-04-01", "2026-12-31")]


def test_range_label_is_greek() -> None:
    assert Range("2026-01-01", "2026-03-31").label() == "01/01/2026 – 31/03/2026"


# --------------------------------------------------------------------------
# Ο κανόνας του cursor — το bug που αποτρέπει
# --------------------------------------------------------------------------

def test_cursor_refused_for_untouched_period(conn: sqlite3.Connection, cid: int) -> None:
    """Χωρίς καμία κάλυψη, ο cursor δεν πρέπει να χρησιμοποιηθεί."""
    assert not can_use_cursor(conn, cid, Direction.INCOMING, "01/01/2026", "31/03/2026")


def test_cursor_allowed_when_extending_forward(conn: sqlite3.Connection, cid: int) -> None:
    """Το συνηθισμένο: ξανασυγχρονισμός της ίδιας περιόδου, λίγο πιο μπροστά."""
    record(conn, cid, Direction.INCOMING, "01/01/2026", "31/03/2026")
    conn.commit()
    assert can_use_cursor(conn, cid, Direction.INCOMING, "01/01/2026", "30/04/2026")
    # Αρχίζει ακριβώς την επόμενη μέρα -> ακόμη συνεχόμενο
    assert can_use_cursor(conn, cid, Direction.INCOMING, "01/04/2026", "30/04/2026")


def test_cursor_refused_for_earlier_period(conn: sqlite3.Connection, cid: int) -> None:
    """ΤΟ BUG: ζητάμε παλιότερη περίοδο μετά από νεότερη.

    Τα MARK του Απριλίου είναι μικρότερα του cursor του Ιουνίου, οπότε με cursor
    η ΑΑΔΕ δεν θα επέστρεφε τίποτα και το κενό θα έμενε για πάντα.
    """
    record(conn, cid, Direction.INCOMING, "01/06/2026", "30/06/2026")
    conn.commit()
    assert not can_use_cursor(conn, cid, Direction.INCOMING, "01/04/2026", "31/05/2026")


def test_cursor_refused_when_gap_before_requested_range(
    conn: sqlite3.Connection, cid: int
) -> None:
    record(conn, cid, Direction.INCOMING, "01/01/2026", "31/03/2026")
    conn.commit()
    # Κενό ο Απρίλιος -> ζητώντας Μάιο δεν επεκτείνουμε συνεχόμενα
    assert not can_use_cursor(conn, cid, Direction.INCOMING, "01/05/2026", "31/05/2026")


def test_coverage_is_per_direction(conn: sqlite3.Connection, cid: int) -> None:
    record(conn, cid, Direction.INCOMING, "01/01/2026", "31/03/2026")
    conn.commit()
    assert can_use_cursor(conn, cid, Direction.INCOMING, "01/01/2026", "30/04/2026")
    assert not can_use_cursor(conn, cid, Direction.OUTGOING, "01/01/2026", "30/04/2026")


# --------------------------------------------------------------------------
# Αποθήκευση
# --------------------------------------------------------------------------

def test_record_compacts_rows(conn: sqlite3.Connection, cid: int) -> None:
    """Ο πίνακας δεν πρέπει να φουσκώνει με μια γραμμή ανά sync."""
    for _ in range(5):
        record(conn, cid, Direction.INCOMING, "01/01/2026", "31/03/2026")
    conn.commit()
    rows = conn.execute(
        "SELECT COUNT(*) c FROM coverage WHERE client_id=?", (cid,)
    ).fetchone()["c"]
    assert rows == 1


def test_gaps_for_client_needs_both_directions(conn: sqlite3.Connection, cid: int) -> None:
    """Κενό μόνο όταν λείπει και από τις δύο κατευθύνσεις."""
    record(conn, cid, Direction.INCOMING, "01/01/2026", "31/03/2026")
    record(conn, cid, Direction.OUTGOING, "01/04/2026", "30/06/2026")
    conn.commit()
    assert coverage.gaps_for_client(conn, cid) == []


def test_real_gap_is_reported(conn: sqlite3.Connection, cid: int) -> None:
    for d in (Direction.INCOMING, Direction.OUTGOING):
        record(conn, cid, d, "01/01/2026", "31/03/2026")
        record(conn, cid, d, "01/06/2026", "30/06/2026")
    conn.commit()
    found = coverage.gaps_for_client(conn, cid)
    assert found == [Range("2026-04-01", "2026-05-31")]
    assert found[0].label() == "01/04/2026 – 31/05/2026"
    assert found[0].days == 61

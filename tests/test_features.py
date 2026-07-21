"""Tests για τις λειτουργίες που ζητήθηκαν μαζικά.

Καλύπτουν τη λογική που μπορεί να ελεγχθεί χωρίς οθόνη: την πρώτη-εκκίνηση
ξενάγηση (πλέον στη βάση, όχι στο μητρώο), τη μορφοποίηση της «τελευταίας
λήψης», και τη συμπεριφορά του datepicker στη ρόδα του ποντικιού — που ήταν η
αιτία που «άλλαζε μόνο του».
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from timologio import repo  # noqa: E402
from timologio.db import init_db  # noqa: E402


@pytest.fixture
def conn(tmp_path) -> sqlite3.Connection:
    return init_db(tmp_path / "t.db")


# --- meta / πρώτη εκκίνηση --------------------------------------------------


def test_meta_roundtrip(conn):
    assert repo.get_meta(conn, "tour_seen") == ""
    repo.set_meta(conn, "tour_seen", "1")
    assert repo.get_meta(conn, "tour_seen") == "1"


def test_meta_default(conn):
    assert repo.get_meta(conn, "λείπει", "x") == "x"


def test_meta_travels_with_the_database(tmp_path):
    """Η κατάσταση ζει στη βάση: μια νέα βάση δεν «θυμάται» την ξενάγηση.

    Αυτό ήταν το bug — το μητρώο επιβίωνε των εγκαταστάσεων, οπότε ένα καθαρό
    install δεν έδειχνε ποτέ την ξενάγηση.
    """
    a = init_db(tmp_path / "a.db")
    repo.set_meta(a, "tour_seen", "1")
    b = init_db(tmp_path / "b.db")
    assert repo.get_meta(b, "tour_seen") == ""


# --- μορφοποίηση τελευταίας λήψης ------------------------------------------


def test_fmt_last_download_none():
    from timologio.gui.main_window import _fmt_last_download

    assert _fmt_last_download(None) == ("—", 0.0)
    assert _fmt_last_download("") == ("—", 0.0)


def test_fmt_last_download_parses_and_sorts():
    from timologio.gui.main_window import _fmt_last_download

    older_text, older_key = _fmt_last_download("2026-01-01 08:00:00")
    newer_text, newer_key = _fmt_last_download("2026-07-19 12:00:00")
    assert "/" in older_text and ":" in older_text
    # Το κλειδί ταξινόμησης σέβεται τη χρονική σειρά.
    assert newer_key > older_key


def test_fmt_last_download_survives_garbage():
    from timologio.gui.main_window import _fmt_last_download

    assert _fmt_last_download("όχι ημερομηνία") == ("—", 0.0)


# --- datepicker ------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_datepicker_ignores_wheel_when_unfocused(app):
    """Η ρόδα πάνω από το πεδίο ΔΕΝ αλλάζει την ημερομηνία αν δεν έχει εστίαση.

    Αλλιώς, κάθε κύλιση της σελίδας που περνούσε από πάνω άλλαζε σιωπηλά την
    περίοδο — το «datepicker δεν δουλεύει σταθερά»."""
    from datetime import date

    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent

    from timologio.gui.widgets import GrDateEdit

    edit = GrDateEdit(date(2026, 6, 15))
    before = edit.date()
    event = QWheelEvent(
        QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )
    edit.wheelEvent(event)
    assert edit.date() == before


def test_datepicker_roundtrips_greek_format(app):
    from timologio.gui.widgets import GrDateEdit

    edit = GrDateEdit()
    edit.set_gr("07/03/2026")
    assert edit.gr() == "07/03/2026"


# --- έλεγχος ενημερώσεων ----------------------------------------------------


def test_parse_version():
    from timologio.updates import parse_version

    assert parse_version("v0.2.3") == (0, 2, 3)
    assert parse_version("0.2.3") == (0, 2, 3)
    # Αριθμητική σύγκριση, όχι αλφαβητική: 0.2.10 > 0.2.9.
    assert parse_version("0.2.10") > parse_version("0.2.9")


def test_parse_version_survives_garbage():
    from timologio.updates import parse_version

    assert parse_version("") == (0,)
    assert parse_version("έκδοση") == (0,)


@pytest.mark.parametrize(
    "current, latest, expected",
    [
        ("0.2.2", "0.3.0", True),
        ("0.2.2", "0.2.2", False),
        ("0.2.3", "0.2.2", False),   # ποτέ «ενημέρωση» προς τα πίσω
        ("0.2.2", "?", False),       # άκυρη απάντηση δεν προτείνει ενημέρωση
    ],
)
def test_update_is_newer(current, latest, expected):
    from timologio.updates import UpdateInfo

    assert UpdateInfo(current, latest, "http://x").is_newer is expected

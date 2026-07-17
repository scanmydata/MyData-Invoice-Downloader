"""Tests για τις στήλες των πινάκων.

Ζητήθηκε δύο φορές «resizable και reorderable»: την πρώτη φορά έμοιαζε έτοιμο,
αλλά η στήλη της Επωνυμίας ήταν σε Stretch — γέμιζε τον πίνακα και αρνιόταν να
συρθεί, δηλαδή ακριβώς η στήλη που θέλει κανείς να φαρδύνει.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QHeaderView, QTableWidget  # noqa: E402

SPEC = [
    ("", 30, "checkbox"),
    ("ΑΦΜ", 84, ""),
    ("Επωνυμία", 0, "γεμίζει"),
    ("Αξία", 88, ""),
]
FILL = 2


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def prefs(tmp_path):
    """Δικές μας ρυθμίσεις σε αρχείο, για να μη μολύνουμε το μητρώο."""
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    yield settings


@pytest.fixture
def table(app, prefs):
    from timologio.gui.widgets import setup_columns

    widget = QTableWidget(0, len(SPEC))
    widget.setHorizontalHeaderLabels([c[0] for c in SPEC])
    widget.resize(700, 300)
    setup_columns(widget, SPEC, prefs, "probe")
    widget.show()
    yield widget
    widget.hide()


def test_no_column_is_locked(table) -> None:
    header = table.horizontalHeader()
    locked = [
        i for i in range(table.columnCount())
        if header.sectionResizeMode(i) is not QHeaderView.ResizeMode.Interactive
    ]
    assert locked == [], f"κλειδωμένες στήλες: {locked}"


def test_columns_are_movable(table) -> None:
    header = table.horizontalHeader()
    assert header.sectionsMovable()
    before = header.visualIndex(FILL)
    header.moveSection(before, before + 1)
    assert header.visualIndex(FILL) == before + 1


def test_checkbox_column_stays_first(table) -> None:
    """Το κουτάκι επιλογής δεν έχει νόημα στη μέση του πίνακα."""
    assert not table.horizontalHeader().isFirstSectionMovable()


def test_fill_column_is_resizable(table) -> None:
    header = table.horizontalHeader()
    header.resizeSection(FILL, 260)
    assert header.sectionSize(FILL) == 260


def test_fill_column_takes_the_slack(table) -> None:
    header = table.horizontalHeader()
    total = sum(header.sectionSize(i) for i in range(table.columnCount()))
    assert abs(total - table.viewport().width()) <= 2, "έμεινε κενό στα δεξιά"


def test_manual_width_survives_a_window_resize(table) -> None:
    """Μόλις ο χρήστης πιάσει τη στήλη, το πλάτος είναι δικό του."""
    header = table.horizontalHeader()
    header.resizeSection(FILL, 250)
    table.resize(900, 300)
    QApplication.processEvents()
    assert header.sectionSize(FILL) == 250


def test_untouched_column_follows_the_window(table) -> None:
    header = table.horizontalHeader()
    before = header.sectionSize(FILL)
    table.resize(900, 300)
    QApplication.processEvents()
    assert header.sectionSize(FILL) > before, "η στήλη δεν ακολούθησε το πλάτος"


def test_manual_choice_is_remembered(app, prefs, tmp_path) -> None:
    """Δεύτερο άνοιγμα: η στήλη δεν πρέπει να ξαναγεμίσει μόνη της."""
    from timologio.gui.widgets import setup_columns

    first = QTableWidget(0, len(SPEC))
    first.setHorizontalHeaderLabels([c[0] for c in SPEC])
    first.resize(700, 300)
    setup_columns(first, SPEC, prefs, "memory")
    first.show()
    first.horizontalHeader().resizeSection(FILL, 210)
    QApplication.processEvents()

    second = QTableWidget(0, len(SPEC))
    second.setHorizontalHeaderLabels([c[0] for c in SPEC])
    second.resize(1100, 300)
    setup_columns(second, SPEC, prefs, "memory")
    second.show()
    QApplication.processEvents()
    assert second._fill_column._manual, "ξέχασε ότι ο χρήστης όρισε το πλάτος"
    assert second.horizontalHeader().sectionSize(FILL) == 210

"""Η «Έξυπνη λήψη» εμφανίζεται μόνο όταν κατεβαίνουν έξοδα.

Ο χρήστης ζήτησε το κουμπί να φαίνεται μόνο όταν στη λήψη είναι επιλεγμένα τα
έξοδα — έχει νόημα μόνο εκεί (κατεβάζει PDF αχαρακτήριστων εξόδων). Όταν κρύβεται
πρέπει και να ξετσεκάρεται, ώστε να μη μείνει «κρυφά ενεργή».
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from timologio.gui.sync_page import SyncPage  # noqa: E402


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


def _page(app) -> SyncPage:
    return SyncPage(QSettings("scanmydata-test", "smart-visibility"))


def test_visible_when_expenses_on_by_default(app):
    page = _page(app)
    assert page.chk_expense.isChecked()
    assert page._smart_row.isVisibleTo(page)


def test_hidden_and_unchecked_when_expenses_off(app):
    page = _page(app)
    page.chk_smart.setChecked(True)
    page.chk_expense.setChecked(False)
    assert not page._smart_row.isVisibleTo(page)
    # Κρυφή = ξετσεκαρισμένη, ώστε το smart_expenses_only() να μη «διαρρέει».
    assert not page.chk_smart.isChecked()
    assert not page.smart_expenses_only()


def test_reappears_when_expenses_re_enabled(app):
    page = _page(app)
    page.chk_expense.setChecked(False)
    page.chk_expense.setChecked(True)
    assert page._smart_row.isVisibleTo(page)

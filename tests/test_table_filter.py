"""Γρήγορα φίλτρα στηλών (Excel-style): κεφαλίδα με χωνί, ενσωματωμένο popup και
γενικός ελεγκτής που κρύβει γραμμές βάσει του κειμένου των κελιών."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QTableWidget,
    QTableWidgetItem,
)


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    from timologio.gui.theme import apply_theme

    apply_theme(application, "light")
    yield application


def test_table_column_filter_hides_rows(app):
    from timologio.gui.table_filter import FilterHeader, TableColumnFilter

    table = QTableWidget(3, 2)
    for row, name in enumerate(["ΑΛΦΑ", "ΒΗΤΑ", "ΑΛΦΑ"]):
        table.setItem(row, 1, QTableWidgetItem(name))
    ctrl = TableColumnFilter(table, (1,))
    assert isinstance(table.horizontalHeader(), FilterHeader)

    ctrl.filters[1] = {"ΑΛΦΑ"}
    ctrl.apply()
    assert [table.isRowHidden(r) for r in range(3)] == [False, True, False]

    ctrl.filters.clear()
    ctrl.apply()
    assert [table.isRowHidden(r) for r in range(3)] == [False, False, False]


def test_column_filter_popup_live_apply(app):
    """Το popup εφαρμόζει «ζωντανά»: κάθε τσεκάρισμα καλεί το on_apply."""
    from timologio.gui.table_filter import ColumnFilterPopup

    seen: list[set[str]] = []
    popup = ColumnFilterPopup(
        "Στήλη", ["1", "2"], {"1", "2"}, lambda values: seen.append(set(values))
    )
    # ξετσεκάρισμα «(Όλα)» -> καμία τιμή
    popup.list.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert seen[-1] == set()
    # τσεκάρισμα μιας τιμής
    popup.list.item(1).setCheckState(Qt.CheckState.Checked)
    assert seen[-1] == {"1"}


def test_filter_header_reports_active(app):
    from timologio.gui.table_filter import FilterHeader

    table = QTableWidget(1, 3)
    header = FilterHeader((1, 2), table)
    table.setHorizontalHeader(header)
    header.set_active({2})
    assert header._active == {2}

"""Διπλό κλικ στα Παραστατικά: ξαναπροσπάθεια λήψης με ΒΑΣΗ την τωρινή βάση.

Ο χρήστης παραπονέθηκε ότι μετά την έξυπνη λήψη κάποια παραστατικά έδειχναν
«αναμονή» και το διπλό κλικ δεν τα κατέβαζε σωστά. Η ρίζα ήταν ότι η απόφαση
γινόταν με βάση την (παλιά) κατάσταση του πίνακα. Τώρα διαβάζεται φρέσκια από τη
βάση, ώστε ένα ήδη κατεβασμένο να μη «ξανακατεβαίνει» και ένα εκκρεμές/αποτυχημένο
να ξαναδοκιμάζεται.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from timologio.config import Settings  # noqa: E402
from timologio.crypto import Crypto  # noqa: E402
from timologio.db import init_db  # noqa: E402
from timologio.gui.documents_view import DocumentsView  # noqa: E402
from timologio.models import Client, Direction, DocStatus, Document  # noqa: E402
from timologio.repo import upsert_client, upsert_document  # noqa: E402

CLIENT_VAT = "123456783"


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def view(app, tmp_path: Path) -> DocumentsView:
    conn = init_db(tmp_path / "t.db")
    crypto = Crypto(tmp_path / ".enckey")
    cid = upsert_client(
        conn,
        Client(vat=CLIENT_VAT, label="ΔΕΙΓΜΑ ΑΕ", mydata_user="u", mydata_key="k" * 32),
        crypto,
    )
    upsert_document(
        conn, cid,
        Document(mark="m1", invoice_type="1.1", issuer_vat="987654324",
                 counter_vat=CLIENT_VAT, issue_date="2026-07-10", total_value=10.0,
                 direction=Direction.INCOMING,
                 downloading_invoice_url="https://x.gr/a"),
    )
    conn.execute("UPDATE documents SET classification='unclassified'")
    conn.commit()

    dv = DocumentsView(Settings(data_dir=tmp_path), QSettings("scanmydata-test", "dv"))
    dv.show_client(conn, CLIENT_VAT, "ΔΕΙΓΜΑ ΑΕ", "all")
    return dv


def _row(view: DocumentsView) -> sqlite3.Row:
    return view._rows[0]


def test_current_status_reads_fresh_from_db(view: DocumentsView) -> None:
    row = _row(view)
    assert view._current_status(row) == DocStatus.PENDING
    # Προσομοίωση λήψης που ενημέρωσε τη βάση αλλά ΟΧΙ τον πίνακα (cache παλιό).
    view._conn.execute("UPDATE documents SET status='downloaded' WHERE mark='m1'")
    view._conn.commit()
    assert row["status"] == "pending"          # ο πίνακας μένει παλιός
    assert view._current_status(row) == DocStatus.DOWNLOADED  # η βάση, φρέσκια


def test_retry_set_covers_pending_and_failed() -> None:
    assert DocStatus.PENDING in DocumentsView._RETRY_ON_DOUBLE_CLICK
    assert DocStatus.FAILED_RETRYABLE in DocumentsView._RETRY_ON_DOUBLE_CLICK
    assert DocStatus.FAILED_PERMANENT in DocumentsView._RETRY_ON_DOUBLE_CLICK
    assert DocStatus.DOWNLOADED not in DocumentsView._RETRY_ON_DOUBLE_CLICK


def test_double_click_downloads_when_status_pending(view: DocumentsView, monkeypatch) -> None:
    called: list[str] = []
    monkeypatch.setattr(view, "_download_pending_row", lambda r: called.append(r["mark"]))
    monkeypatch.setattr(view, "_toggle_current", lambda: called.append("TOGGLE"))

    class _Idx:
        def row(self):
            return 0

    view._on_double_click(_Idx())
    assert called == ["m1"]


def test_double_click_toggles_when_already_downloaded(view: DocumentsView, monkeypatch) -> None:
    view._conn.execute("UPDATE documents SET status='downloaded' WHERE mark='m1'")
    view._conn.commit()
    called: list[str] = []
    monkeypatch.setattr(view, "_download_pending_row", lambda r: called.append(r["mark"]))
    monkeypatch.setattr(view, "_toggle_current", lambda: called.append("TOGGLE"))

    class _Idx:
        def row(self):
            return 0

    view._on_double_click(_Idx())
    assert called == ["TOGGLE"]  # ήδη κατεβασμένο → δεν ξανακατεβαίνει

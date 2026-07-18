"""Tests για τον διαχωρισμό εσόδων/εξόδων και τα φίλτρα παραστατικών."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from timologio.crypto import Crypto
from timologio.db import init_db
from timologio.models import Classification, Client, Direction, Document
from timologio.reports import analyse_client, documents_for
from timologio.repo import upsert_client, upsert_document

CLIENT_VAT = "123456783"


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    conn = init_db(tmp_path / "t.db")
    crypto = Crypto(tmp_path / ".enckey")
    cid = upsert_client(
        conn,
        Client(vat=CLIENT_VAT, label="ΔΕΙΓΜΑ ΕΜΠΟΡΙΚΗ ΑΕ", mydata_user="u", mydata_key="k" * 32),
        crypto,
    )

    def add(mark, itype, issuer, counter, net, vat, direction=Direction.INCOMING):
        upsert_document(
            conn, cid,
            Document(mark=mark, invoice_type=itype, issuer_vat=issuer,
                     counter_vat=counter, net_value=net, vat_amount=vat,
                     total_value=net + vat, issue_date="2026-07-01",
                     direction=direction, downloading_invoice_url="https://x.gr/a"),
        )

    # Έσοδα: τα εκδίδει ο πελάτης
    add("1", "2.1", CLIENT_VAT, "044004008", 100.0, 24.0, Direction.OUTGOING)
    add("2", "1.1", CLIENT_VAT, "044004008", 200.0, 48.0, Direction.OUTGOING)
    # Έξοδα: τα εκδίδει άλλος
    add("3", "1.1", "987654324", CLIENT_VAT, 50.0, 12.0, Direction.INCOMING)
    # Η ΠΑΓΙΔΑ: 13.1 λιανικό έξοδο — το υποβάλλει ο ΛΗΠΤΗΣ, οπότε είναι
    # «εκδοθέν» (outgoing) αλλά είναι ΕΞΟΔΟ και δεν έχει καθόλου ΑΦΜ εκδότη.
    add("4", "13.1", "", CLIENT_VAT, 10.0, 2.4, Direction.OUTGOING)
    add("5", "14.3", "", CLIENT_VAT, 20.0, 4.8, Direction.OUTGOING)
    conn.commit()
    return conn


def test_income_is_what_the_client_issued(conn: sqlite3.Connection) -> None:
    a = analyse_client(conn, CLIENT_VAT)
    assert a is not None
    assert a.income.count == 2
    assert a.income.net == pytest.approx(300.0)
    assert a.income.gross == pytest.approx(372.0)


def test_retail_expense_docs_are_not_income(conn: sqlite3.Connection) -> None:
    """Τα 13.x/14.x είναι «εκδοθέντα» αλλά ΕΞΟΔΑ.

    Ο αφελής κανόνας «direction=outgoing -> έσοδα» θα τα μετρούσε ως έσοδα.
    Μετρημένα σε πραγματικό πελάτη: 24 τέτοια παραστατικά.
    """
    a = analyse_client(conn, CLIENT_VAT)
    assert a is not None
    assert a.expense.count == 3, "1.1 εισερχόμενο + 13.1 + 14.3"
    assert a.expense.net == pytest.approx(80.0)


def test_income_plus_expense_covers_everything(conn: sqlite3.Connection) -> None:
    a = analyse_client(conn, CLIENT_VAT)
    assert a is not None
    assert a.income.count + a.expense.count == a.total
    assert a.income.net + a.expense.net == pytest.approx(a.net_value)
    assert a.income.gross + a.expense.gross == pytest.approx(a.total_value)


# --------------------------------------------------------------------------
# Φίλτρα — αντιστοιχούν στα πλακίδια της ανάλυσης
# --------------------------------------------------------------------------

def test_filter_income_matches_analysis(conn: sqlite3.Connection) -> None:
    a = analyse_client(conn, CLIENT_VAT)
    assert a is not None
    assert len(documents_for(conn, CLIENT_VAT, "income")) == a.income.count


def test_filter_expense_matches_analysis(conn: sqlite3.Connection) -> None:
    a = analyse_client(conn, CLIENT_VAT)
    assert a is not None
    assert len(documents_for(conn, CLIENT_VAT, "expense")) == a.expense.count


def test_filter_all_returns_everything(conn: sqlite3.Connection) -> None:
    assert len(documents_for(conn, CLIENT_VAT, "all")) == 5


def test_filter_unknown_key_falls_back_to_all(conn: sqlite3.Connection) -> None:
    assert len(documents_for(conn, CLIENT_VAT, "καμία-τέτοια")) == 5


def test_filter_by_status_matches_tiles(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE documents SET status='downloaded' WHERE mark IN ('1','2')")
    conn.execute("UPDATE documents SET status='no_provider_url' WHERE mark='3'")
    conn.execute("UPDATE documents SET status='failed_permanent' WHERE mark='4'")
    conn.commit()

    a = analyse_client(conn, CLIENT_VAT)
    assert a is not None
    assert len(documents_for(conn, CLIENT_VAT, "downloaded")) == a.downloaded == 2
    assert len(documents_for(conn, CLIENT_VAT, "no_provider_url")) == a.no_provider_url == 1
    assert len(documents_for(conn, CLIENT_VAT, "failed")) == a.failed == 1


def test_filter_by_classification_matches_tiles(conn: sqlite3.Connection) -> None:
    from timologio.repo import set_classifications

    set_classifications(conn, 1, {
        "1": Classification.CLASSIFIED,
        "2": Classification.UNCLASSIFIED,
        "3": Classification.UNCLASSIFIED,
    })
    conn.commit()

    a = analyse_client(conn, CLIENT_VAT)
    assert a is not None
    assert len(documents_for(conn, CLIENT_VAT, "classified")) == a.classified == 1
    assert len(documents_for(conn, CLIENT_VAT, "unclassified")) == a.unclassified == 2
    assert len(documents_for(conn, CLIENT_VAT, "unknown_cls")) == a.unknown_classification == 2


def test_documents_are_newest_first(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE documents SET issue_date='2026-01-05' WHERE mark='1'")
    conn.execute("UPDATE documents SET issue_date='2026-12-20' WHERE mark='2'")
    conn.commit()
    rows = documents_for(conn, CLIENT_VAT, "all")
    dates = [r["issue_date"] for r in rows]
    assert dates == sorted(dates, reverse=True)

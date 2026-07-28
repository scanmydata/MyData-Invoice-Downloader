"""Έξυπνη λήψη: PDF μόνο για αχαρακτήριστα έξοδα στο επιλεγμένο διάστημα.

Ο λογιστής θέλει, όταν βιάζεται, να κατεβάζει μόνο ό,τι χρειάζεται για να
χαρακτηρίσει — τα έσοδα και τα ήδη χαρακτηρισμένα να παραλείπονται ώστε η λήψη
να τελειώνει γρήγορα.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from timologio.crypto import Crypto
from timologio.db import init_db
from timologio.models import Client, Direction, Document
from timologio.repo import pending_documents, upsert_client, upsert_document
from timologio.sync import _gr_to_iso

CLIENT_VAT = "123456783"


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    conn = init_db(tmp_path / "t.db")
    crypto = Crypto(tmp_path / ".enckey")
    cid = upsert_client(
        conn, Client(vat=CLIENT_VAT, label="ΔΕΙΓΜΑ ΑΕ",
                     mydata_user="u", mydata_key="k" * 32), crypto,
    )

    def add(mark, issuer, counter, date, direction):
        upsert_document(
            conn, cid,
            Document(mark=mark, invoice_type="1.1", issuer_vat=issuer,
                     counter_vat=counter, issue_date=date, total_value=10.0,
                     direction=direction,
                     downloading_invoice_url="https://x.gr/a"),
        )

    # Έξοδα (εκδότης άλλος) στο διάστημα
    add("exp_unclassified_in", "987654324", CLIENT_VAT, "2026-07-10", Direction.INCOMING)
    add("exp_classified_in", "987654324", CLIENT_VAT, "2026-07-11", Direction.INCOMING)
    add("exp_unclassified_out_of_range", "987654324", CLIENT_VAT, "2026-06-01", Direction.INCOMING)
    # Έσοδο (το εξέδωσε ο πελάτης) — δεν πρέπει να μπει ποτέ στην έξυπνη λήψη
    add("income_unclassified", CLIENT_VAT, "044004008", "2026-07-12", Direction.OUTGOING)
    conn.commit()

    # Χαρακτηρισμοί: μόνο το exp_classified_in είναι χαρακτηρισμένο.
    conn.execute("UPDATE documents SET classification='unclassified'")
    conn.execute(
        "UPDATE documents SET classification='classified' WHERE mark='exp_classified_in'"
    )
    conn.commit()
    return conn


def _client_id(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT id FROM clients WHERE vat=?", (CLIENT_VAT,)).fetchone()["id"]


def test_normal_pending_returns_everything(conn: sqlite3.Connection) -> None:
    marks = {r["mark"] for r in pending_documents(conn, _client_id(conn))}
    assert marks == {
        "exp_unclassified_in", "exp_classified_in",
        "exp_unclassified_out_of_range", "income_unclassified",
    }


def test_smart_keeps_only_unclassified_expenses_in_range(conn: sqlite3.Connection) -> None:
    marks = {
        r["mark"]
        for r in pending_documents(
            conn, _client_id(conn),
            unclassified_expenses_only=True,
            client_vat=CLIENT_VAT,
            date_from_iso="2026-07-01",
            date_to_iso="2026-07-31",
        )
    }
    # Μόνο το αχαρακτήριστο έξοδο μέσα στο διάστημα.
    assert marks == {"exp_unclassified_in"}


def test_gr_to_iso_converts_and_is_robust() -> None:
    assert _gr_to_iso("10/07/2026") == "2026-07-10"
    assert _gr_to_iso("") == ""
    assert _gr_to_iso("οχι-ημερομηνία") == ""

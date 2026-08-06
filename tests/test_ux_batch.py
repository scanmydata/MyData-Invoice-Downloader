"""Δέσμη UX βελτιώσεων: ημερομηνία εκτύπωσης, ονόματα αρχείων ΗΗ-ΜΜ-ΕΕΕΕ,
κατάργηση «ανενεργού» πελάτη.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from timologio.crypto import Crypto
from timologio.db import init_db
from timologio.download.storage import _date_for_name
from timologio.models import Client, Direction, Document
from timologio.repo import (
    mark_printed,
    normalize_disabled_clients,
    upsert_client,
    upsert_document,
)

CLIENT_VAT = "123456783"


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    conn = init_db(tmp_path / "t.db")
    crypto = Crypto(tmp_path / ".enckey")
    cid = upsert_client(
        conn, Client(vat=CLIENT_VAT, label="ΔΕΙΓΜΑ ΑΕ",
                     mydata_user="u", mydata_key="k" * 32), crypto,
    )
    upsert_document(
        conn, cid,
        Document(mark="m1", invoice_type="1.1", issuer_vat="987654324",
                 counter_vat=CLIENT_VAT, issue_date="2026-07-10", total_value=10.0,
                 direction=Direction.INCOMING,
                 downloading_invoice_url="https://x.gr/a"),
    )
    conn.commit()
    return conn


def _cid(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT id FROM clients WHERE vat=?", (CLIENT_VAT,)).fetchone()["id"]


# --- Ημερομηνία εκτύπωσης --------------------------------------------------

def test_print_date_column_exists(conn: sqlite3.Connection) -> None:
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(documents)")}
    assert "print_date" in cols


def test_mark_printed_sets_date(conn: sqlite3.Connection) -> None:
    assert conn.execute("SELECT print_date FROM documents WHERE mark='m1'").fetchone()[0] == ""
    n = mark_printed(conn, _cid(conn), ["m1"], "2026-08-06")
    assert n == 1
    assert conn.execute("SELECT print_date FROM documents WHERE mark='m1'").fetchone()[0] == "2026-08-06"


def test_mark_printed_empty_is_noop(conn: sqlite3.Connection) -> None:
    assert mark_printed(conn, _cid(conn), [], "2026-08-06") == 0


# --- Ονόματα αρχείων ΗΗ-ΜΜ-ΕΕΕΕ -------------------------------------------

def test_date_for_name_greek_order() -> None:
    assert _date_for_name("2026-01-02") == "02-01-2026"
    assert _date_for_name("2026-12-31") == "31-12-2026"


def test_date_for_name_bad_input_falls_back() -> None:
    assert _date_for_name("") == "00-00-0000"
    # Μη-ISO αλλά μη κενό: περνά ως έχει (καθαρισμένο), δεν σκάει.
    assert _date_for_name("2026") == "2026"


# --- Κατάργηση «ανενεργού» πελάτη ------------------------------------------

def test_normalize_disabled_recomputes_from_credentials(conn: sqlite3.Connection) -> None:
    # Παλιά βάση με «disabled» πελάτη που στην πραγματικότητα έχει κλειδί.
    conn.execute("UPDATE clients SET status='disabled' WHERE vat=?", (CLIENT_VAT,))
    conn.commit()
    n = normalize_disabled_clients(conn)
    assert n == 1
    status = conn.execute("SELECT status FROM clients WHERE vat=?", (CLIENT_VAT,)).fetchone()[0]
    assert status == "ready"  # έχει user+key → ξαναγίνεται διαθέσιμος


def test_new_client_ready_only_with_both_credentials(tmp_path: Path) -> None:
    conn = init_db(tmp_path / "t2.db")
    crypto = Crypto(tmp_path / ".enckey2")
    upsert_client(conn, Client(vat="044004008", label="ΜΙΣΟΣ", mydata_user="u",
                               mydata_key=""), crypto)
    upsert_client(conn, Client(vat="044222111", label="ΠΛΗΡΗΣ", mydata_user="u",
                               mydata_key="k" * 32), crypto)
    half = conn.execute("SELECT status FROM clients WHERE vat='044004008'").fetchone()[0]
    full = conn.execute("SELECT status FROM clients WHERE vat='044222111'").fetchone()[0]
    assert half == "missing_key"   # λείπει κλειδί → όχι διαθέσιμος
    assert full == "ready"

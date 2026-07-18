"""Tests για διαγραφή πελατών και εκκαθάριση ληφθέντων.

Καταστροφικές πράξεις — αξίζουν κάλυψη ακριβώς επειδή δεν αναιρούνται.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from timologio import coverage
from timologio.coverage import Range
from timologio.crypto import Crypto
from timologio.db import init_db
from timologio.models import Client, Direction, Document
from timologio.repo import (
    delete_clients,
    list_clients,
    upsert_client,
    upsert_document,
    wipe_documents,
)

A, B = "123456783", "555555559"


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    conn = init_db(tmp_path / "t.db")
    crypto = Crypto(tmp_path / ".enckey")
    for vat in (A, B):
        cid = upsert_client(
            conn, Client(vat=vat, label=f"Πελάτης {vat}", mydata_user="u",
                         mydata_key="k" * 32), crypto,
        )
        for mark in ("1", "2"):
            upsert_document(conn, cid, Document(
                mark=f"{vat}-{mark}", invoice_type="1.1", issuer_vat="044004008",
                counter_vat=vat, issue_date="2026-07-01",
                direction=Direction.INCOMING))
        coverage.record(conn, cid, Direction.INCOMING, "01/01/2026", "31/07/2026")
        conn.execute(
            "UPDATE clients SET last_mark_incoming='400099' WHERE vat=?", (vat,)
        )
    conn.commit()
    return conn


def _docs(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]


# --------------------------------------------------------------------------
# Διαγραφή πελατών
# --------------------------------------------------------------------------

def test_delete_client_removes_only_that_one(conn: sqlite3.Connection) -> None:
    assert delete_clients(conn, [A]) == 1
    conn.commit()
    assert [r["vat"] for r in list_clients(conn)] == [B]


def test_delete_client_cascades_to_documents(conn: sqlite3.Connection) -> None:
    delete_clients(conn, [A])
    conn.commit()
    assert _docs(conn) == 2, "μένουν μόνο του δεύτερου πελάτη"
    rows = conn.execute("SELECT mark FROM documents").fetchall()
    assert all(r["mark"].startswith(B) for r in rows)


def test_delete_client_cascades_to_coverage(conn: sqlite3.Connection) -> None:
    delete_clients(conn, [A])
    conn.commit()
    left = conn.execute("SELECT COUNT(*) c FROM coverage").fetchone()["c"]
    assert left == 1


def test_delete_many(conn: sqlite3.Connection) -> None:
    assert delete_clients(conn, [A, B]) == 2
    conn.commit()
    assert list_clients(conn) == []
    assert _docs(conn) == 0


def test_delete_nothing_is_safe(conn: sqlite3.Connection) -> None:
    assert delete_clients(conn, []) == 0
    conn.commit()
    assert len(list_clients(conn)) == 2


# --------------------------------------------------------------------------
# Εκκαθάριση
# --------------------------------------------------------------------------

def test_wipe_keeps_clients_and_keys(conn: sqlite3.Connection, tmp_path: Path) -> None:
    from timologio.repo import get_client

    wipe_documents(conn, [A])
    conn.commit()
    crypto = Crypto(tmp_path / ".enckey")
    client = get_client(conn, A, crypto)
    assert client is not None
    assert client.mydata_key == "k" * 32, "το κλειδί δεν πρέπει να χαθεί"
    assert client.status == "ready"


def test_wipe_removes_documents_of_one_client(conn: sqlite3.Connection) -> None:
    assert wipe_documents(conn, [A]) == 2
    conn.commit()
    assert _docs(conn) == 2
    rows = conn.execute("SELECT mark FROM documents").fetchall()
    assert all(r["mark"].startswith(B) for r in rows)


def test_wipe_all(conn: sqlite3.Connection) -> None:
    assert wipe_documents(conn) == 4
    conn.commit()
    assert _docs(conn) == 0
    assert len(list_clients(conn)) == 2, "οι πελάτες μένουν"


def test_wipe_resets_cursor_and_coverage(conn: sqlite3.Connection) -> None:
    """Χωρίς μηδενισμό, η επόμενη λήψη θα νόμιζε ότι τα έχει ήδη κατεβάσει."""
    wipe_documents(conn, [A])
    conn.commit()
    row = conn.execute(
        "SELECT last_mark_incoming, last_mark_outgoing FROM clients WHERE vat=?", (A,)
    ).fetchone()
    assert row["last_mark_incoming"] == "0"
    assert row["last_mark_outgoing"] == "0"

    cid = conn.execute("SELECT id FROM clients WHERE vat=?", (A,)).fetchone()["id"]
    assert coverage.fetch(conn, cid) == []
    assert not coverage.can_use_cursor(
        conn, cid, Direction.INCOMING, "01/01/2026", "31/07/2026"
    )


def test_wipe_one_leaves_other_cursor_alone(conn: sqlite3.Connection) -> None:
    wipe_documents(conn, [A])
    conn.commit()
    row = conn.execute(
        "SELECT last_mark_incoming FROM clients WHERE vat=?", (B,)
    ).fetchone()
    assert row["last_mark_incoming"] == "400099"
    cid = conn.execute("SELECT id FROM clients WHERE vat=?", (B,)).fetchone()["id"]
    assert coverage.fetch(conn, cid) == [Range("2026-01-01", "2026-07-31")]

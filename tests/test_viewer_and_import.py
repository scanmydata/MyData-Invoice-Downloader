"""Tests για τις διορθώσεις v0.2.5:

* το κλειδί myDATA που μπαίνει κατά λάθος στη στήλη «Συνθηματικό myData»
  (εξαγωγές taxsystem) εντοπίζεται πλέον ως εφεδρεία·
* τα παραστατικά που ο πάροχος δείχνει μόνο online δεν μετριούνται ως σφάλμα
  (κατάσταση viewer_only) και οι παλιές εγγραφές επαναταξινομούνται·
* το UpdateInfo κουβαλά τις σημειώσεις έκδοσης.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from timologio.db import init_db
from timologio.excel.aliases import (
    is_secondary_key_header,
    looks_like_key,
)
from timologio.excel.format_b import parse
from timologio.excel.reader import Sheet

KEY = "e5cbc62a2c4340a5e5a5fae584ca7939"  # 32-hex, μορφή κλειδιού myDATA


# --- ανίχνευση κλειδιού σε λάθος στήλη ------------------------------------


def test_looks_like_key_only_accepts_32_hex():
    assert looks_like_key(KEY)
    assert looks_like_key("A" * 32)  # case-insensitive hex
    assert not looks_like_key("συνθηματικό123")   # web password
    assert not looks_like_key(KEY[:-1])           # 31 χαρακτήρες
    assert not looks_like_key("g" * 32)           # όχι hex
    assert not looks_like_key("")


def test_secondary_key_header_recognised():
    assert is_secondary_key_header("Συνθηματικό myData")
    assert is_secondary_key_header("συνθηματικο mydata")
    assert not is_secondary_key_header("Api myData")
    assert not is_secondary_key_header("Επωνυμία")


def _sheet(rows: list[dict[str, str]]) -> list[Sheet]:
    s = Sheet(name="Φύλλο1")
    s.rows = rows
    return [s]


_HEADER = {
    "B": "Α.Φ.Μ.",
    "C": "Επωνυμία",
    "D": "Όνομα χρήστη myData",
    "E": "Api myData",
    "F": "Συνθηματικό myData",
}


def test_key_in_password_column_is_promoted_when_api_column_empty():
    sheets = _sheet([
        _HEADER,
        {"B": "090000045", "C": "ΤΕΣΤ Α", "D": "u1", "E": "", "F": KEY},
    ])
    clients = parse(sheets)
    assert len(clients) == 1
    assert clients[0].mydata_key == KEY


def test_api_column_wins_over_password_column():
    other = "abcdef0123456789abcdef0123456789"
    sheets = _sheet([
        _HEADER,
        {"B": "090000045", "C": "ΤΕΣΤ Β", "D": "u1", "E": other, "F": KEY},
    ])
    clients = parse(sheets)
    assert clients[0].mydata_key == other  # η κανονική στήλη είναι αυθεντική


def test_non_key_password_is_never_promoted():
    sheets = _sheet([
        _HEADER,
        {"B": "090000045", "C": "ΤΕΣΤ Γ", "D": "u1", "E": "", "F": "μυστικό2024"},
    ])
    clients = parse(sheets)
    assert clients[0].mydata_key == ""  # συνθηματικό web, όχι κλειδί


# --- viewer_only: κατάσταση & επαναταξινόμηση -----------------------------


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return init_db(tmp_path / "t.db")


def _add_doc(conn, mark, status, error=""):
    conn.execute(
        "INSERT INTO clients(vat, status) VALUES('090000045','ready')"
        if not conn.execute("SELECT 1 FROM clients").fetchone() else "SELECT 1",
    )
    cid = conn.execute("SELECT id FROM clients LIMIT 1").fetchone()[0]
    conn.execute(
        """INSERT INTO documents(client_id, mark, status, error_text,
                                 downloading_invoice_url)
           VALUES(?,?,?,?,?)""",
        (cid, mark, status, error, "https://provider.example/view/x"),
    )
    conn.commit()
    return cid


def test_mark_viewer_only_sets_status_and_clears_error(conn):
    from timologio import repo

    cid = _add_doc(conn, "M1", "failed_permanent", "κάποιο σφάλμα")
    repo.mark_viewer_only(conn, cid, "M1")
    row = conn.execute(
        "SELECT status, error_text FROM documents WHERE mark='M1'"
    ).fetchone()
    assert row["status"] == "viewer_only"
    assert row["error_text"] == ""


def test_migration_reclassifies_page_errors_as_viewer_only(tmp_path):
    """Οι παλιές εγγραφές «Ο πάροχος επέστρεψε σελίδα, όχι PDF» γίνονται
    viewer_only στο άνοιγμα της βάσης — δεν είναι σφάλματα."""
    db = tmp_path / "old.db"
    conn = init_db(db)
    _add_doc(conn, "M_page", "failed_permanent",
             "Ο πάροχος επέστρεψε σελίδα, όχι PDF: content-type=text/html")
    _add_doc(conn, "M_real", "failed_permanent", "HTTP 500 από τον πάροχο")
    conn.commit()
    conn.close()

    # Νέο άνοιγμα -> τρέχει το _migrate.
    conn = init_db(db)
    statuses = {
        r["mark"]: r["status"]
        for r in conn.execute("SELECT mark, status FROM documents")
    }
    assert statuses["M_page"] == "viewer_only"
    assert statuses["M_real"] == "failed_permanent"  # πραγματικό σφάλμα μένει


# --- σημειώσεις έκδοσης ----------------------------------------------------


def test_update_info_carries_notes():
    from timologio.updates import UpdateInfo

    assert UpdateInfo("0.1", "0.2", "u").notes == ""
    info = UpdateInfo("0.1", "0.2", "u", notes="## Τι νέο\n- κάτι")
    assert "Τι νέο" in info.notes

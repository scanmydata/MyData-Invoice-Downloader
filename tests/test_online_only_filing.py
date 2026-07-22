"""Test: αρχειοθέτηση PDF που κατέβασε ο χρήστης για «μόνο online» παραστατικό.

Καμία επικοινωνία με πάροχο και καμία παράκαμψη ελέγχου — απλώς παίρνουμε bytes
που ο χρήστης ήδη αποθήκευσε και τα βάζουμε στο σωστό όνομα/φάκελο.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from timologio.config import Settings
from timologio.crypto import Crypto
from timologio.db import init_db
from timologio.models import Client, Direction, Document
from timologio.repo import mark_viewer_only, upsert_client, upsert_document, viewer_only_documents
from timologio.sync import save_online_only_pdf

CLIENT_VAT = "123456783"


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    conn = init_db(tmp_path / "t.db")
    crypto = Crypto(tmp_path / ".enckey")
    cid = upsert_client(
        conn, Client(vat=CLIENT_VAT, label="ΔΕΙΓΜΑ ΕΜΠΟΡΙΚΗ ΑΕ",
                     mydata_user="u", mydata_key="k" * 32), crypto,
    )
    upsert_document(
        conn, cid,
        Document(mark="400014401148454", invoice_type="1.1",
                 issuer_vat="987654324", issuer_name="ΧΡΩΜΑΤΑ ΠΑΡΑΔΕΙΓΜΑ ΟΕ",
                 counter_vat=CLIENT_VAT, series="ΤΔΑ", aa="1",
                 issue_date="2026-01-02", total_value=40.29,
                 direction=Direction.INCOMING,
                 downloading_invoice_url="https://epsilondigital-3rd.epsilonnet.gr/fd/abc:97",
                 provider_host="epsilondigital-3rd.epsilonnet.gr"),
    )
    mark_viewer_only(conn, cid, "400014401148454")
    conn.commit()
    return conn


def test_save_online_only_pdf_files_and_marks_downloaded(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    row = viewer_only_documents(conn)[0]

    payload = b"%PDF-1.4 " + b"x" * 500
    path, size = save_online_only_pdf(conn, settings, row, payload)

    # Αρχειοθετήθηκε με το κανονικό σχήμα ονομάτων, στον φάκελο του πελάτη.
    assert path.exists()
    assert path.read_bytes() == payload
    assert size == len(payload)
    assert path.name == "ΧΡΩΜΑΤΑ ΠΑΡΑΔΕΙΓΜΑ ΟΕ_987654324_2026-01-02_ΤΔΑ_1_40,29.pdf"
    assert path.is_relative_to(settings.storage_root)
    # Ο φάκελος του πελάτη είναι «<ΑΦΜ> <επωνυμία>» / έτος / μήνας.
    assert path.parent.parent.parent.name.startswith(CLIENT_VAT)
    assert (path.parent.parent.name, path.parent.name) == ("2026", "01")

    # Σημειώθηκε ως «Ελήφθη» και δεν εμφανίζεται πια ως μόνο-online.
    status = conn.execute(
        "SELECT status, local_path FROM documents WHERE mark=?",
        ("400014401148454",),
    ).fetchone()
    assert status["status"] == "downloaded"
    assert status["local_path"]
    assert viewer_only_documents(conn) == []


def test_save_online_only_pdf_rejects_non_pdf(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    row = viewer_only_documents(conn)[0]
    with pytest.raises(ValueError):
        save_online_only_pdf(conn, settings, row, b"<html>not a pdf</html>")

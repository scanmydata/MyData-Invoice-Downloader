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


def test_download_viewer_only_parallel_saves_all(
    conn: sqlite3.Connection, tmp_path: Path, monkeypatch
) -> None:
    """Η παράλληλη λήψη «μόνο online» αρχειοθετεί όλα τα PDF (mock renderer)."""
    from pathlib import Path as _P

    import timologio.download.headless as headless
    from timologio import sync

    # Δεύτερο viewer_only doc ώστε να δουλέψει ο παραλληλισμός.
    cid = conn.execute("SELECT id FROM clients WHERE vat=?", (CLIENT_VAT,)).fetchone()["id"]
    upsert_document(
        conn, cid,
        Document(mark="400014401148455", invoice_type="1.1", issuer_vat="987654324",
                 issuer_name="ΑΛΛΟΣ ΠΡΟΜΗΘΕΥΤΗΣ", counter_vat=CLIENT_VAT, series="ΤΔΑ",
                 aa="2", issue_date="2026-01-03", total_value=50.0,
                 direction=Direction.INCOMING,
                 downloading_invoice_url="https://x.gr/fd/two:1",
                 provider_host="x.gr"),
    )
    mark_viewer_only(conn, cid, "400014401148455")
    conn.commit()

    class FakeRenderer:
        def __init__(self, *a, **k): pass
        def render_pdf(self, url, **k): return b"%PDF-1.4 " + b"z" * 300
        def close(self): pass

    monkeypatch.setattr(headless, "find_browser", lambda: _P("edge.exe"))
    monkeypatch.setattr(headless, "HeadlessRenderer", FakeRenderer)

    settings = Settings(data_dir=tmp_path / "data")
    saved, skipped, failed = sync.download_viewer_only(conn, settings)
    assert (saved, skipped, failed) == (2, 0, 0)
    assert viewer_only_documents(conn) == []
    downloaded = conn.execute(
        "SELECT COUNT(*) c FROM documents WHERE status='downloaded'"
    ).fetchone()["c"]
    assert downloaded == 2


def test_download_viewer_only_headed_fallback(
    conn: sqlite3.Connection, tmp_path: Path, monkeypatch
) -> None:
    """Όσα μένουν κενά στο headless πέρασμα, τα πιάνει το ορατό headed πέρασμα."""
    from pathlib import Path as _P

    import timologio.download.headless as headless
    from timologio import sync

    class FakeRenderer:
        # Headless -> κενή σελίδα (None)· ορατό headed -> επιτυχία.
        def __init__(self, *a, headed=False, **k):
            self._headed = headed
        def render_pdf(self, url, **k):
            return (b"%PDF-1.4 " + b"z" * 300) if self._headed else None
        def close(self):
            pass

    monkeypatch.setattr(headless, "find_browser", lambda: _P("edge.exe"))
    monkeypatch.setattr(headless, "HeadlessRenderer", FakeRenderer)

    settings = Settings(data_dir=tmp_path / "data")
    # Πέρασμα 1 (headless) δεν πιάνει τίποτα· πέρασμα 2 (headed) τα σώζει.
    saved, skipped, failed = sync.download_viewer_only(conn, settings)
    assert (saved, skipped, failed) == (1, 0, 0)

    # Χωρίς headed fallback, μένει «μόνο online».
    conn.execute("UPDATE documents SET status='viewer_only', local_path='' WHERE mark=?",
                 ("400014401148454",))
    conn.commit()
    saved2, skipped2, failed2 = sync.download_viewer_only(
        conn, settings, headed_fallback=False
    )
    assert (saved2, skipped2, failed2) == (0, 1, 0)

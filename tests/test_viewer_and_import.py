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


# --- headless λήψη «μόνο online» -------------------------------------------


def test_viewer_only_documents_query(conn):
    cid = _add_doc(conn, "M_view", "viewer_only")
    # ίδιος πελάτης: ένα downloaded (αγνοείται) κι ένα viewer_only χωρίς url.
    conn.execute(
        "INSERT INTO documents(client_id,mark,status,downloading_invoice_url) "
        "VALUES(?,?,?,?)", (cid, "M_dl", "downloaded", "https://x/y"))
    conn.execute(
        "INSERT INTO documents(client_id,mark,status,downloading_invoice_url) "
        "VALUES(?,?,?,?)", (cid, "M_nourl", "viewer_only", ""))
    conn.commit()
    from timologio import repo

    rows = repo.viewer_only_documents(conn)
    assert [r["mark"] for r in rows] == ["M_view"]
    assert rows[0]["client_vat"] == "090000045"
    assert rows[0]["client_label"] == ""  # όπως μπήκε στο _add_doc


def test_find_browser_and_available_never_crash():
    from timologio.download import headless

    # Δεν βεβαιώνουμε την ύπαρξη browser (μπορεί να λείπει σε CI) — μόνο ότι δεν
    # σκάει και επιστρέφει τον σωστό τύπο.
    b = headless.find_browser()
    assert b is None or b.exists()
    assert isinstance(headless.available(), bool)


def test_download_viewer_only_saves_renderable_keeps_rest(conn, tmp_path, monkeypatch):
    """Ο renderer επιστρέφει PDF για τη μία σελίδα και None για την άλλη:
    η πρώτη γίνεται downloaded με αρχείο, η δεύτερη μένει viewer_only."""
    from timologio import sync
    from timologio.config import Settings
    from timologio.download import headless
    from timologio.download.provider import NotAPdf

    # Το πέρασμα 0 (άμεση λήψη) δεν πρέπει να χτυπά δίκτυο στο test: το κάνουμε
    # να «βλέπει» τα πάντα ως μόνο-online (NotAPdf) ώστε να πέσουν στον renderer.
    def _no_direct(self, url):
        raise NotAPdf("html")
    monkeypatch.setattr(
        "timologio.download.provider.ProviderDownloader.fetch_pdf", _no_direct
    )

    cid = _add_doc(conn, "M_good", "viewer_only")
    # συμπληρώνουμε url/στοιχεία στη γραμμή που έφτιαξε το _add_doc
    conn.execute(
        "UPDATE documents SET downloading_invoice_url='https://prov/good',"
        "issuer_vat='111',series='A',aa='1',issue_date='2026-01-01' WHERE mark='M_good'")
    conn.execute(
        "INSERT INTO documents(client_id,mark,status,downloading_invoice_url,"
        "issuer_vat,series,aa,issue_date) VALUES(?,?,?,?,?,?,?,?)",
        (cid, "M_bad", "viewer_only", "https://prov/bad", "222", "A", "2", "2026-01-02"),
    )
    conn.commit()

    class FakeRenderer:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def render_pdf(self, url, **k):
            return b"%PDF-1.4\nfake invoice\n%%EOF" if url.endswith("good") else None

    monkeypatch.setattr(headless, "HeadlessRenderer", FakeRenderer)

    settings = Settings(data_dir=tmp_path)
    saved, skipped, failed = sync.download_viewer_only(conn, settings)
    assert (saved, skipped, failed) == (1, 1, 0)

    rows = {r["mark"]: r for r in conn.execute(
        "SELECT mark,status,local_path,file_bytes FROM documents")}
    assert rows["M_good"]["status"] == "downloaded"
    assert rows["M_good"]["file_bytes"] > 0
    assert (settings.storage_root / rows["M_good"]["local_path"]).exists()
    assert rows["M_bad"]["status"] == "viewer_only"
    assert rows["M_bad"]["local_path"] == ""


def test_direct_fetch_recovers_provider_with_pdf(conn, tmp_path, monkeypatch):
    """Πέρασμα 0: πάροχος με άμεσο PDF (π.χ. Megasoft) κατεβαίνει ΧΩΡΙΣ browser."""
    from timologio import sync
    from timologio.config import Settings
    from timologio.download.provider import NotAPdf, PdfResult

    cid = _add_doc(conn, "M_direct", "viewer_only")
    conn.execute(
        "UPDATE documents SET downloading_invoice_url='https://invoicelink.megasoft.gr"
        "/invoiceinspect/qr?QrCode=ABC/',issuer_vat='111',series='A',aa='1',"
        "issue_date='2026-01-01' WHERE mark='M_direct'")
    conn.execute(
        "INSERT INTO documents(client_id,mark,status,downloading_invoice_url,"
        "issuer_vat,series,aa,issue_date) VALUES(?,?,?,?,?,?,?,?)",
        (cid, "M_html", "viewer_only", "https://prov/html", "222", "A", "2", "2026-01-02"))
    conn.commit()

    def fake_fetch(self, url):
        if "megasoft" in url:
            return PdfResult(payload=b"%PDF-1.4\nmega\n%%EOF", url=url)
        raise NotAPdf("html")
    monkeypatch.setattr(
        "timologio.download.provider.ProviderDownloader.fetch_pdf", fake_fetch)

    settings = Settings(data_dir=tmp_path)
    saved, remaining = sync._direct_fetch_batch(
        conn, settings, sync.repo.viewer_only_documents(conn),
        progress=lambda m: None, should_cancel=None)
    assert saved == 1
    assert [r["mark"] for r in remaining] == ["M_html"]
    got = {r["mark"]: r["status"] for r in conn.execute("SELECT mark,status FROM documents")}
    assert got["M_direct"] == "downloaded"
    assert got["M_html"] == "viewer_only"

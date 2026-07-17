"""Tests για φακέλους πελατών, εξαγωγή ZIP και έξυπνα φίλτρα."""

from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

import pytest

from timologio.crypto import Crypto
from timologio.db import init_db
from timologio.download.storage import client_folder, find_client_folder, target_path
from timologio.models import Client, Direction, Document
from timologio.reports import (
    count_without_pdf,
    documents_for,
    export_zip,
    invoice_types_of,
    suppliers_of,
)
from timologio.repo import upsert_client, upsert_document

CLIENT_VAT = "802576637"
CLIENT_LABEL = "ΤΟ ΒΑΨΙΜΟ Ε Ε"


# --------------------------------------------------------------------------
# Φάκελος πελάτη: ΑΦΜ + επωνυμία
# --------------------------------------------------------------------------

def test_client_folder_has_vat_and_label(tmp_path: Path) -> None:
    folder = client_folder(tmp_path, CLIENT_VAT, CLIENT_LABEL)
    assert folder.name == "802576637 ΤΟ ΒΑΨΙΜΟ Ε Ε"


def test_client_folder_without_label_is_just_vat(tmp_path: Path) -> None:
    assert client_folder(tmp_path, CLIENT_VAT, "").name == CLIENT_VAT


def test_client_folder_sanitises_label(tmp_path: Path) -> None:
    folder = client_folder(tmp_path, CLIENT_VAT, 'Α/Β "Γ" <Δ>')
    assert "/" not in folder.name and '"' not in folder.name
    assert folder.name.startswith(CLIENT_VAT)


def test_client_folder_caps_very_long_label(tmp_path: Path) -> None:
    long = "ΑΝΩΝΥΜΗ ΕΜΠΟΡΙΚΗ ΚΑΙ ΒΙΟΜΗΧΑΝΙΚΗ ΕΤΑΙΡΕΙΑ ΗΛΕΚΤΡΟΝΙΚΩΝ ΕΙΔΩΝ ΚΑΙ ΛΟΙΠΩΝ"
    folder = client_folder(tmp_path, CLIENT_VAT, long)
    assert len(folder.name) < 60


def test_find_client_folder_reuses_existing_despite_renamed_label(tmp_path: Path) -> None:
    """Η επωνυμία αλλάζει (VIES, νέο import). Τα αρχεία δεν πρέπει να
    σκορπιστούν σε δεύτερο φάκελο για τον ίδιο πελάτη."""
    old = tmp_path / "802576637 ΠΑΛΙΑ ΕΠΩΝΥΜΙΑ"
    old.mkdir(parents=True)
    assert find_client_folder(tmp_path, CLIENT_VAT, "ΝΕΑ ΕΠΩΝΥΜΙΑ") == old


def test_find_client_folder_matches_bare_vat_folder(tmp_path: Path) -> None:
    old = tmp_path / CLIENT_VAT
    old.mkdir(parents=True)
    assert find_client_folder(tmp_path, CLIENT_VAT, CLIENT_LABEL) == old


def test_find_client_folder_is_not_fooled_by_similar_vat(tmp_path: Path) -> None:
    (tmp_path / "8025766370 ΑΛΛΟΣ").mkdir(parents=True)
    found = find_client_folder(tmp_path, CLIENT_VAT, CLIENT_LABEL)
    assert found.name == "802576637 ΤΟ ΒΑΨΙΜΟ Ε Ε"


def test_target_path_lives_under_named_client_folder(tmp_path: Path) -> None:
    doc = Document(mark="1", invoice_type="1.1", issuer_vat="800916954",
                   issuer_name="ΑΦΟΙ ΛΑΓΟΥ", counter_vat=CLIENT_VAT,
                   series="ΤΔΑ", aa="1", issue_date="2026-01-02", total_value=40.29)
    path = target_path(tmp_path, CLIENT_VAT, doc, client_label=CLIENT_LABEL)
    assert path.parts[-4] == "802576637 ΤΟ ΒΑΨΙΜΟ Ε Ε"
    assert path.parts[-3] == "2026" and path.parts[-2] == "01"


# --------------------------------------------------------------------------
# ZIP
# --------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    conn = init_db(tmp_path / "t.db")
    crypto = Crypto(tmp_path / ".enckey")
    cid = upsert_client(
        conn,
        Client(vat=CLIENT_VAT, label=CLIENT_LABEL, mydata_user="u", mydata_key="k" * 32),
        crypto,
    )
    upsert_document(conn, cid, Document(
        mark="1", invoice_type="1.1", issuer_vat="800916954",
        issuer_name="ΑΦΟΙ ΛΑΓΟΥ", counter_vat=CLIENT_VAT, issue_date="2026-01-02",
        net_value=10, vat_amount=2.4, total_value=12.4,
        downloading_invoice_url="https://x.gr/a", direction=Direction.INCOMING))
    upsert_document(conn, cid, Document(
        mark="2", invoice_type="2.1", issuer_vat=CLIENT_VAT,
        counter_vat="094439854", counter_name="ΤΡΑΚΑΔΑΣ", issue_date="2026-07-05",
        net_value=100, vat_amount=24, total_value=124,
        downloading_invoice_url="https://x.gr/b", direction=Direction.OUTGOING))
    upsert_document(conn, cid, Document(
        mark="3", invoice_type="1.1", issuer_vat="800916954",
        issuer_name="ΑΦΟΙ ΛΑΓΟΥ", counter_vat=CLIENT_VAT, issue_date="2026-03-10",
        net_value=5, vat_amount=1.2, total_value=6.2, direction=Direction.INCOMING))
    conn.commit()
    return conn


def _make_files(conn: sqlite3.Connection, root: Path) -> None:
    for mark, rel in (
        ("1", "802576637 ΤΟ ΒΑΨΙΜΟ Ε Ε/2026/01/ΑΦΟΙ ΛΑΓΟΥ_800916954_2026-01-02_ΤΔΑ_1_12,40.pdf"),
        ("2", "802576637 ΤΟ ΒΑΨΙΜΟ Ε Ε/2026/07/ΤΡΑΚΑΔΑΣ_094439854_2026-07-05_Α_2_124,00.pdf"),
    ):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4 test")
        conn.execute("UPDATE documents SET local_path=?, status='downloaded' WHERE mark=?",
                     (rel, mark))
    conn.commit()


def test_export_zip_packs_files(conn: sqlite3.Connection, tmp_path: Path) -> None:
    root = tmp_path / "data"
    _make_files(conn, root)
    rows = documents_for(conn, CLIENT_VAT, "all")
    target = tmp_path / "out.zip"

    added, missing = export_zip(rows, root, target)
    assert added == 2
    assert missing == 1, "το τρίτο δεν έχει αρχείο"
    assert target.exists()


def test_zip_is_flat(conn: sqlite3.Connection, tmp_path: Path) -> None:
    """Τα αρχεία μπαίνουν χύμα, χωρίς υποφακέλους.

    Το όνομα κάθε αρχείου έχει ήδη προμηθευτή, ημερομηνία και αξία· μια δομή
    έτος/μήνα απλώς θα πρόσθετε κλικ στον παραλήπτη.
    """
    root = tmp_path / "data"
    _make_files(conn, root)
    target = tmp_path / "out.zip"
    export_zip(documents_for(conn, CLIENT_VAT, "all"), root, target)

    with zipfile.ZipFile(target) as zf:
        names = zf.namelist()
    assert names, "το ZIP δεν πρέπει να είναι άδειο"
    assert all("/" not in n for n in names), f"βρέθηκαν υποφάκελοι: {names}"
    assert any(n.startswith("ΑΦΟΙ ΛΑΓΟΥ") for n in names)


def test_zip_disambiguates_same_name(conn: sqlite3.Connection, tmp_path: Path) -> None:
    """Δύο αρχεία με ίδιο όνομα σε διαφορετικούς μήνες δεν πρέπει να
    αλληλοσβηστούν τώρα που το ZIP είναι επίπεδο."""
    root = tmp_path / "data"
    for mark, month in (("1", "01"), ("2", "07")):
        rel = f"802576637 ΤΟ ΒΑΨΙΜΟ Ε Ε/2026/{month}/ΙΔΙΟ ΟΝΟΜΑ.pdf"
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4 test")
        conn.execute("UPDATE documents SET local_path=? WHERE mark=?", (rel, mark))
    conn.commit()

    target = tmp_path / "out.zip"
    added, _ = export_zip(documents_for(conn, CLIENT_VAT, "all"), root, target)
    assert added == 2
    with zipfile.ZipFile(target) as zf:
        names = sorted(zf.namelist())
    assert names == ["ΙΔΙΟ ΟΝΟΜΑ (2).pdf", "ΙΔΙΟ ΟΝΟΜΑ.pdf"]


def test_zip_content_is_intact(conn: sqlite3.Connection, tmp_path: Path) -> None:
    root = tmp_path / "data"
    _make_files(conn, root)
    target = tmp_path / "out.zip"
    export_zip(documents_for(conn, CLIENT_VAT, "all"), root, target)
    with zipfile.ZipFile(target) as zf:
        assert zf.read(zf.namelist()[0]).startswith(b"%PDF")


def test_zip_of_selection_only(conn: sqlite3.Connection, tmp_path: Path) -> None:
    root = tmp_path / "data"
    _make_files(conn, root)
    picked = [r for r in documents_for(conn, CLIENT_VAT, "all") if r["mark"] == "2"]
    target = tmp_path / "one.zip"
    added, _ = export_zip(picked, root, target)
    assert added == 1


# --------------------------------------------------------------------------
# Παραστατικά χωρίς PDF: μπαίνουν με το XML ή μένουν έξω
# --------------------------------------------------------------------------

def _make_xml_only(conn: sqlite3.Connection, root: Path) -> None:
    """Το «3» δεν πέρασε από πάροχο: έχει μόνο το XML της ΑΑΔΕ."""
    rel = "802576637 ΤΟ ΒΑΨΙΜΟ Ε Ε/2026/03/ΑΦΟΙ ΛΑΓΟΥ_800916954_2026-03-10_Α_3_6,20.xml"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"<invoice/>")
    conn.execute("UPDATE documents SET xml_path=? WHERE mark='3'", (rel,))
    conn.commit()


def test_count_without_pdf_sees_only_xml_rows(conn: sqlite3.Connection,
                                              tmp_path: Path) -> None:
    root = tmp_path / "data"
    _make_files(conn, root)
    _make_xml_only(conn, root)
    rows = documents_for(conn, CLIENT_VAT, "all")
    assert count_without_pdf(rows) == 1, "μόνο το «3» έχει XML χωρίς PDF"


def test_zip_includes_xml_when_asked(conn: sqlite3.Connection, tmp_path: Path) -> None:
    root = tmp_path / "data"
    _make_files(conn, root)
    _make_xml_only(conn, root)
    target = tmp_path / "with.zip"

    added, missing = export_zip(documents_for(conn, CLIENT_VAT, "all"), root, target,
                                include_without_pdf=True)
    assert (added, missing) == (3, 0)
    with zipfile.ZipFile(target) as zf:
        assert any(n.endswith(".xml") for n in zf.namelist())


def test_zip_leaves_out_xml_when_refused(conn: sqlite3.Connection,
                                         tmp_path: Path) -> None:
    """Ο χρήστης που στέλνει το ZIP σε πελάτη δεν θέλει να εξηγεί τι είναι XML."""
    root = tmp_path / "data"
    _make_files(conn, root)
    _make_xml_only(conn, root)
    target = tmp_path / "pdf-only.zip"

    added, missing = export_zip(documents_for(conn, CLIENT_VAT, "all"), root, target,
                                include_without_pdf=False)
    assert added == 2
    assert missing == 1, "το παραστατικό χωρίς PDF μετριέται ως εκτός"
    with zipfile.ZipFile(target) as zf:
        assert all(n.endswith(".pdf") for n in zf.namelist())


# --------------------------------------------------------------------------
# Συνδυασμός φίλτρων
# --------------------------------------------------------------------------

def test_extra_filters_combine_with_and(conn: sqlite3.Connection) -> None:
    """Το αίτημα «έξοδα ΚΑΙ ελήφθησαν PDF» — δύο άξονες ταυτόχρονα."""
    conn.execute("UPDATE documents SET status='downloaded' WHERE mark='1'")
    conn.commit()
    rows = documents_for(conn, CLIENT_VAT, "expense", extra_filters=["downloaded"])
    assert [r["mark"] for r in rows] == ["1"], "το «3» είναι έξοδο αλλά δεν κατέβηκε"


def test_extra_filters_can_exclude_everything(conn: sqlite3.Connection) -> None:
    assert documents_for(conn, CLIENT_VAT, "income",
                         extra_filters=["downloaded"]) == []


def test_extra_filter_all_is_ignored(conn: sqlite3.Connection) -> None:
    """Ένας άξονας στο «Όλα» δεν πρέπει να στενεύει τίποτα."""
    plain = documents_for(conn, CLIENT_VAT, "expense")
    padded = documents_for(conn, CLIENT_VAT, "expense", extra_filters=["all", "all"])
    assert [r["mark"] for r in plain] == [r["mark"] for r in padded]


def test_three_axes_at_once(conn: sqlite3.Connection) -> None:
    conn.execute(
        "UPDATE documents SET status='downloaded', classification='unclassified'"
        " WHERE mark='1'"
    )
    conn.commit()
    rows = documents_for(conn, CLIENT_VAT, "expense",
                         extra_filters=["downloaded", "unclassified"])
    assert [r["mark"] for r in rows] == ["1"]


# --------------------------------------------------------------------------
# Έξυπνα φίλτρα
# --------------------------------------------------------------------------

def test_suppliers_list_uses_the_other_party(conn: sqlite3.Connection) -> None:
    found = dict((vat, name) for vat, name, _ in suppliers_of(conn, CLIENT_VAT))
    assert found["800916954"] == "ΑΦΟΙ ΛΑΓΟΥ"
    assert found["094439854"] == "ΤΡΑΚΑΔΑΣ", "στα έσοδα ο «άλλος» είναι ο λήπτης"
    assert CLIENT_VAT not in found, "ο ίδιος ο πελάτης δεν είναι προμηθευτής του εαυτού του"


def test_filter_by_supplier(conn: sqlite3.Connection) -> None:
    rows = documents_for(conn, CLIENT_VAT, "all", supplier_vat="800916954")
    assert len(rows) == 2
    assert {r["mark"] for r in rows} == {"1", "3"}


def test_filter_by_supplier_on_income_side(conn: sqlite3.Connection) -> None:
    rows = documents_for(conn, CLIENT_VAT, "all", supplier_vat="094439854")
    assert [r["mark"] for r in rows] == ["2"]


def test_filter_by_type(conn: sqlite3.Connection) -> None:
    assert len(documents_for(conn, CLIENT_VAT, "all", invoice_type="1.1")) == 2
    assert len(documents_for(conn, CLIENT_VAT, "all", invoice_type="2.1")) == 1


def test_invoice_types_list(conn: sqlite3.Connection) -> None:
    assert invoice_types_of(conn, CLIENT_VAT) == [("1.1", 2), ("2.1", 1)]


def test_filter_by_date_range(conn: sqlite3.Connection) -> None:
    rows = documents_for(conn, CLIENT_VAT, "all",
                         date_from="01/03/2026", date_to="31/12/2026")
    assert {r["mark"] for r in rows} == {"2", "3"}


def test_filter_by_date_accepts_iso(conn: sqlite3.Connection) -> None:
    rows = documents_for(conn, CLIENT_VAT, "all", date_from="2026-07-01")
    assert [r["mark"] for r in rows] == ["2"]


def test_filters_combine(conn: sqlite3.Connection) -> None:
    rows = documents_for(conn, CLIENT_VAT, "expense",
                         supplier_vat="800916954", invoice_type="1.1",
                         date_from="01/01/2026", date_to="31/01/2026")
    assert [r["mark"] for r in rows] == ["1"]

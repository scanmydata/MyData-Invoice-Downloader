"""Regression tests για το Excel import.

Τρέχουν πάνω στα πραγματικά αρχεία του γραφείου, οπότε γίνονται skip αν δεν
υπάρχουν (π.χ. σε CI). Τα μυστικά δεν εμφανίζονται ποτέ σε assertion message.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from timologio.crypto import Crypto
from timologio.db import init_db
from timologio.excel import ExcelFormat, build_preview
from timologio.excel.aliases import field_for
from timologio.excel.reader import read_workbook
from timologio.normalize import norm_afm, norm_header, valid_subscription_key
from timologio.repo import get_client, upsert_client

#: Τα δείγματα Excel περιέχουν πραγματικά στοιχεία πελατών, οπότε ΔΕΝ μπαίνουν
#: στο repo. Όποιος τα έχει, δείχνει τον φάκελό τους με το TIMOLOGIO_SAMPLE_DIR
#: και τα σχετικά tests τρέχουν· αλλιώς παρακάμπτονται σιωπηλά.
SAMPLES = Path(os.environ.get("TIMOLOGIO_SAMPLE_DIR", "")) if os.environ.get(
    "TIMOLOGIO_SAMPLE_DIR"
) else Path("__χωρίς_δείγματα__")
FORMAT_A = SAMPLES / "ΤΕΣΤ_ΚΩΔΙΚΟΙ.xlsx"
FORMAT_B = SAMPLES / "Κωδικοί_Υπόχρεων.xlsx"

pytestmark = pytest.mark.skipif(
    not FORMAT_A.exists() or not FORMAT_B.exists(),
    reason="τα δείγματα Excel δεν είναι διαθέσιμα (δείτε TIMOLOGIO_SAMPLE_DIR)",
)


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return init_db(tmp_path / "t.db")


@pytest.fixture
def crypto(tmp_path: Path) -> Crypto:
    return Crypto(tmp_path / ".enckey")


# --------------------------------------------------------------------------
# Normalizer — ο λόγος που δεν επαναχρησιμοποιούμε το παλιότερο εργαλείο
# --------------------------------------------------------------------------

def test_norm_header_deletes_dots_not_spaces() -> None:
    """«Α.Φ.Μ.» -> «αφμ». Το παλιότερο εργαλείο δίνει «α φ μ» και δεν ταιριάζει ποτέ."""
    assert norm_header("Α.Φ.Μ.") == "αφμ"
    assert norm_header("Ι.Κ.Α.") == "ικα"


def test_norm_header_folds_accents() -> None:
    assert norm_header("Επωνυμία/Επώνυμο") == "επωνυμια επωνυμο"
    assert norm_header("Όνομα χρήστη myData") == "ονομα χρηστη mydata"


def test_norm_header_no_collisions_on_real_headers() -> None:
    """Καμία από όλες τις πραγματικές επικεφαλίδες δεν συγκρούεται με άλλη."""
    sheets = read_workbook(FORMAT_B)
    headers = [v for v in sheets[0].rows[0].values() if v.strip()]
    normed = [norm_header(h) for h in headers]
    assert len(set(normed)) == len(normed), "δύο επικεφαλίδες κατέληξαν ίδιες"


# --------------------------------------------------------------------------
# Η παγίδα BI/BL
# --------------------------------------------------------------------------

def test_api_mydata_maps_to_key() -> None:
    assert field_for("Api myData") == "mydata_key"
    assert field_for("Όνομα χρήστη myData") == "mydata_user"
    assert field_for("Α.Φ.Μ.") == "afm"


def test_etimologio_columns_never_map_to_mydata() -> None:
    """Το «Subscription key e-timologio» είναι ΑΛΛΟ προϊόν.

    Με substring matching (ένα παλιότερο εργαλείο) το alias «subscription key» θα το
    άρπαζε και θα το έστελνε ως myDATA key -> 403 παντού.
    """
    assert field_for("Subscription key e-timologio") is None
    assert field_for("Όνομα χρήστη e-timologio") is None
    assert field_for("Συνθηματικό e-timologio") is None
    assert field_for("Συνθηματικό myData") is None  # web password, όχι API key


def test_bl_only_rows_get_empty_key_not_etimologio_value() -> None:
    """Το κρίσιμο regression.

    αρκετοί πελάτες έχουν κλειδί e-timologio (BL) αλλά ΟΧΙ κλειδί
    myDATA (BI). Πρέπει να καταλήγουν με κενό κλειδί — ποτέ με την τιμή του BL.
    """
    sheets = read_workbook(FORMAT_B)
    sheet = sheets[0]
    header = sheet.rows[0]
    col_bi = next(c for c, v in header.items() if v.strip() == "Api myData")
    col_bl = next(c for c, v in header.items() if v.strip() == "Subscription key e-timologio")

    bl_only: dict[str, str] = {}
    for row in sheet.rows[1:]:
        vat = norm_afm(row.get("B", ""))
        if vat and not row.get(col_bi, "").strip() and row.get(col_bl, "").strip():
            bl_only[vat] = row[col_bl].strip()

    assert len(bl_only) == 42, f"περίμενα 42 BL-only γραμμές, βρήκα {len(bl_only)}"

    preview = build_preview(FORMAT_B)
    imported = {r.client.vat: r.client for r in preview.rows}
    for vat, etimologio_key in bl_only.items():
        client = imported.get(vat)
        assert client is not None, f"χάθηκε ο πελάτης {vat}"
        assert client.mydata_key == "", f"ο {vat} πήρε κλειδί ενώ δεν έχει BI"
        assert client.mydata_key != etimologio_key, f"ΔΙΑΡΡΟΗ e-timologio key στον {vat}"


# --------------------------------------------------------------------------
# Ανίχνευση μορφής & πλήθη
# --------------------------------------------------------------------------

def test_format_a_detected_and_parsed() -> None:
    preview = build_preview(FORMAT_A)
    assert preview.fmt is ExcelFormat.AADE_BLOCK
    assert len(preview.rows) == 2, "το αρχείο έχει 2 μπλοκ (R7 και R14)"
    vats = {r.client.vat for r in preview.rows}
    assert vats == {"555555559", "123456783"}
    assert preview.ready == 2
    for row in preview.rows:
        assert valid_subscription_key(row.client.mydata_key)


def test_format_b_detected_with_expected_counts() -> None:
    preview = build_preview(FORMAT_B)
    assert preview.fmt is ExcelFormat.WIDE_TABLE
    assert len(preview.rows) == 153
    assert preview.ready == 58
    assert preview.missing_key == 95


def test_all_keys_are_32_hex() -> None:
    preview = build_preview(FORMAT_B)
    for row in preview.rows:
        if row.client.mydata_key:
            assert valid_subscription_key(row.client.mydata_key)


def test_sheet2_is_ignored() -> None:
    """Το «Sheet (2)» έχει 43 ΑΦΜ χωρίς στήλες myDATA.

    Αν το διαβάζαμε, θα περνούσε κενά credentials πάνω από καλά.
    """
    sheets = read_workbook(FORMAT_B)
    assert len(sheets) == 2, "το αρχείο έχει 2 φύλλα"
    preview = build_preview(FORMAT_B)
    # 153 = μόνο το πρώτο φύλλο· με τα δύο θα ήταν περισσότερα
    assert len(preview.rows) == 153


# --------------------------------------------------------------------------
# Upsert: μη-καταστροφικό
# --------------------------------------------------------------------------

def test_empty_import_never_clobbers_stored_key(
    conn: sqlite3.Connection, crypto: Crypto
) -> None:
    """Η άμυνα για το Sheet (2): κενή τιμή δεν σβήνει αποθηκευμένο κλειδί."""
    from timologio.models import Client

    upsert_client(
        conn,
        Client(vat="123456783", label="Αρχικό", mydata_user="U1", mydata_key="k" * 32),
        crypto,
    )
    upsert_client(conn, Client(vat="123456783", label="Νέα επωνυμία"), crypto)
    conn.commit()

    client = get_client(conn, "123456783", crypto)
    assert client is not None
    assert client.mydata_key == "k" * 32, "το κλειδί σβήστηκε από κενό import"
    assert client.mydata_user == "U1"
    assert client.label == "Νέα επωνυμία", "η επωνυμία έπρεπε να ενημερωθεί"
    assert client.status == "ready"


def test_reimport_is_idempotent(conn: sqlite3.Connection, crypto: Crypto) -> None:
    preview = build_preview(FORMAT_B, conn)
    for row in preview.rows:
        upsert_client(conn, row.client, crypto)
    conn.commit()
    first = [dict(r) for r in conn.execute("SELECT vat, status FROM clients ORDER BY vat")]

    for row in build_preview(FORMAT_B, conn).rows:
        upsert_client(conn, row.client, crypto)
    conn.commit()
    second = [dict(r) for r in conn.execute("SELECT vat, status FROM clients ORDER BY vat")]

    assert first == second
    assert len(first) == 153
    assert sum(1 for r in first if r["status"] == "ready") == 58


def test_key_is_encrypted_at_rest(conn: sqlite3.Connection, crypto: Crypto, tmp_path: Path) -> None:
    from timologio.models import Client

    secret = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
    upsert_client(conn, Client(vat="123456783", mydata_user="U", mydata_key=secret), crypto)
    conn.commit()
    stored = conn.execute(
        "SELECT mydata_key_enc FROM clients WHERE vat='123456783'"
    ).fetchone()[0]
    assert stored.startswith("enc:1:")
    assert secret not in stored
    assert crypto.dec(stored) == secret

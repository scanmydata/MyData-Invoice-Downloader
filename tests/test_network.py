"""Tests για δικτυακή λειτουργία (server/τερματικά) και VIES."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from timologio.db import init_db, is_network_path
from timologio.locking import LockBusy, SyncLock
from timologio.vies import clean_name, clean_vat

# --------------------------------------------------------------------------
# Ανίχνευση δικτυακής διαδρομής
#
# Το WAL απαιτεί shared memory που δεν υπάρχει πάνω από SMB. Αν αυτός ο έλεγχος
# σπάσει, μια βάση σε δικτυακό φάκελο θα ανοίξει σε WAL και θα φθαρεί.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    [
        r"\\SERVER\share\timologio.db",
        "//server/share/timologio.db",       # το pathlib το κανονικοποιεί
        r"\\192.168.1.10\logistiko\x.db",
    ],
)
def test_unc_paths_detected_as_network(path: str) -> None:
    assert is_network_path(Path(path))


@pytest.mark.parametrize(
    "path",
    [
        r"C:\Users\a\Documents\Παραστατικά myDATA\timologio.db",
        r"D:\data\timologio.db",
    ],
)
def test_local_paths_not_network(path: str) -> None:
    assert not is_network_path(Path(path))


def test_local_db_uses_wal(tmp_path: Path) -> None:
    conn = init_db(tmp_path / "t.db")
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Κλείδωμα λήψης μεταξύ υπολογιστών
# --------------------------------------------------------------------------

def test_second_lock_is_refused(tmp_path: Path) -> None:
    first = SyncLock(tmp_path)
    first.acquire()
    try:
        with pytest.raises(LockBusy) as exc:
            SyncLock(tmp_path).acquire()
        assert "Εκτελείται ήδη λήψη" in exc.value.message_el
        assert exc.value.holder
    finally:
        first.release()


def test_lock_is_reusable_after_release(tmp_path: Path) -> None:
    a = SyncLock(tmp_path)
    a.acquire()
    a.release()
    assert not (tmp_path / "sync.lock").exists()
    b = SyncLock(tmp_path)
    b.acquire()  # δεν πρέπει να σηκώσει
    b.release()


def test_lock_context_manager_releases_on_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        with SyncLock(tmp_path):
            raise RuntimeError("boom")
    assert not (tmp_path / "sync.lock").exists(), "το lock έμεινε μετά από σφάλμα"


def test_stale_lock_from_crash_is_broken(tmp_path: Path) -> None:
    """Ένα crash δεν πρέπει να κλειδώσει το γραφείο για πάντα.

    Σε πραγματικό crash το λειτουργικό κλείνει το handle και μένει μόνο το
    αρχείο — αυτό προσομοιώνουμε.
    """
    import os
    import time

    from timologio.locking import STALE_AFTER

    crashed = SyncLock(tmp_path)
    crashed.acquire()
    os.close(crashed._fd)  # η διεργασία «πέθανε»: το handle έφυγε, το αρχείο έμεινε
    crashed._fd = None
    old = time.time() - STALE_AFTER.total_seconds() - 60
    os.utime(tmp_path / "sync.lock", (old, old))

    fresh = SyncLock(tmp_path)
    fresh.acquire()  # πρέπει να σπάσει το ορφανό
    fresh.release()


def test_live_lock_is_not_broken_even_if_old(tmp_path: Path) -> None:
    """Μια λήψη που κρατάει ώρες δεν πρέπει να «σπάσει» από άλλο μηχάνημα.

    Στα Windows το ανοιχτό handle το αποδεικνύει: το αρχείο δεν διαγράφεται.
    """
    import os
    import time

    from timologio.locking import STALE_AFTER

    live = SyncLock(tmp_path)
    live.acquire()
    try:
        old = time.time() - STALE_AFTER.total_seconds() - 60
        os.utime(tmp_path / "sync.lock", (old, old))
        with pytest.raises(LockBusy):
            SyncLock(tmp_path).acquire()
    finally:
        live.release()


# --------------------------------------------------------------------------
# VIES
# --------------------------------------------------------------------------

def test_clean_name_keeps_first_of_multiple() -> None:
    """Το VIES επιστρέφει «JUMBO ΑΝΩΝΥΜΗ…||JUMBO» — κρατάμε την πρώτη."""
    assert clean_name("JUMBO ΑΝΩΝΥΜΗ ΕΜΠΟΡΙΚΗ ΕΤΑΙΡΕΙΑ||JUMBO") == (
        "JUMBO ΑΝΩΝΥΜΗ ΕΜΠΟΡΙΚΗ ΕΤΑΙΡΕΙΑ"
    )


def test_clean_name_rejects_placeholder() -> None:
    assert clean_name("---") is None
    assert clean_name("") is None
    assert clean_name(None) is None


def test_clean_name_collapses_whitespace() -> None:
    assert clean_name("  ΑΦΟΙ   ΛΑΓΟΥ\n ΟΕ ") == "ΑΦΟΙ ΛΑΓΟΥ ΟΕ"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("EL094222211", "094222211"),
        ("GR094222211", "094222211"),
        ("094222211", "094222211"),
        (" 094222211 ", "094222211"),
        ("123", None),
        ("", None),
    ],
)
def test_clean_vat(raw: str, expected: str | None) -> None:
    assert clean_vat(raw) == expected


# --------------------------------------------------------------------------
# Μητρώο επωνυμιών: ιεραρχία πηγών
# --------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return init_db(tmp_path / "t.db")


def _name(conn: sqlite3.Connection, vat: str) -> str:
    row = conn.execute("SELECT name FROM suppliers WHERE vat=?", (vat,)).fetchone()
    return row["name"] if row else ""


def test_vies_overrides_invoice_name(conn: sqlite3.Connection) -> None:
    """Το επίσημο μητρώο υπερισχύει του ονόματος που γράφει το παραστατικό."""
    from timologio.repo import upsert_supplier

    upsert_supplier(conn, "094173365", "JUMBO", "invoice")
    upsert_supplier(conn, "094173365", "JUMBO ΑΝΩΝΥΜΗ ΕΜΠΟΡΙΚΗ ΕΤΑΙΡΕΙΑ", "vies")
    assert _name(conn, "094173365") == "JUMBO ΑΝΩΝΥΜΗ ΕΜΠΟΡΙΚΗ ΕΤΑΙΡΕΙΑ"


def test_client_label_beats_vies(conn: sqlite3.Connection) -> None:
    """Η επωνυμία που έχει καταχωρήσει ο λογιστής υπερισχύει του VIES."""
    from timologio.repo import upsert_supplier

    upsert_supplier(conn, "802576637", "ΕΠΙΣΗΜΗ ΑΠΟ VIES", "vies")
    upsert_supplier(conn, "802576637", "ΤΟ ΒΑΨΙΜΟ Ε Ε", "client")
    assert _name(conn, "802576637") == "ΤΟ ΒΑΨΙΜΟ Ε Ε"


def test_vies_never_downgrades_client_label(conn: sqlite3.Connection) -> None:
    from timologio.repo import upsert_supplier

    upsert_supplier(conn, "802576637", "ΤΟ ΒΑΨΙΜΟ Ε Ε", "client")
    upsert_supplier(conn, "802576637", "ΕΠΙΣΗΜΗ ΑΠΟ VIES", "vies")
    assert _name(conn, "802576637") == "ΤΟ ΒΑΨΙΜΟ Ε Ε"


def test_vies_misses_are_not_retried(conn: sqlite3.Connection) -> None:
    """Χωρίς αυτό, κάθε sync θα ξαναρωτούσε τα ίδια άγνωστα ΑΦΜ."""
    from timologio.crypto import Crypto
    from timologio.models import Client, Direction, Document
    from timologio.repo import (
        record_vies_miss,
        upsert_client,
        upsert_document,
        vats_needing_name,
    )

    crypto = Crypto(tmp := Path(conn.execute("PRAGMA database_list").fetchone()[2]).parent / "k")
    cid = upsert_client(conn, Client(vat="802576637", mydata_user="u", mydata_key="k" * 32), crypto)
    upsert_document(conn, cid, Document(mark="1", issuer_vat="094173365",
                                        direction=Direction.INCOMING))
    conn.commit()

    assert "094173365" in vats_needing_name(conn, cid)
    record_vies_miss(conn, "094173365")
    conn.commit()
    assert "094173365" not in vats_needing_name(conn, cid)

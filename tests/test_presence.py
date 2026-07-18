"""Παρουσία υπολογιστών και έλεγχος σύνδεσης."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from timologio import presence
from timologio.db import init_db


@pytest.fixture
def conn(tmp_path):
    connection = init_db(tmp_path / "timologio.db")
    yield connection
    connection.close()


def _age(conn: sqlite3.Connection, peer_id: str, delta: timedelta) -> None:
    """Γερνάει τεχνητά έναν παλμό, για να ελεγχθεί το «εκτός»."""
    stamp = (datetime.now(timezone.utc) - delta).strftime(presence._TS)
    conn.execute("UPDATE peers SET last_seen = ? WHERE id = ?", (stamp, peer_id))
    conn.commit()


def test_heartbeat_creates_one_row_per_workstation(conn, tmp_path):
    for _ in range(3):
        assert presence.heartbeat(conn, role="server", version="0.1.0", data_dir=tmp_path)

    rows = conn.execute("SELECT COUNT(*) c FROM peers").fetchone()["c"]
    # Τρεις παλμοί από την ίδια θέση εργασίας δεν κάνουν τρεις εγγραφές: αλλιώς
    # κάθε επανεκκίνηση θα πρόσθετε νέα γραμμή στη λίστα συνδέσεων.
    assert rows == 1


def test_peer_is_online_right_after_heartbeat(conn, tmp_path):
    presence.heartbeat(conn, role="terminal", version="0.1.0", data_dir=tmp_path)
    peers = presence.list_peers(conn)
    assert len(peers) == 1
    assert peers[0].online
    assert peers[0].is_self
    assert peers[0].role == "terminal"


def test_peer_goes_offline_after_window(conn, tmp_path):
    presence.heartbeat(conn, role="server", version="0.1.0", data_dir=tmp_path)
    _age(conn, presence.this_id(), presence.ONLINE_WINDOW + timedelta(seconds=5))
    assert presence.list_peers(conn)[0].online is False


def test_one_missed_heartbeat_does_not_mark_offline(conn, tmp_path):
    """Κλειδωμένη βάση κατά τη λήψη χάνει παλμούς — δεν είναι αποσύνδεση."""
    presence.heartbeat(conn, role="server", version="0.1.0", data_dir=tmp_path)
    _age(conn, presence.this_id(), timedelta(seconds=presence.HEARTBEAT_SECONDS + 5))
    assert presence.list_peers(conn)[0].online is True


def test_forget_old_drops_only_ancient_rows(conn, tmp_path):
    presence.heartbeat(conn, role="server", version="0.1.0", data_dir=tmp_path)
    conn.execute(
        "INSERT INTO peers(id, host, username, role, version, pid, data_dir,"
        " first_seen, last_seen) VALUES('ΠΑΛΙΟΣ|χρήστης','ΠΑΛΙΟΣ','χρήστης',"
        " 'terminal','0.1.0',0,'', ?, ?)",
        ("2020-01-01 00:00:00", "2020-01-01 00:00:00"),
    )
    conn.commit()

    assert presence.forget_old(conn) == 1
    remaining = [p.host for p in presence.list_peers(conn)]
    assert remaining == [presence.host_name()]


def test_online_peers_sort_before_offline(conn, tmp_path):
    presence.heartbeat(conn, role="server", version="0.1.0", data_dir=tmp_path)
    conn.execute(
        "INSERT INTO peers(id, host, username, role, version, pid, data_dir,"
        " first_seen, last_seen) VALUES('ΑΛΛΟΣ|χρήστης','ΑΛΛΟΣ','χρήστης',"
        " 'terminal','0.1.0',0,'', ?, ?)",
        ("2024-01-01 00:00:00", "2024-01-01 00:00:00"),
    )
    conn.commit()

    peers = presence.list_peers(conn)
    assert peers[0].online and not peers[1].online


def test_heartbeat_survives_a_broken_connection(tmp_path):
    """Ο παλμός δεν επιτρέπεται ποτέ να ρίξει την εφαρμογή."""
    connection = init_db(tmp_path / "timologio.db")
    connection.close()
    assert presence.heartbeat(
        connection, role="server", version="0.1.0", data_dir=tmp_path
    ) is False


# --- έλεγχος σύνδεσης -------------------------------------------------------


def test_check_reports_healthy_local_setup(tmp_path):
    init_db(tmp_path / "timologio.db").close()
    health = presence.check_connection(tmp_path, tmp_path / "timologio.db")
    assert health.ok
    assert health.first_problem is None


def test_check_names_the_missing_folder(tmp_path):
    missing = tmp_path / "δεν-υπάρχει"
    health = presence.check_connection(missing, missing / "timologio.db")
    assert not health.ok
    # Το πρώτο πρόβλημα πρέπει να είναι ο φάκελος και όχι η βάση: το μήνυμα που
    # θα δει το τερματικό πρέπει να δείχνει την αιτία, όχι το σύμπτωμα.
    assert health.first_problem.name == "Φάκελος δεδομένων"


def test_check_reports_missing_database_separately(tmp_path):
    health = presence.check_connection(tmp_path, tmp_path / "timologio.db")
    assert not health.ok
    assert health.first_problem.name == "Βάση δεδομένων"


def test_check_leaves_no_probe_file_behind(tmp_path):
    init_db(tmp_path / "timologio.db").close()
    presence.check_connection(tmp_path, tmp_path / "timologio.db")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".σύνδεση")]
    assert leftovers == []

"""Έλεγχοι στο ίδιο το script του installer.

Το Inno Setup δεν τρέχει σε CI, οπότε δεν μπορούμε να εκτελέσουμε τη λογική
του. Μπορούμε όμως να φυλάξουμε τις αποφάσεις που κόστισαν: η μία από αυτές
(η ανάγνωση του ρόλου κατά την απεγκατάσταση) έσβηνε τα δεδομένα ΟΛΟΥ του
γραφείου από ένα απλό τερματικό, και το σύμπτωμα εμφανιζόταν μόνο σε πραγματική
απεγκατάσταση.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ISS = Path(__file__).resolve().parents[1] / "installer" / "timologio.iss"


@pytest.fixture(scope="module")
def script() -> str:
    return ISS.read_text(encoding="utf-8-sig")


def test_role_and_datadir_are_read_before_registry_is_deleted(script: str):
    """Και τα δύο διαβάζονται στο InitializeUninstall.

    Στο usPostUninstall τα κλειδιά έχουν ήδη σβηστεί από τα uninsdeletevalue /
    uninsdeletekey. Μια ανάγνωση εκεί αποτυγχάνει σιωπηλά και ο ρόλος πέφτει σε
    'standalone' — δηλαδή ένα τερματικό θα θεωρούσε δικά του τα δεδομένα του
    server και θα τα διέγραφε.
    """
    start = script.index("function InitializeUninstall")
    end = script.index("procedure DeleteDataDir")
    body = script[start:end]
    assert "'DataDir', UninstDataDir" in body
    assert "'Role', UninstRole" in body


def test_uninstall_never_deletes_for_terminal_or_unknown_role(script: str):
    start = script.index("procedure CurUninstallStepChanged")
    body = script[start:]
    assert "if (Role = '') or (Role = 'terminal') then" in body
    # Το Exit πρέπει να προηγείται κάθε κλήσης διαγραφής.
    guard = body.index("(Role = '') or (Role = 'terminal')")
    assert guard < body.index("DelTree")
    assert guard < body.index("DeleteDataDir")


def test_silent_uninstall_never_shows_a_dialog(script: str):
    """Ένα MsgBox σε σιωπηλή απεγκατάσταση κρεμάει μαζικά deployments."""
    start = script.index("procedure CurUninstallStepChanged")
    body = script[start:]
    assert "if UninstallSilent then" in body
    assert body.index("if UninstallSilent then") < body.index("MsgBox")


def test_deletion_requires_two_confirmations(script: str):
    start = script.index("procedure CurUninstallStepChanged")
    body = script[start:]
    # Δύο ερωτήσεις πριν από κάθε διαγραφή, και οι δύο με προεπιλογή το «Όχι».
    assert body.count("MB_YESNO or MB_DEFBUTTON2") == 2


def test_command_line_datadir_is_not_overwritten(script: str):
    """Χωρίς αυτό, σιωπηλή εγκατάσταση τερματικού αντικαθιστούσε τη διαδρομή
    του πελάτη με το δείγμα \\\\SERVER\\... και αποτύγχανε."""
    start = script.index("procedure CurPageChanged")
    body = script[start:]
    assert "if DataDirFromCommandLine then" in body
    assert body.index("DataDirFromCommandLine") < body.index("IsTerminal")


def test_terminal_still_requires_a_network_path(script: str):
    """Το τερματικό χωρίς UNC διαδρομή φτιάχνει σιωπηλά δεύτερη, άδεια βάση."""
    assert "if Pos('\\\\', Dir) <> 1 then" in script


def test_autostart_is_per_user(script: str):
    """HKLM θα απαιτούσε δικαιώματα διαχειριστή και UAC."""
    assert "Root: HKCU; Subkey: \"Software\\Microsoft\\Windows\\CurrentVersion\\Run\"" in script
    assert "Check: WantsAutostart" in script


def test_postinstall_launch_forces_show(script: str):
    """Μετά την εγκατάσταση τρέχουμε με --show, ώστε η πρώτη εμφάνιση να μη
    μαζεύεται στο tray ακόμη κι αν έχει επιλεγεί «εκκίνηση στο tray»."""
    start = script.index("[Run]")
    body = script[start:]
    assert 'Parameters: "--show"' in body
    assert "postinstall" in body

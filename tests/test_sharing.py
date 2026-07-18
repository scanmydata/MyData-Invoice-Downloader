"""Κοινή χρήση του φακέλου δεδομένων.

Η ίδια η δημιουργία share απαιτεί δικαιώματα διαχειριστή και αλλάζει ρυθμίσεις
του συστήματος — δεν γίνεται σε test. Ελέγχουμε ό,τι μπορεί να ελεγχθεί χωρίς
αυτό: τα ονόματα, την αναγνώριση υπάρχοντος share, και το ίδιο το script που θα
τρέξει ανυψωμένο (εκεί ένα λάθος quoting είναι σιωπηλή αποτυχία με UAC ήδη
εγκεκριμένο).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from timologio import sharing


@pytest.mark.parametrize(
    "name",
    ["ParastatikaMyDATA", "myDATA", "a" * 80],
)
def test_valid_names(name):
    assert sharing.is_valid_name(name)


@pytest.mark.parametrize(
    "name",
    ["", "a" * 81, "με\\backslash", "με/slash", "με:άνω", "με*αστέρι", "με?ερώτημα",
     'με"εισαγωγικά', "με<μικρότερο", "με|κάθετο"],
)
def test_invalid_names(name):
    assert not sharing.is_valid_name(name)


def test_suggested_name_avoids_greek_and_spaces():
    """Το όνομα πληκτρολογείται σε κάθε τερματικό — τα ελληνικά και τα κενά
    είναι ευκαιρίες για τυπογραφικό που εμφανίζεται ως «δεν βρίσκω τον server»."""
    suggested = sharing.suggest_name(Path(r"C:\Users\x\Documents\Παραστατικά myDATA"))
    assert suggested == sharing.DEFAULT_SHARE_NAME
    assert suggested.isascii()
    assert " " not in suggested


def test_suggested_name_keeps_a_usable_latin_folder_name():
    assert sharing.suggest_name(Path(r"C:\data\Invoices 2026")) == "Invoices2026"


def test_suggested_name_never_empty():
    assert sharing.suggest_name(Path("C:/")) == sharing.DEFAULT_SHARE_NAME


def test_unc_path_is_built_from_host_and_name():
    info = sharing.ShareInfo(name="ParastatikaMyDATA", path=r"C:\data")
    assert info.unc == rf"\\{sharing.host_name()}\ParastatikaMyDATA"


def test_share_script_sets_both_smb_and_ntfs_rights():
    """Μόνο SMB δίνει «δεν έχετε πρόσβαση» — το κλασικό μισοφτιαγμένο share."""
    script = sharing.build_share_script(Path(r"C:\data"), "Δοκιμή", "Everyone")
    assert "New-SmbShare" in script
    assert "FileSystemAccessRule" in script
    assert "Set-Acl" in script


def test_share_script_enables_firewall_by_language_neutral_id():
    """Το DisplayGroup είναι μεταφρασμένο· σε ελληνικά Windows δεν θα έβρισκε
    τους κανόνες και το share θα ήταν αόρατο στο δίκτυο."""
    script = sharing.build_share_script(Path(r"C:\data"), "x", "Everyone")
    assert "@FirewallAPI.dll,-28502" in script
    assert "DisplayGroup" not in script


def test_share_script_replaces_an_existing_share_of_the_same_name():
    script = sharing.build_share_script(Path(r"C:\data"), "x", "Everyone")
    assert script.index("Remove-SmbShare") < script.index("New-SmbShare")


def test_script_escapes_single_quotes_in_paths():
    """Ένας φάκελος «Ο' Μπράιαν» θα έσπαγε το script — με το UAC ήδη δοσμένο."""
    script = sharing.build_share_script(Path(r"C:\O'Brien"), "x", "Everyone")
    assert "$p='C:\\O''Brien'" in script


def test_find_share_ignores_administrative_shares(monkeypatch, tmp_path):
    """Τα C$ και ADMIN$ υπάρχουν πάντα και δεν εξυπηρετούν τα τερματικά."""
    monkeypatch.setattr(
        sharing, "list_shares",
        lambda: [sharing.ShareInfo(name="C$", path=str(tmp_path))],
    )
    assert sharing.find_share_for(tmp_path) is None


def test_find_share_matches_the_data_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sharing, "list_shares",
        lambda: [
            sharing.ShareInfo(name="Άλλο", path=str(tmp_path / "αλλού")),
            sharing.ShareInfo(name="Σωστό", path=str(tmp_path)),
        ],
    )
    found = sharing.find_share_for(tmp_path)
    assert found is not None and found.name == "Σωστό"


def test_unshare_script_targets_only_the_named_share():
    script = sharing.build_unshare_script("ParastatikaMyDATA")
    assert "Remove-SmbShare -Name 'ParastatikaMyDATA'" in script
    assert "New-SmbShare" not in script

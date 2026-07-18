"""Ο κύριος κωδικός: τύλιγμα του κλειδιού δεδομένων.

Η ουσία που ελέγχεται εδώ είναι μία: **χωρίς τον κωδικό, ένα αντίγραφο του
φακέλου δεδομένων δεν αποδίδει τίποτα**. Όλα τα υπόλοιπα (αλλαγή κωδικού,
συμβατότητα με παλιά αρχεία) υπάρχουν για να μη σπάσει κανείς αυτή την ιδιότητα
προσπαθώντας να βολέψει κάτι άλλο.
"""

from __future__ import annotations

import pytest

from timologio import crypto
from timologio.crypto import Crypto, KeyfileLocked, WrongPassword

PASSWORD = "kodikos-grafeiou-2026"
SECRET = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"


@pytest.fixture(autouse=True)
def _clean_cache():
    crypto.forget()
    yield
    crypto.forget()


@pytest.fixture
def keyfile(tmp_path, monkeypatch):
    # Το TIMOLOGIO_ENC_KEY παρακάμπτει τα πάντα· αν το έχει ο υπολογιστής που
    # τρέχει τις δοκιμές, όλα θα «περνούσαν» χωρίς να δοκιμαστεί τίποτα.
    monkeypatch.delenv("TIMOLOGIO_ENC_KEY", raising=False)
    monkeypatch.delenv("TIMOLOGIO_MASTER_PASSWORD", raising=False)
    return tmp_path / ".enckey"


def test_each_data_dir_gets_its_own_key(tmp_path, monkeypatch):
    monkeypatch.delenv("TIMOLOGIO_ENC_KEY", raising=False)
    keys = {
        crypto.load_or_create_key(tmp_path / str(i) / ".enckey") for i in range(3)
    }
    assert len(keys) == 3


def test_unprotected_keyfile_still_works(keyfile):
    token = Crypto(keyfile).enc(SECRET)
    assert not crypto.is_protected(keyfile)
    assert Crypto(keyfile).dec(token) == SECRET


def test_password_makes_the_folder_useless_without_it(keyfile):
    token = Crypto(keyfile).enc(SECRET)
    crypto.set_password(keyfile, PASSWORD)
    crypto.forget()

    assert crypto.is_protected(keyfile)
    with pytest.raises(KeyfileLocked):
        Crypto(keyfile)
    with pytest.raises(WrongPassword):
        Crypto(keyfile, "lathos-kodikos")
    assert Crypto(keyfile, PASSWORD).dec(token) == SECRET


def test_plaintext_key_is_not_on_disk_once_protected(keyfile):
    key = crypto.load_or_create_key(keyfile)
    crypto.set_password(keyfile, PASSWORD)
    assert key not in keyfile.read_bytes()
    assert PASSWORD.encode() not in keyfile.read_bytes()


def test_changing_password_keeps_the_data_key(keyfile):
    """Αλλιώς κάθε αλλαγή κωδικού θα απαιτούσε ξανακρυπτογράφηση της βάσης."""
    token = Crypto(keyfile).enc(SECRET)
    crypto.set_password(keyfile, PASSWORD)
    crypto.set_password(keyfile, "allos-kodikos-2026", current=PASSWORD)
    crypto.forget()

    assert Crypto(keyfile, "allos-kodikos-2026").dec(token) == SECRET
    with pytest.raises(WrongPassword):
        Crypto(keyfile, PASSWORD)


def test_wrong_current_password_cannot_change_it(keyfile):
    Crypto(keyfile)
    crypto.set_password(keyfile, PASSWORD)
    crypto.forget()
    with pytest.raises(WrongPassword):
        crypto.set_password(keyfile, "neos", current="lathos")
    crypto.forget()
    assert Crypto(keyfile, PASSWORD)  # ο παλιός ισχύει ακόμη


def test_current_password_is_verified_even_while_unlocked(keyfile):
    """Μέσα στην εφαρμογή το κλειδί είναι πάντα ξεκλειδωμένο.

    Αν η επιβεβαίωση του τρέχοντος κωδικού διαβάσει από την cache αντί από το
    αρχείο, τότε όποιος βρει ανοιχτό υπολογιστή αλλάζει ή αφαιρεί την προστασία
    χωρίς να ξέρει τον κωδικό.
    """
    Crypto(keyfile)
    crypto.set_password(keyfile, PASSWORD)
    assert crypto.load_or_create_key(keyfile)  # ξεκλείδωτο, cache γεμάτη

    with pytest.raises(WrongPassword):
        crypto.set_password(keyfile, "neos-kodikos", current="lathos")
    with pytest.raises(WrongPassword):
        crypto.remove_password(keyfile, "lathos")
    assert crypto.is_protected(keyfile)


def test_removing_protection_restores_plain_keyfile(keyfile):
    token = Crypto(keyfile).enc(SECRET)
    crypto.set_password(keyfile, PASSWORD)
    crypto.forget()
    crypto.remove_password(keyfile, PASSWORD)
    crypto.forget()

    assert not crypto.is_protected(keyfile)
    assert Crypto(keyfile).dec(token) == SECRET


def test_unlock_serves_worker_threads(keyfile):
    """Ο χρήστης δίνει τον κωδικό μία φορά· τα threads δεν ξαναρωτούν."""
    token = Crypto(keyfile).enc(SECRET)
    crypto.set_password(keyfile, PASSWORD)
    crypto.forget()

    crypto.unlock(keyfile, PASSWORD)
    assert Crypto(keyfile).dec(token) == SECRET  # χωρίς κωδικό, από την cache


def test_env_password_for_scheduled_tasks(keyfile, monkeypatch):
    token = Crypto(keyfile).enc(SECRET)
    crypto.set_password(keyfile, PASSWORD)
    crypto.forget()

    monkeypatch.setenv("TIMOLOGIO_MASTER_PASSWORD", PASSWORD)
    assert Crypto(keyfile).dec(token) == SECRET


def test_empty_password_refused(keyfile):
    with pytest.raises(ValueError):
        crypto.set_password(keyfile, "")


def test_scrypt_fallback_file_still_opens(keyfile, monkeypatch):
    """Μηχάνημα χωρίς Argon2id γράφει scrypt — και το ξαναδιαβάζει."""
    monkeypatch.setattr(crypto, "_preferred_kdf", lambda: "scrypt")
    token = Crypto(keyfile).enc(SECRET)
    crypto.set_password(keyfile, PASSWORD)
    crypto.forget()

    assert b"kdf: scrypt" in keyfile.read_bytes()
    assert Crypto(keyfile, PASSWORD).dec(token) == SECRET


def test_interrupted_write_leaves_the_key_intact(keyfile, monkeypatch):
    """Το `.enckey` είναι το μοναδικό αντίγραφο: μισογραμμένο = όλα χαμένα."""
    token = Crypto(keyfile).enc(SECRET)
    before = keyfile.read_bytes()

    def boom(src, dst):
        raise OSError("διακοπή ρεύματος")

    monkeypatch.setattr(crypto.os, "replace", boom)
    with pytest.raises(OSError):
        crypto.set_password(keyfile, PASSWORD)

    monkeypatch.undo()
    crypto.forget()
    assert keyfile.read_bytes() == before
    assert Crypto(keyfile).dec(token) == SECRET

"""Ένα μόνο αντίγραφο ανά χρήστη.

Ο χρήστης παραπονέθηκε ότι, με την εφαρμογή μαζεμένη στο tray, ένα διπλό κλικ
στη συντόμευση άνοιγε ΔΕΥΤΕΡΟ αντίγραφο αντί να φέρει μπροστά το υπάρχον. Ο
φρουρός στο app.py το κόβει: το δεύτερο αντίγραφο συνδέεται στο local socket
του πρώτου, του λέει «show» και βγαίνει.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from timologio.gui.app import (  # noqa: E402
    _activate_running_instance,
    _install_instance_guard,
    _instance_key,
)


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


class _FakeWindow:
    """Ό,τι ακριβώς χρειάζεται ο φρουρός: μια μέθοδος bring_to_front."""

    def __init__(self) -> None:
        self.brought = 0

    def bring_to_front(self) -> None:
        self.brought += 1


def test_instance_key_is_per_user(monkeypatch):
    monkeypatch.setenv("USERNAME", "alice")
    assert _instance_key().endswith(".alice")
    monkeypatch.setenv("USERNAME", "bob")
    assert _instance_key().endswith(".bob")


def test_no_running_instance_returns_false(app, monkeypatch):
    # Μοναδικό κλειδί για το test ώστε να μη συγκρούεται με πραγματικό instance.
    monkeypatch.setenv("USERNAME", "pytest-none")
    assert _activate_running_instance() is False


def test_second_instance_brings_the_first_to_front(app, monkeypatch):
    monkeypatch.setenv("USERNAME", "pytest-guard")
    window = _FakeWindow()
    server = _install_instance_guard(window)
    assert server is not None
    try:
        # Δεύτερο «αντίγραφο» στην ίδια διεργασία: συνδέεται στον φρουρό.
        assert _activate_running_instance() is True
        # Η newConnection τρέχει μέσω event loop — δώσ' της χρόνο.
        for _ in range(20):
            QApplication.processEvents()
            if window.brought:
                break
        assert window.brought >= 1
    finally:
        server.close()


def test_guard_survives_stale_socket(app, monkeypatch):
    """Δεύτερο listen στο ίδιο κλειδί δεν πρέπει να σκάει σε «address in use»:
    ο φρουρός καθαρίζει το ορφανό socket πριν το listen."""
    monkeypatch.setenv("USERNAME", "pytest-stale")
    first = _install_instance_guard(_FakeWindow())
    assert first is not None
    # Χωρίς να κλείσουμε τον πρώτο, ένας δεύτερος (νέα εκκίνηση μετά από crash)
    # καθαρίζει και ξαναστήνει.
    second = _install_instance_guard(_FakeWindow())
    try:
        assert second is not None
    finally:
        first.close()
        if second is not None:
            second.close()

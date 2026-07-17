"""Tests για το αρχείο καταγραφής.

Το ιστορικό έφυγε από την οθόνη — αν το αρχείο δεν γράφεται σωστά, δεν υπάρχει
πουθενά αλλού.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from timologio import logs


@pytest.fixture(autouse=True)
def clean_root():
    """Κάθε test ξεκινά χωρίς handlers από προηγούμενο."""
    root = logging.getLogger()
    saved = list(root.handlers)
    root.handlers.clear()
    yield
    for handler in root.handlers:
        handler.close()
    root.handlers[:] = saved


def _record(when: float) -> logging.LogRecord:
    record = logging.LogRecord(
        "timologio.test", logging.WARNING, __file__, 1, "μήνυμα", None, None
    )
    record.created = when
    return record


def test_setup_creates_log_file(tmp_path: Path) -> None:
    path = logs.setup(tmp_path)
    assert path.exists()
    assert path.parent.name == "logs"


def test_setup_writes_greek_startup_line(tmp_path: Path) -> None:
    path = logs.setup(tmp_path)
    logging.getLogger("timologio.test").info("δοκιμή")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert "δοκιμή" in path.read_text(encoding="utf-8")


def test_setup_twice_does_not_duplicate_lines(tmp_path: Path) -> None:
    """Δύο handlers στο ίδιο αρχείο θα έγραφαν κάθε γραμμή δύο φορές."""
    path = logs.setup(tmp_path)
    logs.setup(tmp_path)
    logging.getLogger("timologio.test").info("μία φορά")
    for handler in logging.getLogger().handlers:
        handler.flush()
    text = path.read_text(encoding="utf-8")
    assert text.count("μία φορά") == 1


def test_key_never_reaches_the_log_file(tmp_path: Path) -> None:
    """Το αρχείο είναι ό,τι θα σταλεί για υποστήριξη — δεν πάει κλειδί μέσα.

    Το «κλειδί» είναι επίτηδες ψεύτικο: το φίλτρο κοιτάζει σχήμα (32
    δεκαεξαδικά), οπότε ένα αληθινό δεν θα πρόσθετε τίποτα στο test — θα
    πρόσθετε μόνο ένα credential πελάτη μέσα στο git.
    """
    path = logs.setup(tmp_path)
    key = "deadbeefcafef00d0123456789abcdef"
    logging.getLogger("timologio.test").info("κλήση με κλειδί %s", key)
    for handler in logging.getLogger().handlers:
        handler.flush()

    text = path.read_text(encoding="utf-8")
    assert key not in text
    assert "<redacted-key>" in text


def test_header_style_secrets_are_redacted(tmp_path: Path) -> None:
    path = logs.setup(tmp_path)
    logging.getLogger("timologio.test").warning(
        "headers: aade-user-id: XRHSTHS_DOKIMHS"
    )
    for handler in logging.getLogger().handlers:
        handler.flush()
    text = path.read_text(encoding="utf-8")
    assert "XRHSTHS_DOKIMHS" not in text
    assert "<redacted>" in text


def test_formatter_uses_greek_date_order() -> None:
    formatter = logs.GreekFormatter("%(asctime)s %(levelshort)s %(message)s")
    # 17/07/2026 09:30:00 UTC
    moment = datetime(2026, 7, 17, 9, 30, 0, tzinfo=timezone.utc).timestamp()
    line = formatter.format(_record(moment))
    assert re.match(r"^17/07/2026 \d{2}:30:00 ", line), line


def test_formatter_translates_level() -> None:
    formatter = logs.GreekFormatter("%(levelshort)s %(message)s")
    assert formatter.format(_record(0)).startswith("ΠΡΟΣ")


def test_formatter_shifts_utc_to_athens() -> None:
    """Τον Ιούλιο η Ελλάδα είναι UTC+3 — 09:30 UTC είναι 12:30 τοπικά.

    Αν λείπει το tzdata (Windows χωρίς το πακέτο), πέφτουμε στην τοπική ώρα του
    μηχανήματος· το test δέχεται και τα δύο, αρκεί να μη μείνει σε UTC όταν η
    ζώνη είναι όντως διαθέσιμη.
    """
    if logs._athens_tz() is None:
        pytest.skip("δεν υπάρχει βάση ζωνών ώρας σε αυτό το μηχάνημα")
    formatter = logs.GreekFormatter("%(asctime)s")
    moment = datetime(2026, 7, 17, 9, 30, 0, tzinfo=timezone.utc).timestamp()
    assert formatter.format(_record(moment)) == "17/07/2026 12:30:00"

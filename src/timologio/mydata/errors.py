"""Σφάλματα myDATA."""

from __future__ import annotations


class MydataError(Exception):
    """Βάση για όλα τα σφάλματα ΑΑΔΕ."""

    message_el = "Σφάλμα ΑΑΔΕ"


class AuthError(MydataError):
    """Άκυρα διαπιστευτήρια.

    Μετρημένο: λάθος subscription key -> HTTP 403 με **κενό body**. Δεν
    υπάρχει XML να παρσάρουμε, οπότε το fetch.py:137 θα έφτιαχνε ένα
    RuntimeError με κενό μήνυμα. Εδώ το κάνουμε ρητό.
    """

    message_el = "Άκυρο κλειδί API ή δικαιώματα"


class RateLimitError(MydataError):
    message_el = "Προσωρινός περιορισμός από την ΑΑΔΕ"

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("rate limited")
        self.retry_after = retry_after


class TransientError(MydataError):
    """5xx / timeout — αξίζει retry."""

    message_el = "Προσωρινό σφάλμα ΑΑΔΕ"


class MissingKeyError(MydataError):
    """Ο πελάτης δεν έχει κλειδί API.

    Μετρημένο: 95 από τους 153 πελάτες του Κωδικοί_Υπόχρεων.xlsx. Είναι η
    πλειοψηφία, όχι εξαίρεση.
    """

    message_el = "Λείπει κλειδί API"

"""Δεδομένα επίδειξης για την πρώτη εκκίνηση.

Μια ολοκαίνουργια εγκατάσταση ανοίγει σε άδειο πίνακα: ο χρήστης βλέπει μια
εφαρμογή που δεν κάνει τίποτα και μια ξενάγηση που δείχνει άδεια κουτιά. Γι'
αυτό η πρώτη εκκίνηση γεμίζει τη βάση με **φανταστικούς** πελάτες και
παραστατικά, ώστε η ξενάγηση να έχει τι να δείξει.

Μόλις ολοκληρωθεί η ξενάγηση, τα δεδομένα σβήνονται και ο χρήστης ενημερώνεται
ότι πρέπει να βάλει τα δικά του.

Τίποτα εδώ δεν είναι πραγματικό: τα ΑΦΜ είναι κατασκευασμένα (περνούν τον
έλεγχο mod-11 ώστε να μη σημαίνονται ως λάθος) και οι επωνυμίες φανταστικές.
Τα «κλειδιά» είναι προφανώς ψεύτικα, οπότε καμία λήψη δεν μπορεί να πετύχει.
"""

from __future__ import annotations

import sqlite3

from .crypto import Crypto
from .models import Client, Direction, Document

#: Σημάδι στο `source_file`: από αυτό αναγνωρίζουμε τι είναι επίδειξη.
DEMO_SOURCE = "__επίδειξη__"

#: Κατάσταση στον πίνακα `meta`. Ζει στη βάση και όχι στα QSettings ώστε να
#: ταξιδεύει μαζί με τον φάκελο δεδομένων: σε εγκατάσταση «Τερματικό» που
#: δείχνει στον server, η βάση έχει ήδη πελάτες και δεν ξαναμπαίνει επίδειξη.
_META_KEY = "demo_state"

_CLIENTS: list[tuple[str, str, bool]] = [
    ("123456783", "ΔΕΙΓΜΑ ΕΜΠΟΡΙΚΗ ΑΕ", True),
    ("987654324", "ΧΡΩΜΑΤΑ ΠΑΡΑΔΕΙΓΜΑ ΟΕ", True),
    ("555555559", "ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ ΙΚΕ", True),
    ("044004008", "ΠΑΡΑΔΕΙΓΜΑ ΧΩΡΙΣ ΚΛΕΙΔΙ ΑΕ", False),
]

_SUPPLIERS = [
    ("111222336", "ΠΡΟΜΗΘΕΥΤΗΣ ΔΕΙΓΜΑ ΑΕ"),
    ("222333440", "ΥΠΗΡΕΣΙΕΣ ΠΑΡΑΔΕΙΓΜΑ ΟΕ"),
]


def _state(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (_META_KEY,)).fetchone()
    return row["value"] if row else ""


def _set_state(conn: sqlite3.Connection, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_META_KEY, value),
    )


def should_seed(conn: sqlite3.Connection) -> bool:
    """Μόνο σε ολοκαίνουργια, άδεια βάση που δεν έχει ξαναδεί επίδειξη."""
    if _state(conn):
        return False
    clients = conn.execute("SELECT COUNT(*) c FROM clients").fetchone()["c"]
    return clients == 0


def has_demo(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) c FROM clients WHERE source_file = ?", (DEMO_SOURCE,)
    ).fetchone()
    return bool(row["c"])


def seed(conn: sqlite3.Connection, crypto: Crypto) -> int:
    """Γεμίζει τη βάση με φανταστικά δεδομένα. Επιστρέφει πλήθος πελατών."""
    from . import repo

    for vat, label, has_key in _CLIENTS:
        client = Client(
            vat=vat,
            label=label,
            mydata_user=f"demo{vat}" if has_key else "",
            # Προφανώς ψεύτικο, αλλά στη σωστή μορφή (32 hex) ώστε ο πελάτης να
            # εμφανίζεται ως «Διαθέσιμος» και να δείχνει η ξενάγηση κανονικά.
            mydata_key=("d" * 32) if has_key else "",
            source_file=DEMO_SOURCE,
        )
        client_id = repo.upsert_client(conn, client, crypto)
        if not has_key:
            continue
        for index in range(3):
            supplier_vat, supplier_name = _SUPPLIERS[index % len(_SUPPLIERS)]
            repo.upsert_document(
                conn,
                client_id,
                Document(
                    mark=f"4{vat}{index:04d}",
                    direction=Direction.INCOMING,
                    invoice_type="1.1",
                    issuer_vat=supplier_vat,
                    issuer_name=supplier_name,
                    counter_vat=vat,
                    series="Α",
                    aa=str(index + 1),
                    issue_date=f"2026-07-{index + 10:02d}",
                    net_value=100.0 * (index + 1),
                    vat_amount=24.0 * (index + 1),
                    total_value=124.0 * (index + 1),
                    downloading_invoice_url="",
                    provider_host="",
                ),
            )
    for vat, name in _SUPPLIERS:
        repo.upsert_supplier(conn, vat, name, "invoice")
    repo.seed_suppliers_from_clients(conn)
    _set_state(conn, "seeded")
    conn.commit()
    return len(_CLIENTS)


def clear(conn: sqlite3.Connection) -> int:
    """Σβήνει ΜΟΝΟ τα δεδομένα επίδειξης. Επιστρέφει πλήθος πελατών."""
    vats = [
        r["vat"]
        for r in conn.execute(
            "SELECT vat FROM clients WHERE source_file = ?", (DEMO_SOURCE,)
        )
    ]
    if vats:
        placeholders = ",".join("?" * len(vats))
        # Τα παραστατικά φεύγουν με ON DELETE CASCADE.
        conn.execute(f"DELETE FROM clients WHERE vat IN ({placeholders})", vats)
        conn.execute(
            f"DELETE FROM suppliers WHERE vat IN ({placeholders})", vats
        )
    for vat, _ in _SUPPLIERS:
        conn.execute("DELETE FROM suppliers WHERE vat = ?", (vat,))
    _set_state(conn, "cleared")
    conn.commit()
    return len(vats)

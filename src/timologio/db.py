"""Schema και σύνδεση SQLite.

WAL γιατί στη Φάση 4 το GUI thread διαβάζει ενώ ο orchestrator γράφει.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA_VERSION = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  vat                 TEXT NOT NULL UNIQUE,
  label               TEXT NOT NULL DEFAULT '',
  office_code         TEXT NOT NULL DEFAULT '',
  mydata_user_enc     TEXT NOT NULL DEFAULT '',
  mydata_key_enc      TEXT NOT NULL DEFAULT '',
  status              TEXT NOT NULL DEFAULT 'missing_key',
  last_mark_incoming  TEXT NOT NULL DEFAULT '0',
  last_mark_outgoing  TEXT NOT NULL DEFAULT '0',
  source_file         TEXT NOT NULL DEFAULT '',
  imported_at         TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS documents (
  id                      INTEGER PRIMARY KEY AUTOINCREMENT,
  client_id               INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  mark                    TEXT NOT NULL,
  direction               TEXT NOT NULL DEFAULT 'incoming',
  invoice_type            TEXT NOT NULL DEFAULT '',
  issuer_vat              TEXT NOT NULL DEFAULT '',
  issuer_name             TEXT NOT NULL DEFAULT '',
  counter_vat             TEXT NOT NULL DEFAULT '',
  counter_name            TEXT NOT NULL DEFAULT '',
  series                  TEXT NOT NULL DEFAULT '',
  aa                      TEXT NOT NULL DEFAULT '',
  issue_date              TEXT NOT NULL DEFAULT '',
  net_value               REAL NOT NULL DEFAULT 0,
  vat_amount              REAL NOT NULL DEFAULT 0,
  total_value             REAL NOT NULL DEFAULT 0,
  downloading_invoice_url TEXT NOT NULL DEFAULT '',
  provider_host           TEXT NOT NULL DEFAULT '',
  classification          TEXT NOT NULL DEFAULT 'unknown',
  status                  TEXT NOT NULL DEFAULT 'pending',
  local_path              TEXT NOT NULL DEFAULT '',
  xml_path                TEXT NOT NULL DEFAULT '',
  file_bytes              INTEGER NOT NULL DEFAULT 0,
  file_sha256             TEXT NOT NULL DEFAULT '',
  error_text              TEXT NOT NULL DEFAULT '',
  retry_count             INTEGER NOT NULL DEFAULT 0,
  next_retry_at           TEXT NOT NULL DEFAULT '',
  first_seen_at           TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at              TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(client_id, mark)
);

CREATE INDEX IF NOT EXISTS idx_doc_status ON documents(status, next_retry_at);
CREATE INDEX IF NOT EXISTS idx_doc_client ON documents(client_id, status);
CREATE INDEX IF NOT EXISTS idx_doc_host   ON documents(provider_host, status);

CREATE TABLE IF NOT EXISTS runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at    TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at   TEXT,
  date_from     TEXT NOT NULL DEFAULT '',
  date_to       TEXT NOT NULL DEFAULT '',
  clients_total INTEGER NOT NULL DEFAULT 0,
  clients_done  INTEGER NOT NULL DEFAULT 0,
  docs_found    INTEGER NOT NULL DEFAULT 0,
  pdfs_ok       INTEGER NOT NULL DEFAULT 0,
  no_url        INTEGER NOT NULL DEFAULT 0,
  failed        INTEGER NOT NULL DEFAULT 0,
  status        TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS run_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id     INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  ts         TEXT NOT NULL DEFAULT (datetime('now')),
  client_vat TEXT NOT NULL DEFAULT '',
  mark       TEXT NOT NULL DEFAULT '',
  level      TEXT NOT NULL DEFAULT 'info',
  event      TEXT NOT NULL DEFAULT '',
  detail     TEXT NOT NULL DEFAULT ''
);

-- Μητρώο επωνυμιών ανά ΑΦΜ.
-- Το myDATA συμπληρώνει το <issuer><name> μόνο στο ~70% των παραστατικών, ενώ
-- το όνομα του προμηθευτή μπαίνει στο όνομα του αρχείου. Μαζεύουμε κάθε
-- επωνυμία που βλέπουμε (από οποιοδήποτε παραστατικό, από το Excel πελατών, ή
-- χειροκίνητα) και τη χρησιμοποιούμε ξανά όπου λείπει.
CREATE TABLE IF NOT EXISTS suppliers (
  vat        TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  source     TEXT NOT NULL DEFAULT 'invoice',  -- invoice|vies|client|manual
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Ποια διαστήματα ημερομηνιών έχουν όντως ζητηθεί, ανά πελάτη και κατεύθυνση.
-- Χωρίς αυτό, ο incremental cursor κρύβει σιωπηλά παραστατικά όταν ο χρήστης
-- ζητήσει παλιότερη περίοδο (τα MARK της είναι μικρότερα του cursor).
CREATE TABLE IF NOT EXISTS coverage (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  client_id  INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  direction  TEXT NOT NULL,
  date_from  TEXT NOT NULL,   -- ISO
  date_to    TEXT NOT NULL,   -- ISO
  fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_cov_client ON coverage(client_id, direction);

-- ΑΦΜ που ρωτήθηκαν στο VIES χωρίς αποτέλεσμα. Χωρίς αυτό, κάθε sync θα
-- ξαναρωτούσε τα ίδια άγνωστα ΑΦΜ και θα σερνόταν στο rate limit του VIES.
CREATE TABLE IF NOT EXISTS vies_misses (
  vat      TEXT PRIMARY KEY,
  tried_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- Ποιοι υπολογιστές χρησιμοποιούν αυτή τη βάση. Δεν υπάρχει διακομιστής να
-- κρατά συνεδρίες: κάθε instance γράφει τον παλμό του εδώ και «συνδεδεμένος»
-- σημαίνει «έγραψε πρόσφατα». Κλειδί ανά θέση εργασίας (υπολογιστής+χρήστης)
-- και όχι ανά διεργασία, ώστε οι επανεκκινήσεις να μη γεμίζουν τον πίνακα.
CREATE TABLE IF NOT EXISTS peers (
  id         TEXT PRIMARY KEY,
  host       TEXT NOT NULL,
  username   TEXT NOT NULL,
  role       TEXT NOT NULL DEFAULT 'standalone',
  version    TEXT NOT NULL DEFAULT '',
  pid        INTEGER NOT NULL DEFAULT 0,
  data_dir   TEXT NOT NULL DEFAULT '',
  first_seen TEXT NOT NULL,
  last_seen  TEXT NOT NULL
);
"""


def is_network_path(path: Path) -> bool:
    r"""Αληθές αν η βάση κάθεται σε δικτυακό share.

    Πιάνει και τα δύο: UNC (\\server\share\...) και mapped drive (Z:\...).

    Ελέγχουμε το ``Path.drive`` και όχι το κείμενο της διαδρομής: το pathlib
    κανονικοποιεί και το «//server/share» σε «\\\\server\\share», οπότε ένας
    έλεγχος με startswith θα έχανε τη μία από τις δύο γραφές.
    """
    drive = path.drive
    if drive.startswith("\\\\") or drive.startswith("//"):
        return True
    if os.name != "nt" or not drive.endswith(":"):
        return False
    try:
        import ctypes

        # DRIVE_REMOTE = 4
        return ctypes.windll.kernel32.GetDriveTypeW(f"{drive}\\") == 4
    except Exception:
        return False


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row

    if is_network_path(db_path):
        # ΚΡΙΣΙΜΟ: το WAL απαιτεί shared memory (αρχείο -shm) που δεν λειτουργεί
        # πάνω από SMB — η SQLite το τεκμηριώνει ρητά και το αποτέλεσμα είναι
        # φθορά βάσης, όχι απλώς αργή λειτουργία. Σε δικτυακό φάκελο γυρνάμε σε
        # rollback journal, που δουλεύει με κλειδώματα αρχείου.
        conn.execute("PRAGMA journal_mode=TRUNCATE")
        # Σε δίκτυο το NORMAL δεν εγγυάται durability· η ταχύτητα δεν αξίζει τη
        # βάση των πελατών.
        conn.execute("PRAGMA synchronous=FULL")
        # Πολλά τερματικά -> πιο γενναία αναμονή σε lock.
        conn.execute("PRAGMA busy_timeout=20000")
        log.info("Η βάση είναι σε δικτυακό φάκελο — journal_mode=TRUNCATE")
    else:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")

    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Προσθέτει στήλες που λείπουν από παλιότερες βάσεις.

    Το CREATE TABLE IF NOT EXISTS δεν αγγίζει υπάρχοντα πίνακα, οπότε οι νέες
    στήλες πρέπει να μπουν ρητά — αλλιώς μια βάση της v1 σκάει στο πρώτο query.
    """
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(documents)")}
    if "classification" not in existing:
        conn.execute(
            "ALTER TABLE documents ADD COLUMN classification TEXT NOT NULL DEFAULT 'unknown'"
        )

    # Επαναταξινόμηση των «οριστικών σφαλμάτων» που στην πραγματικότητα είναι
    # παραστατικά μόνο-online (ο πάροχος έδωσε σελίδα προβολής αντί για PDF).
    # Δεν ήταν ποτέ σφάλμα· ο νέος κώδικας τα σημειώνει ως viewer_only, και εδώ
    # καθαρίζουμε ό,τι έμεινε από παλιότερες εκδόσεις. Idempotent.
    conn.execute(
        """UPDATE documents SET status='viewer_only', error_text=''
           WHERE status='failed_permanent'
             AND error_text LIKE 'Ο πάροχος επέστρεψε σελίδα%'"""
    )


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = connect(db_path)
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return conn

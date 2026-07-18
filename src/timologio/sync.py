"""Ενορχήστρωση: discover -> persist -> download.

Το GUI της Φάσης 4 θα κάθεται πάνω σε αυτό αμετάβλητο· το CLI παραμένει το
debug surface.
"""

from __future__ import annotations

import logging
import os
import random
import sqlite3
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from . import coverage, repo
from .config import Settings
from .crypto import Crypto
from .download import (
    HostPool,
    ProviderDownloader,
    ProviderError,
    ProviderRateLimited,
    host_slot,
    is_complete_pdf,
    resolve_path,
    target_path,
    write_atomic,
)
from .download.storage import long_path
from .models import Client, Direction, Document, RunStats
from .mydata import AuthError, MissingKeyError, MydataClient, MydataError
from .vies import ViesClient

log = logging.getLogger(__name__)

ProgressFn = Callable[[str], None]


def _noop(_: str) -> None:
    pass


#: Και οι δύο κατευθύνσεις. Ο λογιστής συνήθως τις θέλει μαζί, αλλά όταν κυνηγά
#: μόνο τα έξοδα ενός πελάτη, το μισό αίτημα είναι ο μισός χρόνος.
BOTH_WAYS: tuple[Direction, ...] = (Direction.INCOMING, Direction.OUTGOING)


def discover(
    conn: sqlite3.Connection,
    client: Client,
    settings: Settings,
    *,
    date_from: str,
    date_to: str,
    incremental: bool = True,
    directions: Sequence[Direction] = BOTH_WAYS,
    progress: ProgressFn = _noop,
) -> int:
    """Ανακαλύπτει παραστατικά και τα γράφει στη βάση. Επιστρέφει πλήθος."""
    assert client.id is not None
    found = 0

    # Οι πελάτες του Excel είναι συχνά και αντισυμβαλλόμενοι μεταξύ τους —
    # τζάμπα επωνυμίες για το μητρώο.
    repo.seed_suppliers_from_clients(conn)

    with MydataClient(client.mydata_user, client.mydata_key, settings) as api:
        for direction in directions:
            cursor = "0"
            if incremental and coverage.can_use_cursor(
                conn, client.id, direction, date_from, date_to
            ):
                # Ο cursor είναι ασφαλής μόνο όταν επεκτείνουμε συνεχόμενα κάτι
                # που ήδη έχουμε. Αλλιώς (π.χ. ζητάμε παλιότερη περίοδο) τα MARK
                # της είναι μικρότερα του cursor και η ΑΑΔΕ δεν θα τα έδινε.
                cursor = (
                    client.last_mark_incoming
                    if direction is Direction.INCOMING
                    else client.last_mark_outgoing
                )
            elif incremental:
                progress(
                    f"{client.vat}: νέα περίοδος — πλήρης έλεγχος {direction.value}"
                )

            docs = api.fetch(
                direction, mark=cursor, date_from=date_from, date_to=date_to
            )
            # Πρώτα μαθαίνουμε επωνυμίες, μετά γράφουμε: έτσι ένα παραστατικό
            # χωρίς <name> παίρνει την επωνυμία που είδαμε σε άλλο του ίδιου ΑΦΜ
            # μέσα στην ίδια παρτίδα.
            repo.learn_supplier_names(conn, docs)
            for doc in docs:
                repo.upsert_document(conn, client.id, doc)
                if doc.xml_blob:
                    _save_xml(conn, settings, client, doc)
            repo.backfill_issuer_names(conn, client.id)
            conn.commit()
            found += len(docs)
            progress(f"{client.vat}: {len(docs)} {direction.value}")

            # Ο cursor και το coverage γράφονται μόνο τώρα — μετά από καθαρό
            # τερματισμό. Αν ένα 403 έκοβε τη ροή στη μέση και δηλώναμε την
            # περίοδο καλυμμένη, η ουρά της θα χανόταν σιωπηλά για πάντα.
            marks = [d.mark for d in docs if d.mark.isdigit()]
            if marks:
                repo.advance_cursor(conn, client.id, direction, max(marks, key=int))
            coverage.record(conn, client.id, direction, date_from, date_to)
            conn.commit()

        # Ο χαρακτηρισμός ζητείται πάντα για ΟΛΟ το παράθυρο, ανεξάρτητα από
        # τους cursors: ένα παραστατικό που κατέβηκε χθες μπορεί να
        # χαρακτηρίστηκε σήμερα, οπότε ένα incremental sync πρέπει να το δει.
        try:
            e3 = api.fetch_e3(mark="0", date_from=date_from, date_to=date_to)
        except MydataError as exc:
            # Ο χαρακτηρισμός είναι επιπλέον πληροφορία, όχι ο σκοπός της
            # εφαρμογής — αν αποτύχει, τα PDF κατεβαίνουν κανονικά.
            log.warning("RequestE3Info απέτυχε για %s: %s", client.vat, exc)
            progress(f"{client.vat}: ο χαρακτηρισμός δεν ανακτήθηκε ({exc.message_el})")
        else:
            updated = repo.set_classifications(conn, client.id, e3)
            conn.commit()
            if updated:
                progress(f"{client.vat}: χαρακτηρισμός για {updated} παραστατικά")

    return found


def _save_xml(conn: sqlite3.Connection, settings: Settings, client: Client, doc) -> None:
    """Fallback για τα ~11% χωρίς downloadingInvoiceUrl.

    Δεν υπάρχει PDF παρόχου να κατέβει (δεν πέρασαν από κανάλι παρόχου), αλλά
    το RequestDocs μας δίνει issuer, γραμμές και σύνολα — τα κρατάμε.
    """
    assert client.id is not None and doc.xml_blob
    path = resolve_path(settings.storage_root, client.vat, doc, suffix=".xml",
                        client_label=client.label)
    if not path.exists():
        write_atomic(path, doc.xml_blob)
    repo.mark_xml_saved(
        conn, client.id, doc.mark, str(path.relative_to(settings.storage_root))
    )


def resolve_names_via_vies(
    conn: sqlite3.Connection,
    *,
    client_id: int | None = None,
    limit: int = 200,
    progress: ProgressFn = _noop,
) -> int:
    """Συμπληρώνει επωνυμίες από το VIES για ΑΦΜ που δεν ξέρουμε αλλιώς.

    Τρέχει μετά το backfill, οπότε ρωτάει μόνο ό,τι δεν λύθηκε από παραστατικά ή
    από τη λίστα πελατών. Κάθε ΑΦΜ ρωτιέται μία φορά — τα αποτελέσματα και οι
    αστοχίες αποθηκεύονται μόνιμα.
    """
    pending = repo.vats_needing_name(conn, client_id)
    if not pending:
        return 0

    resolved = 0
    progress(f"VIES: αναζήτηση {min(len(pending), limit)} επωνυμιών…")
    with ViesClient() as vies:
        for vat in pending[:limit]:
            name = vies.lookup(vat)
            if name:
                repo.upsert_supplier(conn, vat, name, "vies")
                resolved += 1
            else:
                repo.record_vies_miss(conn, vat)
    conn.commit()
    if resolved:
        progress(f"VIES: βρέθηκαν {resolved} επωνυμίες")
    return resolved


def _doc_from_row(row: sqlite3.Row) -> Document:
    """Ξαναχτίζει Document από γραμμή της βάσης, για να βγει το όνομα αρχείου."""
    return Document(
        mark=row["mark"],
        invoice_type=row["invoice_type"],
        issuer_vat=row["issuer_vat"],
        issuer_name=row["issuer_name"],
        counter_vat=row["counter_vat"],
        counter_name=row["counter_name"],
        series=row["series"],
        aa=row["aa"],
        issue_date=row["issue_date"],
        total_value=row["total_value"],
    )


def _backoff(attempt: int, settings: Settings, retry_after: float | None = None) -> str:
    delay = retry_after if retry_after else min(2**attempt + random.uniform(0, 1), settings.retry_cap_seconds)
    return (datetime.now() + timedelta(seconds=delay)).strftime("%Y-%m-%d %H:%M:%S")


def download_pending(
    conn: sqlite3.Connection,
    client: Client,
    settings: Settings,
    *,
    stats: RunStats,
    progress: ProgressFn = _noop,
) -> None:
    """Κατεβάζει ό,τι εκκρεμεί για έναν πελάτη.

    Τα workers δεν αγγίζουν sqlite: επιστρέφουν αποτέλεσμα και ο βρόχος εδώ
    (single writer) γράφει.
    """
    assert client.id is not None
    rows = repo.pending_documents(conn, client.id)
    if not rows:
        return

    pool = HostPool(settings.max_per_host)
    downloader = ProviderDownloader(settings)

    def job(row: sqlite3.Row) -> tuple[sqlite3.Row, object]:
        host = row["provider_host"]
        try:
            with host_slot(pool, host):
                return row, downloader.fetch_pdf(row["downloading_invoice_url"])
        except Exception as exc:  # επιστρέφεται, δεν πετιέται
            return row, exc

    try:
        with ThreadPoolExecutor(max_workers=settings.max_workers) as pool_exec:
            for row, outcome in pool_exec.map(job, rows):
                _persist_outcome(conn, client, settings, row, outcome, stats, pool, progress)
                conn.commit()
    finally:
        downloader.close()


def _persist_outcome(
    conn: sqlite3.Connection,
    client: Client,
    settings: Settings,
    row: sqlite3.Row,
    outcome: object,
    stats: RunStats,
    pool: HostPool,
    progress: ProgressFn,
) -> None:
    assert client.id is not None
    mark = row["mark"]

    if isinstance(outcome, ProviderError):
        if isinstance(outcome, ProviderRateLimited):
            pool.throttle(row["provider_host"])
        retryable = outcome.retryable and row["retry_count"] + 1 < settings.max_retries
        repo.mark_failed(
            conn,
            client.id,
            mark,
            f"{outcome.message_el}: {outcome}",
            retryable=retryable,
            next_retry_at=_backoff(row["retry_count"] + 1, settings) if retryable else "",
        )
        stats.failed += 1
        progress(f"  ✗ {mark}: {outcome.message_el}")
        return

    if isinstance(outcome, Exception):
        repo.mark_failed(conn, client.id, mark, str(outcome), retryable=True,
                         next_retry_at=_backoff(row["retry_count"] + 1, settings))
        stats.failed += 1
        progress(f"  ✗ {mark}: {outcome}")
        return

    doc = _doc_from_row(row)
    path = resolve_path(settings.storage_root, client.vat, doc,
                        client_label=client.label)
    size, sha = write_atomic(path, outcome.payload)  # type: ignore[attr-defined]
    repo.mark_downloaded(
        conn, client.id, mark, str(path.relative_to(settings.storage_root)), size, sha
    )
    stats.pdfs_ok += 1
    progress(f"  ✓ {mark} ({size:,} B)")


def rename_existing(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    dry_run: bool = False,
    progress: ProgressFn = _noop,
) -> tuple[int, int]:
    """Μετονομάζει ήδη κατεβασμένα αρχεία στο τρέχον σχήμα ονομάτων.

    Χρειάζεται επειδή το σχήμα άλλαξε από <MARK>_<τύπος>_<ΑΦΜ> σε
    <ΠΡΟΜΗΘΕΥΤΗΣ>_<ΑΦΜ>_<ΗΜ/ΝΙΑ>_<ΣΕΙΡΑ>_<ΑΑ>_<ΑΞΙΑ>. Επιστρέφει
    (μετονομάστηκαν, παραλείφθηκαν).
    """
    rows = list(
        conn.execute(
            """SELECT c.vat client_vat, c.label client_label, d.* FROM documents d
               JOIN clients c ON c.id = d.client_id
               WHERE d.local_path <> '' OR d.xml_path <> ''"""
        )
    )
    renamed = skipped = 0
    for row in rows:
        label = row["client_label"] or ""
        for column, suffix in (("local_path", ".pdf"), ("xml_path", ".xml")):
            stored = row[column]
            if not stored:
                continue
            current = settings.storage_root / stored
            if not current.exists():
                skipped += 1
                continue

            doc = _doc_from_row(row)
            wanted = target_path(settings.storage_root, row["client_vat"], doc, suffix,
                                 client_label=label)
            if wanted == current:
                continue
            if wanted.exists():
                wanted = target_path(
                    settings.storage_root, row["client_vat"], doc, suffix,
                    disambiguate=True, client_label=label,
                )
                if wanted.exists():
                    skipped += 1
                    continue

            if dry_run:
                progress(f"  {current.name}\n    -> {wanted.name}")
                renamed += 1
                continue

            wanted.parent.mkdir(parents=True, exist_ok=True)
            os.replace(long_path(current), long_path(wanted))
            conn.execute(
                f"UPDATE documents SET {column}=?, updated_at=datetime('now')"
                " WHERE client_id=? AND mark=?",
                (str(wanted.relative_to(settings.storage_root)), row["client_id"],
                 row["mark"]),
            )
            renamed += 1
    if not dry_run:
        conn.commit()
        _remove_empty_dirs(settings.storage_root)
    return renamed, skipped


def _remove_empty_dirs(root: Path) -> None:
    """Καθαρίζει φακέλους που άδειασαν μετά τη μετονομασία.

    Χωρίς αυτό, μια αλλαγή σχήματος (π.χ. «123456783» -> «123456783 ΔΕΙΓΜΑ ΕΜΠΟΡΙΚΗ»)
    αφήνει πίσω δεκάδες άδειους φακέλους που μπερδεύουν τον χρήστη.
    """
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir():
            try:
                next(path.iterdir())
            except StopIteration:
                path.rmdir()
            except OSError:
                pass


def sync_client(
    conn: sqlite3.Connection,
    client: Client,
    settings: Settings,
    *,
    date_from: str,
    date_to: str,
    incremental: bool = True,
    directions: Sequence[Direction] = BOTH_WAYS,
    use_vies: bool = True,
    progress: ProgressFn = _noop,
) -> RunStats:
    stats = RunStats()
    try:
        stats.docs_found = discover(
            conn,
            client,
            settings,
            date_from=date_from,
            date_to=date_to,
            incremental=incremental,
            directions=directions,
            progress=progress,
        )
    except MissingKeyError:
        stats.skipped += 1
        progress(f"{client.vat}: Λείπει κλειδί API")
        return stats
    except AuthError as exc:
        # Μόνο αυτός ο πελάτης σταματά· ο cursor μένει ως έχει.
        stats.failed += 1
        progress(f"{client.vat}: {exc.message_el}")
        return stats
    except MydataError as exc:
        stats.failed += 1
        progress(f"{client.vat}: {exc.message_el}")
        return stats

    assert client.id is not None

    # Το VIES καλύπτει ό,τι δεν έδωσαν τα παραστατικά ούτε η λίστα πελατών, ώστε
    # τα ονόματα αρχείων να έχουν επωνυμία και όχι σκέτο ΑΦΜ. Μετά από αυτό
    # ξαναγεμίζουμε τα κενά, πριν χτιστούν τα ονόματα των αρχείων.
    if use_vies:
        try:
            if resolve_names_via_vies(conn, client_id=client.id, progress=progress):
                repo.backfill_issuer_names(conn, client.id)
                conn.commit()
        except Exception as exc:  # το VIES δεν είναι ποτέ λόγος να χαλάσει η λήψη
            log.warning("VIES: %s", exc)

    stats.no_url = int(
        conn.execute(
            "SELECT COUNT(*) c FROM documents WHERE client_id=? AND status='no_provider_url'",
            (client.id,),
        ).fetchone()["c"]
    )
    download_pending(conn, client, settings, stats=stats, progress=progress)
    return stats

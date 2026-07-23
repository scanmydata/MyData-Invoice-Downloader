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
    NotAPdf,
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
from .models import Client, Direction, Document, OperationCancelled, RunStats
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
    should_cancel: Callable[[], bool] | None = None,
) -> int:
    """Ανακαλύπτει παραστατικά και τα γράφει στη βάση. Επιστρέφει πλήθος."""
    assert client.id is not None
    found = 0

    # Οι πελάτες του Excel είναι συχνά και αντισυμβαλλόμενοι μεταξύ τους —
    # τζάμπα επωνυμίες για το μητρώο.
    repo.seed_suppliers_from_clients(conn)

    with MydataClient(client.mydata_user, client.mydata_key, settings) as api:
        for direction in directions:
            if should_cancel and should_cancel():
                break
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
                direction, mark=cursor, date_from=date_from, date_to=date_to,
                should_cancel=should_cancel,
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
            e3 = api.fetch_e3(mark="0", date_from=date_from, date_to=date_to,
                              should_cancel=should_cancel)
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
    should_cancel: Callable[[], bool] | None = None,
) -> int:
    """Συμπληρώνει επωνυμίες από το VIES για ΑΦΜ που δεν ξέρουμε αλλιώς.

    Τρέχει μετά το backfill, οπότε ρωτάει μόνο ό,τι δεν λύθηκε από παραστατικά ή
    από τη λίστα πελατών. Κάθε ΑΦΜ ρωτιέται μία φορά — τα αποτελέσματα και οι
    αστοχίες αποθηκεύονται μόνιμα.

    Το VIES είναι η πιο αργή, σειριακή φάση (έως 200 δικτυακές κλήσεις μία-μία).
    Ελέγχουμε την ακύρωση πριν από κάθε αναζήτηση, ώστε το «Ακύρωση» να πιάνει
    μέσα σε ένα δευτερόλεπτο αντί να περιμένει να τελειώσουν όλες.
    """
    pending = repo.vats_needing_name(conn, client_id)
    if not pending:
        return 0

    resolved = 0
    progress(f"VIES: αναζήτηση {min(len(pending), limit)} επωνυμιών…")
    with ViesClient() as vies:
        for vat in pending[:limit]:
            if should_cancel and should_cancel():
                break
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
    should_cancel: Callable[[], bool] | None = None,
) -> None:
    """Κατεβάζει ό,τι εκκρεμεί για έναν πελάτη.

    Τα workers δεν αγγίζουν sqlite: επιστρέφουν αποτέλεσμα και ο βρόχος εδώ
    (single writer) γράφει.

    Η ακύρωση σταματά ΑΜΕΣΩΣ το πρόγραμμα εργασιών: παύουμε να καταναλώνουμε
    αποτελέσματα και ακυρώνουμε όσα δεν ξεκίνησαν (``cancel_futures``). Οι λίγες
    μεταφορτώσεις που τρέχουν ήδη ολοκληρώνονται στο παρασκήνιο — δεν περιμένουμε.
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

    pool_exec = ThreadPoolExecutor(max_workers=settings.max_workers)
    try:
        futures = [pool_exec.submit(job, row) for row in rows]
        for fut in futures:
            if should_cancel and should_cancel():
                break
            row, outcome = fut.result()
            _persist_outcome(conn, client, settings, row, outcome, stats, pool, progress)
            conn.commit()
    finally:
        # wait=False + cancel_futures: δεν κρεμάμε το UI περιμένοντας ό,τι τρέχει.
        pool_exec.shutdown(wait=False, cancel_futures=True)
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

    if isinstance(outcome, NotAPdf):
        # Δεν είναι σφάλμα: ο πάροχος προσφέρει μόνο online προβολή, όχι PDF.
        repo.mark_viewer_only(conn, client.id, mark)
        stats.viewer_only += 1
        progress(f"  ⧉ {mark}: μόνο online προβολή στον πάροχο")
        return

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
    should_cancel: Callable[[], bool] | None = None,
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
            should_cancel=should_cancel,
        )
    except OperationCancelled:
        # Ο χρήστης ακύρωσε στη μέση της ανακάλυψης — όχι σφάλμα. Ο cursor δεν
        # έχει προχωρήσει για την τρέχουσα κατεύθυνση, οπότε τίποτα δεν χάνεται.
        progress(f"{client.vat}: ακυρώθηκε")
        return stats
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

    if should_cancel and should_cancel():
        progress(f"{client.vat}: ακυρώθηκε")
        return stats

    # Το VIES καλύπτει ό,τι δεν έδωσαν τα παραστατικά ούτε η λίστα πελατών, ώστε
    # τα ονόματα αρχείων να έχουν επωνυμία και όχι σκέτο ΑΦΜ. Μετά από αυτό
    # ξαναγεμίζουμε τα κενά, πριν χτιστούν τα ονόματα των αρχείων.
    if use_vies:
        try:
            if resolve_names_via_vies(conn, client_id=client.id, progress=progress,
                                      should_cancel=should_cancel):
                repo.backfill_issuer_names(conn, client.id)
                conn.commit()
        except OperationCancelled:
            progress(f"{client.vat}: ακυρώθηκε")
            return stats
        except Exception as exc:  # το VIES δεν είναι ποτέ λόγος να χαλάσει η λήψη
            log.warning("VIES: %s", exc)

    if should_cancel and should_cancel():
        progress(f"{client.vat}: ακυρώθηκε")
        return stats

    # Αυτόματη επανάληψη: όσα «κόλλησαν» ως σφάλμα αλλά έχουν σύνδεσμο (π.χ. ο
    # πάροχος ήταν στιγμιαία εκτός) ξαναμπαίνουν στην ουρά και ξαναδοκιμάζονται
    # τώρα — χωρίς να χρειάζεται να κάνει κάτι ο χρήστης.
    requeued = repo.requeue_errors(conn, client.id)
    if requeued:
        conn.commit()
        progress(f"{client.vat}: επανάληψη λήψης για {requeued} με σφάλμα")

    stats.no_url = int(
        conn.execute(
            "SELECT COUNT(*) c FROM documents WHERE client_id=? AND status='no_provider_url'",
            (client.id,),
        ).fetchone()["c"]
    )
    download_pending(conn, client, settings, stats=stats, progress=progress,
                     should_cancel=should_cancel)
    return stats


class AllBrowsersFailed(Exception):
    """Κανένας από τους διαθέσιμους browsers δεν άνοιξε."""


def _open_renderer_with_fallback(
    browsers, browser_idx, *, headed, should_cancel, progress,
):
    """Ανοίγει renderer δοκιμάζοντας τους browsers με τη σειρά (Edge → Chrome).

    Επιστρέφει (renderer, νέος_δείκτης). Αν ο πρώτος δεν ξεκινά («σφάλμα
    browser»), δοκιμάζει τον επόμενο· έτσι ο χρήστης δεν κολλάει επειδή π.χ. ο
    Edge έχει πρόβλημα. Πετά ``HeadlessCancelled`` σε ακύρωση, ή
    ``AllBrowsersFailed`` αν κανένας δεν ανοίξει.
    """
    from .download.headless import HeadlessCancelled, HeadlessError, HeadlessRenderer

    idx = browser_idx
    while idx < len(browsers):
        try:
            renderer = HeadlessRenderer(
                browser=browsers[idx], headed=headed, should_cancel=should_cancel,
            )
            if idx > browser_idx:
                progress(f"  ↻ δοκιμή με {browsers[idx].name}")
            return renderer, idx
        except HeadlessCancelled:
            raise
        except HeadlessError as exc:
            log.warning("Ο browser %s δεν άνοιξε: %s", browsers[idx].name, exc)
            idx += 1
    raise AllBrowsersFailed()


def _render_viewer_batch(
    conn: sqlite3.Connection,
    settings: Settings,
    rows: list[sqlite3.Row],
    *,
    headed: bool,
    patient: bool,
    timeout: float,
    progress: ProgressFn,
    should_cancel: Callable[[], bool] | None,
) -> tuple[int, int, list[sqlite3.Row]]:
    """Αποδίδει μια παρτίδα «μόνο online» **σειριακά, με έναν browser**.

    Επιστρέφει (αποθηκεύτηκαν, σφάλματα, όσα έμειναν κενά/ακυρώθηκαν).

    Σκόπιμα ΕΝΑΣ browser και σειριακά — όχι πολλοί παράλληλοι: κάθε headless
    Chrome/Edge είναι βαρύς (renderer + GPU + utility διεργασίες), και πέντε μαζί
    «πάγωναν» αδύναμα μηχανήματα. Ένας browser σε χαμηλή προτεραιότητα, που
    επαναχρησιμοποιείται σε όλες τις σελίδες, είναι σταθερός και αρκετά γρήγορος.

    Η ακύρωση γίνεται αισθητή σε <0.5s: ελέγχεται πριν από κάθε σελίδα και μέσα
    στην αναμονή απόδοσης (``render_pdf(should_cancel=…)`` -> ``HeadlessCancelled``).
    """
    from .download.headless import (
        HeadlessCancelled,
        HeadlessError,
        HeadlessRenderer,
        find_browsers,
    )

    saved = failed = 0
    remaining: list[sqlite3.Row] = []
    renderer: HeadlessRenderer | None = None
    # Fallback browsers: αν ο πρώτος (Edge) δεν ανοίγει — «σφάλμα browser» —
    # δοκιμάζουμε τον επόμενο (Chrome). Ο δείκτης προχωρά μόνιμα ώστε να μην
    # ξαναδοκιμάζουμε browser που ήδη απέτυχε να ξεκινήσει.
    browsers = find_browsers()
    browser_idx = 0
    cancelled = False
    try:
        for i, row in enumerate(rows):
            label = row["client_label"] or row["client_vat"]
            if cancelled or (should_cancel and should_cancel()):
                cancelled = True
                remaining.append(row)
                continue
            # Ο browser ανοίγει μόλις χρειαστεί (lazily) — αν όλα ακυρωθούν πριν
            # ξεκινήσουμε, δεν ανοίγει καθόλου. Η ίδια η εκκίνηση είναι ακυρώσιμη.
            try:
                if renderer is None:
                    renderer, browser_idx = _open_renderer_with_fallback(
                        browsers, browser_idx, headed=headed,
                        should_cancel=should_cancel, progress=progress,
                    )
                pdf = renderer.render_pdf(
                    row["downloading_invoice_url"], patient=patient,
                    timeout=timeout, should_cancel=should_cancel,
                )
            except HeadlessCancelled:
                cancelled = True
                remaining.append(row)
                continue
            except AllBrowsersFailed:
                # Κανένας browser δεν άνοιξε — δεν έχει νόημα να δοκιμάσουμε τις
                # υπόλοιπες γραμμές. Μένουν «μόνο online».
                failed += 1
                progress(f"  ✗ {label}: σφάλμα browser (δοκιμάστηκαν όλοι)")
                remaining.extend(rows[i + 1:])
                break
            except HeadlessError as exc:
                failed += 1
                log.warning("Render απέτυχε (%s): %s", row["mark"], exc)
                progress(f"  ✗ {label}: σφάλμα browser")
                continue
            if pdf is None:
                remaining.append(row)
                continue
            doc = _doc_from_row(row)
            path = resolve_path(settings.storage_root, row["client_vat"], doc,
                                client_label=row["client_label"])
            size, sha = write_atomic(path, pdf)
            repo.mark_downloaded(
                conn, row["client_id"], row["mark"],
                str(path.relative_to(settings.storage_root)), size, sha,
            )
            conn.commit()
            saved += 1
            progress(f"  ✓ {label}: PDF ({size:,} B)")
    finally:
        if renderer is not None:
            try:
                renderer.close()
            except Exception:  # noqa: BLE001
                pass
    return saved, failed, remaining


def _direct_fetch_batch(
    conn: sqlite3.Connection,
    settings: Settings,
    rows: list[sqlite3.Row],
    *,
    progress: ProgressFn,
    should_cancel: Callable[[], bool] | None,
) -> tuple[int, list[sqlite3.Row]]:
    """Δοκιμάζει **άμεση** λήψη PDF πριν καν ανοίξει browser.

    Κάποιοι πάροχοι που φαίνονται «μόνο online» έχουν στην πραγματικότητα άμεσο
    PDF endpoint — επιβεβαιωμένο στη **Megasoft** (``…/qr?QrCode=…/pdf`` ->
    application/pdf). Το κερδίζουμε εδώ γρήγορα, χωρίς browser. Ό,τι επιστρέφει
    HTML/σφάλμα (etimologiera, Epsilon…) πάει στα browser περάσματα.

    Επιστρέφει (αποθηκεύτηκαν, όσα έμειναν).
    """
    downloader = ProviderDownloader(settings)
    saved = 0
    remaining: list[sqlite3.Row] = []
    try:
        for row in rows:
            if should_cancel and should_cancel():
                remaining.append(row)
                continue
            label = row["client_label"] or row["client_vat"]
            try:
                result = downloader.fetch_pdf(row["downloading_invoice_url"])
            except Exception:  # noqa: BLE001 — HTML/σφάλμα: δοκίμασε browser μετά
                remaining.append(row)
                continue
            doc = _doc_from_row(row)
            path = resolve_path(settings.storage_root, row["client_vat"], doc,
                                client_label=row["client_label"])
            size, sha = write_atomic(path, result.payload)  # type: ignore[attr-defined]
            repo.mark_downloaded(
                conn, row["client_id"], row["mark"],
                str(path.relative_to(settings.storage_root)), size, sha,
            )
            conn.commit()
            saved += 1
            progress(f"  ✓ {label}: PDF άμεσα από τον πάροχο ({size:,} B)")
    finally:
        downloader.close()
    return saved, remaining


def download_viewer_only(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    vats: list[str] | None = None,
    progress: ProgressFn = _noop,
    should_cancel: Callable[[], bool] | None = None,
    headed_fallback: bool = True,
) -> tuple[int, int, int]:
    """Κατεβάζει τα «μόνο online» παραστατικά, σε τρία περάσματα.

    0. **Άμεση λήψη PDF** από τον πάροχο (χωρίς browser): πιάνει τη **Megasoft**,
       που έχει άμεσο ``/pdf`` endpoint παρότι δείχνει σελίδα QR.
    1. **Headless browser** (αόρατο): πιάνει τους παρόχους που στοιχειοθετούν το
       παραστατικό στη σελίδα χωρίς έλεγχο «είστε άνθρωπος» (π.χ. e-timologiera).
    2. **Ορατό (headed) browser** για όσα έμειναν (π.χ. Epsilon πίσω από
       Cloudflare Turnstile): ανοίγει ορατά παράθυρα ώστε ο χρήστης να περάσει ο
       ίδιος τον έλεγχο, και μετά τυπώνουμε τη σελίδα σε PDF. **Δεν παρακάμπτουμε
       κανέναν έλεγχο** — απλώς δεν κρύβουμε τον browser.

    Επιστρέφει (αποθηκεύτηκαν, παραλείφθηκαν, σφάλματα).
    """
    from .download.headless import find_browser

    rows = repo.viewer_only_documents(conn, vats)
    if not rows:
        return 0, 0, 0

    # Πέρασμα 0: άμεση λήψη PDF (Megasoft κ.ά.) — γρήγορο, χωρίς browser.
    saved, remaining = _direct_fetch_batch(
        conn, settings, rows, progress=progress, should_cancel=should_cancel,
    )
    failed = 0
    if not remaining:
        return saved, 0, failed

    # Τα browser περάσματα χρειάζονται Edge/Chrome. Αν λείπει, ό,τι δεν πιάστηκε
    # άμεσα μένει «μόνο online» — δεν είναι σφάλμα.
    if find_browser() is None:
        for row in remaining:
            label = row["client_label"] or row["client_vat"]
            progress(f"  ⧉ {label}: παραμένει μόνο online (χωρίς Edge/Chrome)")
        return saved, len(remaining), failed

    # Πέρασμα 1: headless, σειριακά με έναν browser (σταθερό, χαμηλή προτεραιότητα).
    s1, failed, remaining = _render_viewer_batch(
        conn, settings, remaining, headed=False, patient=False, timeout=30.0,
        progress=progress, should_cancel=should_cancel,
    )
    saved += s1

    # Πέρασμα 2: ορατός headed browser για όσα έμειναν, αν το θέλει ο χρήστης.
    cancelled = bool(should_cancel and should_cancel())
    if headed_fallback and remaining and not cancelled:
        progress(
            f"  ▶ {len(remaining)} παραστατικά ανοίγουν σε ΟΡΑΤΟ browser, ένα-ένα "
            "— μόλις εμφανιστεί το καθένα αποθηκεύεται και ανοίγει το επόμενο."
        )
        # Σειριακά (ένα ορατό παράθυρο): ανοίγει το επόμενο μόλις ολοκληρωθεί το
        # προηγούμενο — πιο ξεκάθαρο από πολλά παράθυρα μαζί.
        s2, f2, remaining = _render_viewer_batch(
            conn, settings, remaining, headed=True, patient=True, timeout=150.0,
            progress=progress, should_cancel=should_cancel,
        )
        saved += s2
        failed += f2

    for row in remaining:
        label = row["client_label"] or row["client_vat"]
        progress(f"  ⧉ {label}: παραμένει μόνο online")
    return saved, len(remaining), failed


def save_online_only_pdf(
    conn: sqlite3.Connection,
    settings: Settings,
    row: sqlite3.Row,
    pdf_bytes: bytes,
) -> tuple[Path, int]:
    """Αρχειοθετεί ένα PDF που κατέβασε ο ίδιος ο χρήστης από τον browser του.

    Για τα «μόνο online» παραστατικά που ο πάροχος δείχνει πίσω από έλεγχο
    ανθρώπου (π.χ. Cloudflare), ο χρήστης ανοίγει τη σελίδα, περνά τον έλεγχο ως
    άνθρωπος και αποθηκεύει/τυπώνει το PDF. Εδώ απλώς παίρνουμε το αρχείο που
    ήδη κατέβασε και το βάζουμε στο σωστό όνομα/φάκελο (το ίδιο σχήμα με την
    αυτόματη λήψη), σημειώνοντάς το ως «Ελήφθη». Καμία επικοινωνία με τον
    πάροχο — δουλεύουμε πάνω σε αρχείο που υπάρχει ήδη στον δίσκο.

    Το `row` προέρχεται από `repo.viewer_only_documents` (έχει client_id/vat/
    label). Επιστρέφει (τελική διαδρομή, μέγεθος). Σφάλμα αν δεν είναι PDF.
    """
    if not pdf_bytes.startswith(b"%PDF"):
        raise ValueError("Το αρχείο δεν είναι PDF")
    doc = _doc_from_row(row)
    path = resolve_path(
        settings.storage_root, row["client_vat"], doc,
        client_label=row["client_label"],
    )
    size, sha = write_atomic(path, pdf_bytes)
    repo.mark_downloaded(
        conn, row["client_id"], row["mark"],
        str(path.relative_to(settings.storage_root)), size, sha,
    )
    conn.commit()
    return path, size

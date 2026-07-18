"""CLI — headless surface για τις Φάσεις 1-3 και debugging της Φάσης 4."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

from . import repo
from .config import load_settings
from . import crypto as crypto_mod
from .crypto import Crypto, SecretRedactingFilter
from .db import init_db
from .models import Client, ClientStatus


class Locked(Exception):
    """Ο φάκελος δεδομένων είναι προστατευμένος και δεν δόθηκε κωδικός."""


def _crypto(settings) -> Crypto:
    """Crypto, ζητώντας τον κύριο κωδικό αν ο φάκελος είναι προστατευμένος.

    Σε scheduled task ή pipeline δεν υπάρχει τερματικό για prompt: εκεί ο
    κωδικός δίνεται με TIMOLOGIO_MASTER_PASSWORD και το getpass δεν καλείται.
    """
    path = settings.enckey_path
    if not crypto_mod.is_protected(path) or os.environ.get("TIMOLOGIO_MASTER_PASSWORD"):
        return Crypto(path)
    if not sys.stdin.isatty():
        raise Locked(
            "Ο φάκελος δεδομένων προστατεύεται με κύριο κωδικό. Ορίστε τον στη "
            "μεταβλητή περιβάλλοντος TIMOLOGIO_MASTER_PASSWORD."
        )
    import getpass

    for attempt in range(3):
        try:
            crypto_mod.unlock(path, getpass.getpass("Κύριος κωδικός: "))
            return Crypto(path)
        except crypto_mod.WrongPassword:
            print(f"Λάθος κωδικός ({attempt + 1}/3).", file=sys.stderr)
    raise Locked("Ο κωδικός δεν δόθηκε σωστά.")


def _setup_logging(verbose: bool) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(SecretRedactingFilter())
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        handlers=[handler],
    )


def _default_dates() -> tuple[str, str]:
    today = date.today()
    return f"01/01/{today.year}", today.strftime("%d/%m/%Y")


def cmd_sync(args: argparse.Namespace) -> int:
    from .backup import create_backup
    from .locking import LockBusy, SyncLock
    from .sync import sync_client

    settings = load_settings()
    lock = SyncLock(settings.data_dir)
    try:
        lock.acquire()
    except LockBusy as exc:
        print(exc.message_el, file=sys.stderr)
        return 1

    try:
        return _run_sync(args, settings, lock)
    finally:
        lock.release()


def _run_sync(args: argparse.Namespace, settings, lock) -> int:
    from .backup import create_backup
    from .sync import sync_client

    create_backup(settings.db_path, reason="sync")
    conn = init_db(settings.db_path)
    crypto = _crypto(settings)

    date_from = args.date_from or _default_dates()[0]
    date_to = args.date_to or _default_dates()[1]

    if args.vat:
        rows = [r for r in repo.list_clients(conn) if r["vat"] == args.vat]
        if not rows:
            print(f"Δεν βρέθηκε πελάτης με ΑΦΜ {args.vat}", file=sys.stderr)
            return 1
    else:
        rows = repo.list_clients(conn, only_ready=True)

    if not rows:
        print("Δεν υπάρχουν πελάτες με κλειδί API. Κάντε πρώτα import.", file=sys.stderr)
        return 1

    run_id = repo.start_run(conn, date_from, date_to, len(rows))
    print(f"Συγχρονισμός {len(rows)} πελατών, {date_from} - {date_to}\n")

    totals = {"found": 0, "pdf": 0, "no_url": 0, "failed": 0, "skipped": 0}
    for row in rows:
        client = repo.get_client(conn, row["vat"], crypto)
        assert client is not None
        if client.status is not ClientStatus.READY:
            print(f"{client.vat} {client.label}: Λείπει κλειδί API — παράλειψη")
            totals["skipped"] += 1
            continue

        print(f"── {client.vat} {client.label}")
        lock.touch()  # μια μεγάλη λήψη δεν πρέπει να θεωρηθεί ορφανή
        stats = sync_client(
            conn,
            client,
            settings,
            date_from=date_from,
            date_to=date_to,
            incremental=not args.full,
            use_vies=not args.no_vies,
            progress=lambda m: print(f"   {m}"),
        )
        totals["found"] += stats.docs_found
        totals["pdf"] += stats.pdfs_ok
        totals["no_url"] += stats.no_url
        totals["failed"] += stats.failed
        repo.log_event(
            conn, run_id, client_vat=client.vat, event="sync",
            detail=f"found={stats.docs_found} pdf={stats.pdfs_ok} failed={stats.failed}",
        )
        conn.commit()

    repo.finish_run(conn, run_id)
    print(
        f"\nΣύνολο: {totals['found']} παραστατικά | {totals['pdf']} PDF | "
        f"{totals['no_url']} χωρίς PDF παρόχου | {totals['failed']} σφάλματα"
    )
    print(f"Αρχεία: {settings.storage_root}")
    return 0


def cmd_add_client(args: argparse.Namespace) -> int:
    """Προσωρινό για Φάση 1 — η Φάση 2 φέρνει το Excel import."""
    settings = load_settings()
    conn = init_db(settings.db_path)
    crypto = _crypto(settings)

    user = os.environ.get("AADE_USER", "")
    key = os.environ.get("AADE_KEY", "")
    if not user or not key:
        print("Ορίστε AADE_USER και AADE_KEY στο περιβάλλον.", file=sys.stderr)
        return 1

    client = Client(vat=args.vat, label=args.label or "", mydata_user=user,
                    mydata_key=key, source_file="cli")
    repo.upsert_client(conn, client, crypto)
    conn.commit()
    print(f"Αποθηκεύτηκε ο πελάτης {args.vat}.")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    from .backup import create_backup
    from .excel import FORMAT_LABELS_EL, build_preview

    settings = load_settings()
    if not args.dry_run:
        create_backup(settings.db_path, reason="import")
    conn = init_db(settings.db_path)
    crypto = _crypto(settings)

    try:
        preview = build_preview(args.file, conn)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Αρχείο : {preview.path.name}")
    print(f"Μορφή  : {FORMAT_LABELS_EL[preview.fmt]}")
    print(f"Σύνοψη : {preview.summary_el()}\n")

    shown = preview.rows if args.all else preview.rows[:15]
    print(f"{'ΑΦΜ':11s} {'Επωνυμία':32s} {'Χρήστης':10s} {'Κλειδί':10s} {'Ενέργεια':11s}")
    print("─" * 84)
    for row in shown:
        d = row.display()
        line = (f"{d['afm']:11s} {d['label'][:32]:32s} {d['user']:10s} "
                f"{d['key']:10s} {d['action']:11s}")
        if d["warnings"]:
            line += f"  ⚠ {d['warnings']}"
        print(line)
    if len(preview.rows) > len(shown):
        print(f"… και άλλοι {len(preview.rows) - len(shown)} (--all για όλους)")

    if args.dry_run:
        print("\n[dry-run] Δεν γράφτηκε τίποτα. Ξανατρέξτε χωρίς --dry-run για εισαγωγή.")
        return 0

    for row in preview.rows:
        repo.upsert_client(conn, row.client, crypto)
    conn.commit()
    print(f"\nΕισήχθησαν {len(preview.rows)} πελάτες στη βάση.")
    print(f"Έτοιμοι για λήψη: {preview.ready}. Χωρίς κλειδί API: {preview.missing_key}.")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    settings = load_settings()
    conn = init_db(settings.db_path)
    rows = repo.list_clients(conn)
    if not rows:
        print("Κανένας πελάτης.")
        return 0
    ready = sum(1 for r in rows if r["status"] == "ready")
    print(f"{len(rows)} πελάτες — {ready} έτοιμοι, {len(rows) - ready} χωρίς κλειδί API\n")
    for r in rows:
        docs = conn.execute(
            "SELECT COUNT(*) c, SUM(status='downloaded') d FROM documents WHERE client_id=?",
            (r["id"],),
        ).fetchone()
        flag = "✓" if r["status"] == "ready" else "—"
        print(f" {flag} {r['vat']:11s} {(r['label'] or '')[:38]:38s} "
              f"{docs['c'] or 0:5d} παρ. / {docs['d'] or 0:5d} PDF")
    return 0


def cmd_names(args: argparse.Namespace) -> int:
    """Συμπληρώνει επωνυμίες από το VIES και μετονομάζει ανάλογα."""
    from .backup import create_backup
    from .sync import resolve_names_via_vies

    settings = load_settings()
    create_backup(settings.db_path, reason="names")
    conn = init_db(settings.db_path)

    repo.seed_suppliers_from_clients(conn)
    for row in repo.list_clients(conn):
        repo.backfill_issuer_names(conn, row["id"])
    conn.commit()

    pending = repo.vats_needing_name(conn)
    if not pending:
        print("Όλα τα ΑΦΜ έχουν επωνυμία.")
        return 0

    print(f"{len(pending)} ΑΦΜ χωρίς επωνυμία. Αναζήτηση στο VIES "
          f"(~1 δευτ./ΑΦΜ, όριο {args.limit})…\n")
    found = resolve_names_via_vies(conn, limit=args.limit, progress=lambda m: print(f"  {m}"))
    for row in repo.list_clients(conn):
        repo.backfill_issuer_names(conn, row["id"])
    conn.commit()

    print(f"\nΒρέθηκαν {found} επωνυμίες.")
    stats = {r["source"]: r["c"] for r in conn.execute(
        "SELECT source, COUNT(*) c FROM suppliers GROUP BY source")}
    print(f"Μητρώο: {stats}")
    print("\nΤρέξτε «timologio rename» για να ενημερωθούν τα ονόματα αρχείων.")
    return 0


def cmd_analyse(args: argparse.Namespace) -> int:
    from .models import CLASSIFICATION_LABELS_EL, Classification
    from .reports import analyse_client

    settings = load_settings()
    conn = init_db(settings.db_path)
    a = analyse_client(conn, args.vat)
    if a is None:
        print(f"Δεν βρέθηκε πελάτης με ΑΦΜ {args.vat}", file=sys.stderr)
        return 1

    def money(v: float) -> str:
        return f"{v:,.2f}".replace(",", "~").replace(".", ",").replace("~", ".")

    print(f"\n{a.label}  ({a.vat})")
    print("─" * 62)
    period = f"{a.first_date} έως {a.last_date}" if a.first_date else "—"
    print(f"  Περίοδος            : {period}")
    print(f"  Παραστατικά         : {a.total}  "
          f"({a.incoming} εισερχ. / {a.outgoing} εκδοθ.)")
    print(f"  Ελήφθησαν PDF       : {a.downloaded}")
    print(f"  Χωρίς PDF παρόχου   : {a.no_provider_url}")
    if a.failed:
        print(f"  Σφάλματα            : {a.failed}")
    print(f"\n  Καθαρή αξία         : {money(a.net_value):>14} €")
    print(f"  ΦΠΑ                 : {money(a.vat_amount):>14} €")
    print(f"  Σύνολο              : {money(a.total_value):>14} €")

    print("\n  Χαρακτηρισμός:")
    print(f"    {CLASSIFICATION_LABELS_EL[Classification.CLASSIFIED]:16s} {a.classified}")
    print(f"    {CLASSIFICATION_LABELS_EL[Classification.UNCLASSIFIED]:16s} {a.unclassified}")
    print(f"    {'Χωρίς στοιχείο E3':16s} {a.unknown_classification}")

    if a.by_type:
        print("\n  Ανά τύπο:")
        for t, c, v in a.by_type[:8]:
            print(f"    {t:8s} {c:5d}  {money(v):>14} €")
    if a.top_suppliers:
        print("\n  Κορυφαίοι προμηθευτές:")
        for name, vat, c, v in a.top_suppliers[:8]:
            print(f"    {name[:34]:34s} {vat:10s} {c:4d}  {money(v):>12} €")
    if a.by_host:
        print("\n  Ανά πάροχο:")
        for h, c in a.by_host[:6]:
            print(f"    {h:36s} {c:4d}")
    print()
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from .reports import export_documents, export_missing_keys, missing_key_clients

    settings = load_settings()
    conn = init_db(settings.db_path)

    if args.kind == "missing-keys":
        rows = missing_key_clients(conn)
        target = Path(args.out) if args.out else settings.data_dir / "πελάτες_χωρίς_κλειδί.csv"
        count = export_missing_keys(conn, target)
        print(f"{count} πελάτες χωρίς κλειδί API -> {target}")
        if rows:
            print("\nΠρώτοι 10:")
            for r in rows[:10]:
                what = "κλειδί API" if r["has_user"] else "χρήστης + κλειδί"
                print(f"  {r['vat']}  {(r['label'] or '')[:40]:40s} λείπει: {what}")
            print("\nΤο κλειδί «Api myData» εκδίδεται ανά υπόχρεο από το taxisnet")
            print("(Ηλεκτρονικά Βιβλία ΑΑΔΕ → Εγγραφή στο myDATA REST API).")
    else:
        target = Path(args.out) if args.out else settings.data_dir / "παραστατικά.csv"
        count = export_documents(conn, target, args.vat)
        print(f"{count} παραστατικά -> {target}")
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    from .backup import create_backup, list_backups, restore

    settings = load_settings()
    if args.restore:
        backups = list_backups(settings.data_dir)
        if not backups:
            print("Δεν υπάρχουν αντίγραφα.", file=sys.stderr)
            return 1
        chosen = Path(args.restore) if args.restore != "latest" else backups[0][0]
        restore(chosen, settings.db_path)
        print(f"Έγινε επαναφορά από: {chosen.name}")
        print("Η προηγούμενη βάση κρατήθηκε ως αντίγραφο «pre-restore».")
        return 0

    if args.list:
        backups = list_backups(settings.data_dir)
        if not backups:
            print("Δεν υπάρχουν αντίγραφα.")
            return 0
        print(f"{len(backups)} αντίγραφα στο {settings.data_dir / 'backups'}:\n")
        for path, when, size in backups:
            print(f"  {when:%d/%m/%Y %H:%M}  {size/1024:8.1f} KB  {path.name}")
        return 0

    path = create_backup(settings.db_path, reason="manual")
    if path is None:
        print("Δεν υπάρχει βάση για αντίγραφο.", file=sys.stderr)
        return 1
    print(f"Αντίγραφο ασφαλείας: {path}")
    return 0


def cmd_rename(args: argparse.Namespace) -> int:
    from .backup import create_backup
    from .sync import rename_existing

    settings = load_settings()
    if not args.dry_run:
        create_backup(settings.db_path, reason="rename")
    conn = init_db(settings.db_path)
    renamed, skipped = rename_existing(
        conn, settings, dry_run=args.dry_run, progress=print
    )
    verb = "θα μετονομαστούν" if args.dry_run else "μετονομάστηκαν"
    print(f"\n{renamed} αρχεία {verb}, {skipped} παραλείφθηκαν.")
    if args.dry_run:
        print("[dry-run] Δεν άλλαξε τίποτα.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="timologio", description="Μαζική λήψη παραστατικών myDATA"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add-client", help="Προσθήκη πελάτη (creds από AADE_USER/AADE_KEY)")
    p_add.add_argument("vat")
    p_add.add_argument("--label", default="")
    p_add.set_defaults(func=cmd_add_client)

    p_imp = sub.add_parser("import", help="Εισαγωγή πελατών από Excel")
    p_imp.add_argument("file", help="Αρχείο .xlsx")
    p_imp.add_argument("--dry-run", action="store_true", dest="dry_run",
                       help="Μόνο preview, χωρίς εγγραφή")
    p_imp.add_argument("--all", action="store_true", help="Εμφάνιση όλων των γραμμών")
    p_imp.set_defaults(func=cmd_import)

    p_list = sub.add_parser("list", help="Λίστα πελατών")
    p_list.set_defaults(func=cmd_list)

    p_sync = sub.add_parser("sync", help="Λήψη παραστατικών")
    p_sync.add_argument("--vat", help="Μόνο αυτός ο πελάτης")
    p_sync.add_argument("--date-from", dest="date_from", help="dd/mm/yyyy")
    p_sync.add_argument("--date-to", dest="date_to", help="dd/mm/yyyy")
    p_sync.add_argument("--full", action="store_true",
                        help="Αγνόησε τους cursors, ξανά από την αρχή")
    p_sync.add_argument("--no-vies", action="store_true", dest="no_vies",
                        help="Χωρίς αναζήτηση επωνυμιών στο VIES")
    p_sync.set_defaults(func=cmd_sync)

    p_names = sub.add_parser("names", help="Συμπλήρωση επωνυμιών από το VIES")
    p_names.add_argument("--limit", type=int, default=200)
    p_names.set_defaults(func=cmd_names)

    p_an = sub.add_parser("analyse", help="Ανάλυση ανά πελάτη")
    p_an.add_argument("vat")
    p_an.set_defaults(func=cmd_analyse)

    p_rep = sub.add_parser("report", help="Εξαγωγή αναφορών σε CSV")
    p_rep.add_argument("kind", choices=["missing-keys", "documents"])
    p_rep.add_argument("--vat", help="Μόνο αυτός ο πελάτης (για documents)")
    p_rep.add_argument("--out", help="Αρχείο εξόδου")
    p_rep.set_defaults(func=cmd_report)

    p_bak = sub.add_parser("backup", help="Αντίγραφα ασφαλείας βάσης")
    p_bak.add_argument("--list", action="store_true", help="Λίστα αντιγράφων")
    p_bak.add_argument("--restore", metavar="ΑΡΧΕΙΟ|latest",
                       help="Επαναφορά από αντίγραφο")
    p_bak.set_defaults(func=cmd_backup)

    p_ren = sub.add_parser("rename", help="Μετονομασία αρχείων στο τρέχον σχήμα")
    p_ren.add_argument("--dry-run", action="store_true", dest="dry_run")
    p_ren.set_defaults(func=cmd_rename)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    try:
        return int(args.func(args))
    except Locked as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Αναφορές προς τον χρήστη.

Δύο πράγματα που ο λογιστής θέλει να δει έξω από την εφαρμογή:
1. ποιοι πελάτες δεν έχουν κλειδί API (για να τα εκδώσει μαζικά)
2. τι κατέβηκε ανά πελάτη
"""

from __future__ import annotations

import csv
import sqlite3
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import coverage
from .models import CLASSIFICATION_LABELS_EL, Classification


#: Έσοδα = ό,τι εξέδωσε ο ίδιος ο πελάτης.
#:
#: ΔΕΝ αρκεί το direction. Τα παραστατικά τύπου 13.x/14.x (λιανικά έξοδα,
#: τιμολόγια αυτοπαράδοσης) τα υποβάλλει ο ΛΗΠΤΗΣ, οπότε εμφανίζονται στα
#: «εκδοθέντα» (RequestTransmittedDocs) ενώ είναι ΕΞΟΔΑ. Μετρημένο σε πραγματικό
#: πελάτη: 24 τέτοια παραστατικά θα κατατάσσονταν λάθος ως έσοδα.
_INCOME = "issuer_vat = :vat"
_EXPENSE = "issuer_vat <> :vat"


@dataclass
class Totals:
    count: int = 0
    net: float = 0.0
    vat: float = 0.0
    gross: float = 0.0


@dataclass
class ClientAnalysis:
    """Σύνοψη ανά πελάτη για το panel ανάλυσης."""

    vat: str
    label: str
    total: int = 0
    downloaded: int = 0
    no_provider_url: int = 0
    viewer_only: int = 0
    failed: int = 0
    pending: int = 0
    incoming: int = 0
    outgoing: int = 0
    classified: int = 0
    unclassified: int = 0
    unknown_classification: int = 0
    net_value: float = 0.0
    vat_amount: float = 0.0
    total_value: float = 0.0
    income: Totals = None  # type: ignore[assignment]
    expense: Totals = None  # type: ignore[assignment]
    first_date: str = ""
    last_date: str = ""
    by_type: list[tuple[str, int, float]] = None  # type: ignore[assignment]
    top_suppliers: list[tuple[str, str, int, float]] = None  # type: ignore[assignment]
    covered: list = None  # type: ignore[assignment]
    gaps: list = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.by_type = self.by_type or []
        self.top_suppliers = self.top_suppliers or []
        self.covered = self.covered or []
        self.gaps = self.gaps or []
        self.income = self.income or Totals()
        self.expense = self.expense or Totals()


def analyse_client(conn: sqlite3.Connection, vat: str) -> ClientAnalysis | None:
    row = conn.execute("SELECT id, vat, label FROM clients WHERE vat=?", (vat,)).fetchone()
    if row is None:
        return None
    cid = row["id"]
    out = ClientAnalysis(vat=row["vat"], label=row["label"] or "")

    totals = conn.execute(
        """SELECT COUNT(*) total,
                  SUM(status='downloaded') downloaded,
                  SUM(status='no_provider_url') no_url,
                  SUM(status='viewer_only') viewer_only,
                  SUM(status IN ('failed_retryable','failed_permanent')) failed,
                  SUM(status='pending') pending,
                  SUM(direction IN ('incoming','both')) incoming,
                  SUM(direction IN ('outgoing','both')) outgoing,
                  SUM(classification='classified') classified,
                  SUM(classification='unclassified') unclassified,
                  SUM(classification='unknown') unknown_cls,
                  COALESCE(SUM(net_value),0) net,
                  COALESCE(SUM(vat_amount),0) vat,
                  COALESCE(SUM(total_value),0) gross,
                  MIN(NULLIF(issue_date,'')) first_date,
                  MAX(NULLIF(issue_date,'')) last_date
           FROM documents WHERE client_id=?""",
        (cid,),
    ).fetchone()

    out.total = totals["total"] or 0
    out.downloaded = totals["downloaded"] or 0
    out.no_provider_url = totals["no_url"] or 0
    out.viewer_only = totals["viewer_only"] or 0
    out.failed = totals["failed"] or 0
    out.pending = totals["pending"] or 0
    out.incoming = totals["incoming"] or 0
    out.outgoing = totals["outgoing"] or 0
    out.classified = totals["classified"] or 0
    out.unclassified = totals["unclassified"] or 0
    out.unknown_classification = totals["unknown_cls"] or 0
    out.net_value = totals["net"] or 0.0
    out.vat_amount = totals["vat"] or 0.0
    out.total_value = totals["gross"] or 0.0
    out.first_date = totals["first_date"] or ""
    out.last_date = totals["last_date"] or ""

    for field, where in (("income", _INCOME), ("expense", _EXPENSE)):
        r = conn.execute(
            f"""SELECT COUNT(*) n, COALESCE(SUM(net_value),0) net,
                       COALESCE(SUM(vat_amount),0) vat, COALESCE(SUM(total_value),0) gross
                FROM documents WHERE client_id = :cid AND {where}""",
            {"cid": cid, "vat": vat},
        ).fetchone()
        setattr(out, field, Totals(r["n"], r["net"], r["vat"], r["gross"]))

    out.by_type = [
        (r["invoice_type"] or "—", r["c"], r["v"] or 0.0)
        for r in conn.execute(
            """SELECT invoice_type, COUNT(*) c, SUM(total_value) v
               FROM documents WHERE client_id=?
               GROUP BY invoice_type ORDER BY c DESC""",
            (cid,),
        )
    ]
    out.top_suppliers = [
        (r["issuer_name"] or "—", r["issuer_vat"] or "", r["c"], r["v"] or 0.0)
        for r in conn.execute(
            """SELECT issuer_name, issuer_vat, COUNT(*) c, SUM(total_value) v
               FROM documents
               WHERE client_id=? AND direction IN ('incoming','both') AND issuer_vat <> ''
               GROUP BY issuer_vat ORDER BY v DESC LIMIT 10""",
            (cid,),
        )
    ]
    out.covered, out.gaps = coverage.summary(conn, cid)
    out.gaps = coverage.gaps_for_client(conn, cid)
    return out


def count_without_pdf(rows: list[sqlite3.Row]) -> int:
    """Πόσα από τα επιλεγμένα δεν έχουν PDF παρόχου αλλά έχουν XML.

    Αυτά ακριβώς είναι που ρωτάμε τον χρήστη αν θέλει μέσα στο ZIP: υπάρχει
    αρχείο να δοθεί, απλώς δεν είναι το PDF που περιμένει.
    """
    return sum(1 for r in rows if not r["local_path"] and r["xml_path"])


def export_zip(
    rows: list[sqlite3.Row],
    storage_root: Path,
    target: Path,
    *,
    include_without_pdf: bool = True,
) -> tuple[int, int]:
    """Πακετάρει τα αρχεία των επιλεγμένων παραστατικών σε ZIP.

    Επιστρέφει (όσα μπήκαν, όσα δεν μπήκαν). Τα αρχεία μπαίνουν **χύμα**,
    χωρίς υποφακέλους: το όνομα κάθε αρχείου περιέχει ήδη προμηθευτή, ημερομηνία
    και αξία, οπότε μια δομή έτος/μήνα απλώς θα πρόσθετε κλικ στον παραλήπτη.
    Σε σύγκρουση ονόματος προστίθεται μετρητής, ώστε να μη χαθεί αρχείο σιωπηλά.

    Με `include_without_pdf=False` μπαίνουν μόνο τα PDF· τα παραστατικά που
    έχουν μόνο XML μένουν έξω.
    """
    added = missing = 0
    used: set[str] = set()
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            relative = row["local_path"] or (
                row["xml_path"] if include_without_pdf else ""
            )
            if not relative:
                missing += 1
                continue
            source = storage_root / relative
            if not source.exists():
                missing += 1
                continue

            name = Path(relative).name
            if name in used:
                stem, suffix = Path(name).stem, Path(name).suffix
                counter = 2
                while f"{stem} ({counter}){suffix}" in used:
                    counter += 1
                name = f"{stem} ({counter}){suffix}"
            used.add(name)
            zf.write(source, name)
            added += 1
    return added, missing


def suppliers_of(conn: sqlite3.Connection, vat: str) -> list[tuple[str, str, int]]:
    """(ΑΦΜ, επωνυμία, πλήθος) των αντισυμβαλλομένων ενός πελάτη.

    Τροφοδοτεί το φίλτρο «ανά προμηθευτή» στον πίνακα παραστατικών.
    """
    return [
        (r["v"], r["n"] or "", r["c"])
        for r in conn.execute(
            """SELECT CASE WHEN d.issuer_vat <> c.vat AND d.issuer_vat <> ''
                           THEN d.issuer_vat ELSE d.counter_vat END AS v,
                      CASE WHEN d.issuer_vat <> c.vat AND d.issuer_vat <> ''
                           THEN d.issuer_name ELSE d.counter_name END AS n,
                      COUNT(*) c
               FROM documents d JOIN clients c ON c.id = d.client_id
               WHERE c.vat = ?
               GROUP BY v HAVING v <> '' ORDER BY c DESC""",
            (vat,),
        )
    ]


def invoice_types_of(conn: sqlite3.Connection, vat: str) -> list[tuple[str, int]]:
    return [
        (r["t"], r["c"])
        for r in conn.execute(
            """SELECT d.invoice_type t, COUNT(*) c
               FROM documents d JOIN clients c ON c.id = d.client_id
               WHERE c.vat = ? AND d.invoice_type <> ''
               GROUP BY t ORDER BY t""",
            (vat,),
        )
    ]


#: Τα κλειδιά αντιστοιχούν στα πλακίδια της ανάλυσης, ώστε ένα κλικ πάνω τους να
#: ανοίγει ακριβώς αυτά που μετρήθηκαν.
DOC_FILTERS: dict[str, str] = {
    "all": "",
    "downloaded": "d.status='downloaded'",
    "no_provider_url": "d.status='no_provider_url'",
    "viewer_only": "d.status='viewer_only'",
    "failed": "d.status IN ('failed_retryable','failed_permanent')",
    "pending": "d.status='pending'",
    "unclassified": "d.classification='unclassified'",
    "classified": "d.classification='classified'",
    "unknown_cls": "d.classification='unknown'",
    "income": "d.issuer_vat = c.vat",
    "expense": "d.issuer_vat <> c.vat",
}


def documents_for(
    conn: sqlite3.Connection,
    vat: str,
    filter_key: str = "all",
    *,
    extra_filters: Sequence[str] = (),
    supplier_vat: str = "",
    invoice_type: str = "",
    date_from: str = "",
    date_to: str = "",
) -> list[sqlite3.Row]:
    """Τα παραστατικά ενός πελάτη, προαιρετικά φιλτραρισμένα.

    Τα φίλτρα συνδυάζονται με ΚΑΙ: το `filter_key` και όσα δοθούν στο
    `extra_filters` ισχύουν ταυτόχρονα, ώστε να μπορεί κανείς να ζητήσει π.χ.
    «έξοδα ΚΑΙ ελήφθησαν PDF» — τρεις ανεξάρτητοι άξονες, όχι ένας κατάλογος
    αμοιβαία αποκλειόμενων επιλογών.
    """
    clauses = ["c.vat = :vat"]
    for key in (filter_key, *extra_filters):
        clause = DOC_FILTERS.get(key or "all", "")
        if clause:
            clauses.append(clause)
    params: dict[str, object] = {"vat": vat}

    if supplier_vat:
        # Ο «άλλος» είναι ο εκδότης στα έξοδα και ο λήπτης στα έσοδα.
        clauses.append(
            "(CASE WHEN d.issuer_vat <> c.vat AND d.issuer_vat <> ''"
            " THEN d.issuer_vat ELSE d.counter_vat END) = :supplier"
        )
        params["supplier"] = supplier_vat
    if invoice_type:
        clauses.append("d.invoice_type = :itype")
        params["itype"] = invoice_type
    if date_from:
        clauses.append("d.issue_date >= :dfrom")
        params["dfrom"] = coverage.to_iso(date_from)
    if date_to:
        clauses.append("d.issue_date <= :dto")
        params["dto"] = coverage.to_iso(date_to)

    return list(
        conn.execute(
            f"""SELECT d.*, c.vat AS client_vat, c.label AS client_label
                FROM documents d
                JOIN clients c ON c.id = d.client_id
                WHERE {' AND '.join(clauses)}
                ORDER BY d.issue_date DESC, d.mark DESC""",
            params,
        )
    )


def documents_by_marks(
    conn: sqlite3.Connection, vat: str, marks: Sequence[str]
) -> list[sqlite3.Row]:
    """Τα παραστατικά ενός πελάτη με τα δοσμένα MARK — ανεξάρτητα από φίλτρα.

    Χρειάζεται ώστε οι μαζικές ενέργειες (εξαγωγή ZIP, εκτύπωση) να δουλεύουν σε
    ό,τι έχει επιλέξει ο χρήστης, ακόμη κι αν ένα ενεργό φίλτρο (αναζήτηση,
    είδος…) κρύβει κάποια από αυτά τη στιγμή της ενέργειας. Περιλαμβάνει
    `client_label` για τη ροή αποθήκευσης «μόνο online».
    """
    marks = list(marks)
    if not marks:
        return []
    placeholders = ",".join("?" * len(marks))
    return list(
        conn.execute(
            f"""SELECT d.*, c.vat AS client_vat, c.label AS client_label
                FROM documents d JOIN clients c ON c.id = d.client_id
                WHERE c.vat = ? AND d.mark IN ({placeholders})
                ORDER BY d.issue_date DESC, d.mark DESC""",
            [vat, *marks],
        )
    )


def missing_key_clients(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Το ανοιχτό θέμα: πελάτες χωρίς κλειδί myDATA API.

    Μετρημένα, τα δύο τρίτα περίπου των «Κωδικών Υπόχρεων». Το κλειδί εκδίδεται
    ανά υπόχρεο από το taxisnet — η εφαρμογή δεν μπορεί να το δημιουργήσει,
    οπότε το καλύτερο που κάνει είναι να βγάλει καθαρή λίστα εργασίας.
    """
    return list(
        conn.execute(
            """SELECT vat, label, office_code, source_file,
                      (mydata_user_enc <> '') AS has_user
               FROM clients WHERE status <> 'ready' ORDER BY label, vat"""
        )
    )


def export_missing_keys(conn: sqlite3.Connection, path: Path) -> int:
    """Γράφει CSV με τους πελάτες που δεν μπορούν να κατεβάσουν."""
    rows = missing_key_clients(conn)
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig ώστε το Excel να δει σωστά τα ελληνικά με διπλό κλικ.
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(["ΑΦΜ", "Επωνυμία", "Κωδικός", "Έχει όνομα χρήστη",
                         "Τι λείπει", "Αρχείο προέλευσης"])
        for row in rows:
            writer.writerow([
                row["vat"],
                row["label"],
                row["office_code"],
                "ΝΑΙ" if row["has_user"] else "ΟΧΙ",
                "Κλειδί API (Api myData)" if row["has_user"]
                else "Όνομα χρήστη και κλειδί API",
                row["source_file"],
            ])
    return len(rows)


def export_documents(conn: sqlite3.Connection, path: Path, vat: str | None = None) -> int:
    """Αναλυτική κατάσταση παραστατικών σε CSV."""
    sql = """SELECT c.vat client_vat, c.label client_label, d.*
             FROM documents d JOIN clients c ON c.id = d.client_id"""
    params: tuple = ()
    if vat:
        sql += " WHERE c.vat = ?"
        params = (vat,)
    sql += " ORDER BY c.vat, d.issue_date, d.mark"

    rows = list(conn.execute(sql, params))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow([
            "ΑΦΜ Πελάτη", "Πελάτης", "MARK", "Κατεύθυνση", "Τύπος", "Ημ. Έκδοσης",
            "Σειρά", "ΑΑ", "ΑΦΜ Εκδότη", "Εκδότης", "Καθαρή Αξία", "ΦΠΑ",
            "Σύνολο", "Χαρακτηρισμός", "Κατάσταση", "Αρχείο",
        ])
        for r in rows:
            cls = Classification(r["classification"] or "unknown")
            writer.writerow([
                r["client_vat"], r["client_label"], r["mark"], r["direction"],
                r["invoice_type"], r["issue_date"], r["series"], r["aa"],
                r["issuer_vat"], r["issuer_name"],
                f"{r['net_value']:.2f}".replace(".", ","),
                f"{r['vat_amount']:.2f}".replace(".", ","),
                f"{r['total_value']:.2f}".replace(".", ","),
                CLASSIFICATION_LABELS_EL[cls],
                r["status"], r["local_path"] or r["xml_path"],
            ])
    return len(rows)

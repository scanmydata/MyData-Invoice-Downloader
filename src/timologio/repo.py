"""Πρόσβαση στη βάση.

Στη Φάση 4 όλα τα writes περνούν από το orchestrator thread· τα download
workers επιστρέφουν αποτελέσματα και δεν αγγίζουν ποτέ sqlite.
"""

from __future__ import annotations

import sqlite3

from .crypto import Crypto
from .models import Classification, Client, ClientStatus, Direction, DocStatus, Document


def upsert_client(conn: sqlite3.Connection, client: Client, crypto: Crypto) -> int:
    """Εισάγει/ενημερώνει πελάτη με ΑΦΜ ως κλειδί.

    Τα CASE guards είναι η άμυνα για το Sheet (2) του Κωδικοί_Υπόχρεων.xlsx:
    έχει 43 ΑΦΜ χωρίς καμία στήλη myDATA. Χωρίς αυτά, μια εισαγωγή τέτοιου
    φύλλου θα έσβηνε κλειδιά που ήδη έχουμε. Κενή τιμή δεν σβήνει ποτέ
    αποθηκευμένη.
    """
    user_enc = crypto.enc(client.mydata_user) if client.mydata_user else ""
    key_enc = crypto.enc(client.mydata_key) if client.mydata_key else ""
    status = (
        ClientStatus.READY
        if (client.mydata_user and client.mydata_key)
        else ClientStatus.MISSING_KEY
    )

    conn.execute(
        """
        INSERT INTO clients(vat, label, office_code, mydata_user_enc, mydata_key_enc,
                            status, source_file)
        VALUES(:vat, :label, :office_code, :user_enc, :key_enc, :status, :source_file)
        ON CONFLICT(vat) DO UPDATE SET
          label = CASE WHEN excluded.label <> '' THEN excluded.label ELSE clients.label END,
          office_code = CASE WHEN excluded.office_code <> '' THEN excluded.office_code
                             ELSE clients.office_code END,
          mydata_user_enc = CASE WHEN :has_user THEN excluded.mydata_user_enc
                                 ELSE clients.mydata_user_enc END,
          mydata_key_enc  = CASE WHEN :has_key  THEN excluded.mydata_key_enc
                                 ELSE clients.mydata_key_enc END,
          source_file = CASE WHEN excluded.source_file <> '' THEN excluded.source_file
                             ELSE clients.source_file END,
          updated_at = datetime('now')
        """,
        {
            "vat": client.vat,
            "label": client.label,
            "office_code": client.office_code,
            "user_enc": user_enc,
            "key_enc": key_enc,
            "status": status.value,
            "source_file": client.source_file,
            "has_user": 1 if client.mydata_user else 0,
            "has_key": 1 if client.mydata_key else 0,
        },
    )
    # Το status ξαναϋπολογίζεται από ό,τι όντως αποθηκεύτηκε (μπορεί το
    # υπάρχον κλειδί να επέζησε ενός κενού import).
    conn.execute(
        """
        UPDATE clients SET status = CASE
            WHEN status = 'disabled' THEN 'disabled'
            WHEN mydata_user_enc <> '' AND mydata_key_enc <> '' THEN 'ready'
            ELSE 'missing_key' END
        WHERE vat = ?
        """,
        (client.vat,),
    )
    row = conn.execute("SELECT id FROM clients WHERE vat = ?", (client.vat,)).fetchone()
    return int(row["id"])


def get_client(conn: sqlite3.Connection, vat: str, crypto: Crypto) -> Client | None:
    row = conn.execute("SELECT * FROM clients WHERE vat = ?", (vat,)).fetchone()
    if row is None:
        return None
    return Client(
        id=row["id"],
        vat=row["vat"],
        label=row["label"],
        office_code=row["office_code"],
        mydata_user=crypto.dec(row["mydata_user_enc"]),
        mydata_key=crypto.dec(row["mydata_key_enc"]),
        status=ClientStatus(row["status"]),
        last_mark_incoming=row["last_mark_incoming"],
        last_mark_outgoing=row["last_mark_outgoing"],
        source_file=row["source_file"],
    )


def delete_clients(conn: sqlite3.Connection, vats: list[str]) -> int:
    """Διαγράφει πελάτες και ό,τι κρέμεται από αυτούς.

    Τα παραστατικά και η κάλυψη φεύγουν μέσω ON DELETE CASCADE. Τα αρχεία στον
    δίσκο ΔΕΝ διαγράφονται εδώ — αυτό το αποφασίζει ρητά ο χρήστης, γιατί είναι
    μη αναστρέψιμο και τα PDF μπορεί να χρειάζονται για έλεγχο.
    """
    if not vats:
        return 0
    placeholders = ",".join("?" * len(vats))
    cur = conn.execute(f"DELETE FROM clients WHERE vat IN ({placeholders})", vats)
    return cur.rowcount or 0


def wipe_documents(conn: sqlite3.Connection, vats: list[str] | None = None) -> int:
    """Σβήνει τα ληφθέντα δεδομένα, κρατώντας τους πελάτες και τα κλειδιά.

    Μηδενίζει και τους cursors και την κάλυψη: αλλιώς η επόμενη λήψη θα νόμιζε
    ότι τα έχει ήδη κατεβάσει και δεν θα ξαναέφερνε τίποτα.
    """
    if vats:
        placeholders = ",".join("?" * len(vats))
        where = f"client_id IN (SELECT id FROM clients WHERE vat IN ({placeholders}))"
        params: list = list(vats)
    else:
        where, params = "1=1", []

    cur = conn.execute(f"DELETE FROM documents WHERE {where}", params)
    conn.execute(f"DELETE FROM coverage WHERE {where}", params)
    if vats:
        placeholders = ",".join("?" * len(vats))
        conn.execute(
            f"""UPDATE clients SET last_mark_incoming='0', last_mark_outgoing='0'
                WHERE vat IN ({placeholders})""",
            vats,
        )
    else:
        conn.execute("UPDATE clients SET last_mark_incoming='0', last_mark_outgoing='0'")
    return cur.rowcount or 0


def list_clients(conn: sqlite3.Connection, only_ready: bool = False) -> list[sqlite3.Row]:
    sql = "SELECT * FROM clients"
    if only_ready:
        sql += " WHERE status = 'ready'"
    return list(conn.execute(sql + " ORDER BY vat"))


def upsert_document(conn: sqlite3.Connection, client_id: int, doc: Document) -> None:
    """Μία εγγραφή ανά MARK.

    Αν το ίδιο MARK έρθει και από RequestDocs και από RequestTransmittedDocs
    (συμβαίνει στην αυτοτιμολόγηση), δεν φτιάχνουμε δεύτερη γραμμή ούτε
    ξανακατεβάζουμε — απλώς σημειώνουμε direction='both'.
    """
    status = DocStatus.PENDING if doc.downloading_invoice_url else DocStatus.NO_PROVIDER_URL
    conn.execute(
        """
        INSERT INTO documents(
            client_id, mark, direction, invoice_type, issuer_vat, issuer_name,
            counter_vat, counter_name, series, aa, issue_date,
            net_value, vat_amount, total_value,
            downloading_invoice_url, provider_host, status)
        VALUES(:client_id, :mark, :direction, :invoice_type, :issuer_vat, :issuer_name,
               :counter_vat, :counter_name, :series, :aa, :issue_date,
               :net_value, :vat_amount, :total_value,
               :url, :host, :status)
        ON CONFLICT(client_id, mark) DO UPDATE SET
          direction = CASE WHEN documents.direction <> excluded.direction
                           THEN 'both' ELSE documents.direction END,
          downloading_invoice_url = CASE WHEN excluded.downloading_invoice_url <> ''
                                         THEN excluded.downloading_invoice_url
                                         ELSE documents.downloading_invoice_url END,
          provider_host = CASE WHEN excluded.provider_host <> ''
                               THEN excluded.provider_host ELSE documents.provider_host END,
          issuer_name = CASE WHEN excluded.issuer_name <> ''
                             THEN excluded.issuer_name ELSE documents.issuer_name END,
          updated_at = datetime('now')
        """,
        {
            "client_id": client_id,
            "mark": doc.mark,
            "direction": doc.direction.value,
            "invoice_type": doc.invoice_type,
            "issuer_vat": doc.issuer_vat,
            "issuer_name": doc.issuer_name,
            "counter_vat": doc.counter_vat,
            "counter_name": doc.counter_name,
            "series": doc.series,
            "aa": doc.aa,
            "issue_date": doc.issue_date,
            "net_value": doc.net_value,
            "vat_amount": doc.vat_amount,
            "total_value": doc.total_value,
            "url": doc.downloading_invoice_url,
            "host": doc.provider_host,
            "status": status.value,
        },
    )


def set_classifications(
    conn: sqlite3.Connection, client_id: int, mapping: dict[str, Classification]
) -> int:
    """Γράφει τον χαρακτηρισμό για όσα MARK έχουν εγγραφή E3.

    Όσα λείπουν μένουν 'unknown' — δεν υπόκεινται σε χαρακτηρισμό εξόδων και
    δεν πρέπει να εμφανίζονται ως «αχαρακτήριστα».
    """
    if not mapping:
        return 0
    conn.executemany(
        """UPDATE documents SET classification=?, updated_at=datetime('now')
           WHERE client_id=? AND mark=?""",
        [(status.value, client_id, mark) for mark, status in mapping.items()],
    )
    return len(mapping)


#: Ιεραρχία αξιοπιστίας πηγών επωνυμίας.
#:
#: Ίδια λογική με το ScanmyData_private/vat_name_cache.py:60-67 (client_db 3 >
#: vies 2 > scrape 1): η επωνυμία που έχει καταχωρήσει ο λογιστής για τον πελάτη
#: του υπερισχύει του επίσημου μητρώου, και το επίσημο μητρώο υπερισχύει του
#: ονόματος που τυχαίνει να γράφει το παραστατικό.
_SOURCE_RANK = {"invoice": 0, "vies": 1, "client": 2, "manual": 3}


def upsert_supplier(
    conn: sqlite3.Connection, vat: str, name: str, source: str = "invoice"
) -> None:
    """Καταχωρεί επωνυμία, χωρίς να υποβαθμίζει καλύτερη πηγή.

    Μια χειροκίνητη διόρθωση δεν πρέπει να σβήνεται από το επόμενο sync, γι'
    αυτό η εγγραφή γίνεται μόνο αν η νέα πηγή είναι ίση ή καλύτερη.
    """
    if not vat or not name.strip():
        return
    rank = _SOURCE_RANK.get(source, 0)
    conn.execute(
        """INSERT INTO suppliers(vat, name, source) VALUES(:vat, :name, :source)
           ON CONFLICT(vat) DO UPDATE SET
             name       = excluded.name,
             source     = excluded.source,
             updated_at = datetime('now')
           WHERE :rank >= CASE suppliers.source
                            WHEN 'manual'  THEN 3
                            WHEN 'client'  THEN 2
                            WHEN 'vies'    THEN 1
                            ELSE 0 END""",
        {"vat": vat, "name": name.strip(), "source": source, "rank": rank},
    )


def supplier_names(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["vat"]: r["name"] for r in conn.execute("SELECT vat, name FROM suppliers")}


def learn_supplier_names(conn: sqlite3.Connection, docs: list[Document]) -> int:
    """Μαθαίνει επωνυμίες από όσα παραστατικά τις έχουν."""
    learned = 0
    for doc in docs:
        for vat, name in ((doc.issuer_vat, doc.issuer_name),
                          (doc.counter_vat, doc.counter_name)):
            if vat and name.strip():
                upsert_supplier(conn, vat, name, "invoice")
                learned += 1
    return learned


def seed_suppliers_from_clients(conn: sqlite3.Connection) -> int:
    """Οι δικοί μας πελάτες είναι συχνά και αντισυμβαλλόμενοι μεταξύ τους.

    Το Excel μας δίνει 153 ζεύγη ΑΦΜ/επωνυμία δωρεάν.
    """
    rows = conn.execute("SELECT vat, label FROM clients WHERE label <> ''").fetchall()
    for row in rows:
        upsert_supplier(conn, row["vat"], row["label"], "client")
    return len(rows)


def vats_needing_name(conn: sqlite3.Connection, client_id: int | None = None) -> list[str]:
    """ΑΦΜ που εμφανίζονται σε παραστατικά αλλά δεν έχουν επωνυμία πουθενά.

    Εξαιρούνται όσα έχουν ήδη ρωτηθεί ανεπιτυχώς στο VIES.
    """
    sql = """
        SELECT DISTINCT vat FROM (
            SELECT issuer_vat AS vat FROM documents
             WHERE issuer_vat <> '' {where_issuer}
            UNION
            SELECT counter_vat AS vat FROM documents
             WHERE counter_vat <> '' {where_counter}
        )
        WHERE vat NOT IN (SELECT vat FROM suppliers)
          AND vat NOT IN (SELECT vat FROM vies_misses)
    """
    params: list = []
    if client_id is None:
        sql = sql.format(where_issuer="", where_counter="")
    else:
        sql = sql.format(where_issuer="AND client_id = ?", where_counter="AND client_id = ?")
        params = [client_id, client_id]
    return [r["vat"] for r in conn.execute(sql, params)]


def record_vies_miss(conn: sqlite3.Connection, vat: str) -> None:
    conn.execute(
        "INSERT INTO vies_misses(vat) VALUES(?) ON CONFLICT(vat) DO NOTHING", (vat,)
    )


def backfill_issuer_names(conn: sqlite3.Connection, client_id: int) -> int:
    """Συμπληρώνει επωνυμίες που έλειπαν, από το μητρώο."""
    cur = conn.execute(
        """UPDATE documents SET issuer_name = (
               SELECT name FROM suppliers WHERE suppliers.vat = documents.issuer_vat)
           WHERE client_id = ? AND issuer_name = '' AND issuer_vat <> ''
             AND EXISTS (SELECT 1 FROM suppliers WHERE suppliers.vat = documents.issuer_vat)""",
        (client_id,),
    )
    cur2 = conn.execute(
        """UPDATE documents SET counter_name = (
               SELECT name FROM suppliers WHERE suppliers.vat = documents.counter_vat)
           WHERE client_id = ? AND counter_name = '' AND counter_vat <> ''
             AND EXISTS (SELECT 1 FROM suppliers WHERE suppliers.vat = documents.counter_vat)""",
        (client_id,),
    )
    return (cur.rowcount or 0) + (cur2.rowcount or 0)


def mark_downloaded(
    conn: sqlite3.Connection, client_id: int, mark: str, path: str, size: int, sha: str
) -> None:
    conn.execute(
        """UPDATE documents SET status='downloaded', local_path=?, file_bytes=?,
           file_sha256=?, error_text='', updated_at=datetime('now')
           WHERE client_id=? AND mark=?""",
        (path, size, sha, client_id, mark),
    )


def mark_xml_saved(conn: sqlite3.Connection, client_id: int, mark: str, path: str) -> None:
    conn.execute(
        """UPDATE documents SET status='no_provider_url', xml_path=?,
           updated_at=datetime('now') WHERE client_id=? AND mark=?""",
        (path, client_id, mark),
    )


def mark_failed(
    conn: sqlite3.Connection,
    client_id: int,
    mark: str,
    error: str,
    *,
    retryable: bool,
    next_retry_at: str = "",
) -> None:
    status = DocStatus.FAILED_RETRYABLE if retryable else DocStatus.FAILED_PERMANENT
    conn.execute(
        """UPDATE documents SET status=?, error_text=?, retry_count=retry_count+1,
           next_retry_at=?, updated_at=datetime('now')
           WHERE client_id=? AND mark=?""",
        (status.value, error[:500], next_retry_at, client_id, mark),
    )


def advance_cursor(
    conn: sqlite3.Connection, client_id: int, direction: Direction, mark: str
) -> None:
    """Προχωράει τον cursor — ΜΟΝΟ μετά από καθαρό τερματισμό του discovery.

    Αν ένα 403 κόψει τη ροή στη μέση και προχωρήσουμε τον cursor, η ουρά που
    δεν προλάβαμε να δούμε χάνεται οριστικά.
    """
    column = (
        "last_mark_incoming" if direction is Direction.INCOMING else "last_mark_outgoing"
    )
    conn.execute(
        f"""UPDATE clients SET {column}=?, updated_at=datetime('now')
            WHERE id=? AND CAST(? AS INTEGER) > CAST({column} AS INTEGER)""",
        (mark, client_id, mark),
    )


def pending_documents(conn: sqlite3.Connection, client_id: int) -> list[sqlite3.Row]:
    """Ό,τι αξίζει προσπάθεια τώρα: νέα + retryable που ωρίμασαν."""
    return list(
        conn.execute(
            """SELECT * FROM documents
               WHERE client_id=? AND downloading_invoice_url <> ''
                 AND (status='pending'
                      OR (status='failed_retryable'
                          AND (next_retry_at='' OR next_retry_at <= datetime('now'))))
               ORDER BY issue_date, mark""",
            (client_id,),
        )
    )


def start_run(conn: sqlite3.Connection, date_from: str, date_to: str, clients_total: int) -> int:
    cur = conn.execute(
        "INSERT INTO runs(date_from, date_to, clients_total) VALUES(?,?,?)",
        (date_from, date_to, clients_total),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def finish_run(conn: sqlite3.Connection, run_id: int, status: str = "completed") -> None:
    conn.execute(
        "UPDATE runs SET finished_at=datetime('now'), status=? WHERE id=?", (status, run_id)
    )
    conn.commit()


def log_event(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    client_vat: str = "",
    mark: str = "",
    level: str = "info",
    event: str = "",
    detail: str = "",
) -> None:
    conn.execute(
        """INSERT INTO run_log(run_id, client_vat, mark, level, event, detail)
           VALUES(?,?,?,?,?,?)""",
        (run_id, client_vat, mark, level, event, detail[:1000]),
    )

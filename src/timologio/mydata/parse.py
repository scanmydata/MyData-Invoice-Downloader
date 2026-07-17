"""Parsing των XML απαντήσεων myDATA.

Διαφορά από το fetch.py: εκείνο σπάει κάθε παραστατικό σε μία γραμμή ανά
κατηγορία ΦΠΑ (fetch.py:189-211) γιατί χτίζει λογιστική αναφορά. Εδώ θέλουμε
**μία εγγραφή ανά MARK** — ένα MARK, ένα αρχείο.
"""

from __future__ import annotations

from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from ..config import NS
from ..models import Direction, Document


def _strip(value: object) -> str:
    return str(value).strip() if value else ""


def _local(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def find_by_localnames(elem: ET.Element | None, names: set[str]) -> str:
    """Fallback αναζήτηση αγνοώντας namespace (fetch.py:22-32).

    Χρειάζεται γιατί κατά καιρούς η ΑΑΔΕ επιστρέφει στοιχεία χωρίς ή με άλλο
    namespace prefix.
    """
    if elem is None:
        return ""
    for sub in elem.iter():
        if _local(sub.tag) in names:
            text = _strip(sub.text)
            if text:
                return text
    return ""


def _to_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        try:
            return float(str(value).strip().replace(",", "."))
        except (TypeError, ValueError):
            return 0.0


def _party(invoice: ET.Element, which: str) -> tuple[str, str]:
    node = invoice.find(f"ns:{which}", NS)
    if node is None:
        return "", ""
    vat = _strip(node.findtext("ns:vatNumber", "", NS)) or find_by_localnames(
        node, {"vatNumber", "VATNumber"}
    )
    name = _strip(node.findtext("ns:name", "", NS)) or find_by_localnames(
        node, {"name", "companyName"}
    )
    return vat, name


def extract_cursors(root: ET.Element) -> dict[str, str]:
    """Pagination cursors (port του fetch.py:86-106).

    Η τεκμηρίωση αναφέρει nextPartitionKey/nextRowKey, αλλά στην πράξη κάποια
    περιβάλλοντα γυρίζουν legacy nextPartitionToken — υποστηρίζουμε και τα δύο.
    """
    cursors = {"nextPartitionKey": "", "nextRowKey": "", "nextPartitionToken": ""}
    for elem in root.iter():
        name = _local(elem.tag)
        text = _strip(elem.text)
        if text and name in cursors and not cursors[name]:
            cursors[name] = text
    return cursors


def parse_invoice(invoice: ET.Element, direction: Direction) -> Document:
    header = invoice.find("ns:invoiceHeader", NS)

    invoice_type = ""
    if header is not None:
        invoice_type = _strip(header.findtext("ns:invoiceType", "", NS))
    if not invoice_type:
        invoice_type = find_by_localnames(invoice, {"invoiceType", "InvoiceType"})

    issuer_vat, issuer_name = _party(invoice, "issuer")
    counter_vat, counter_name = _party(invoice, "counterpart")

    net = vat = total = 0.0
    summary = invoice.find("ns:invoiceSummary", NS)
    if summary is not None:
        net = _to_float(summary.findtext("ns:totalNetValue", "0", NS))
        vat = _to_float(summary.findtext("ns:totalVatAmount", "0", NS))
        total = _to_float(summary.findtext("ns:totalGrossValue", "0", NS)) or round(
            net + vat, 2
        )

    url = _strip(invoice.findtext("ns:downloadingInvoiceUrl", "", NS))
    if not url:
        url = find_by_localnames(invoice, {"downloadingInvoiceUrl"})

    doc = Document(
        mark=_strip(invoice.findtext("ns:mark", "", NS)),
        direction=direction,
        invoice_type=invoice_type,
        issuer_vat=issuer_vat,
        issuer_name=issuer_name,
        counter_vat=counter_vat,
        counter_name=counter_name,
        series=_strip(header.findtext("ns:series", "", NS)) if header is not None else "",
        aa=_strip(header.findtext("ns:aa", "", NS)) if header is not None else "",
        issue_date=iso_date(
            _strip(header.findtext("ns:issueDate", "", NS)) if header is not None else ""
        ),
        net_value=round(net, 2),
        vat_amount=round(vat, 2),
        total_value=round(total, 2),
        downloading_invoice_url=url,
        provider_host=urlsplit(url).netloc if url else "",
    )
    if not url:
        # Χωρίς PDF παρόχου κρατάμε το raw XML — έχει issuer, γραμμές, σύνολα.
        doc.xml_blob = ET.tostring(invoice, encoding="utf-8")
    return doc


def iso_date(value: str) -> str:
    """myDATA -> ISO yyyy-mm-dd, ώστε να ταξινομείται σωστά ως TEXT."""
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) >= 10 and value[4] == "-" and value[7] == "-":
        return value[:10]
    if "/" in value:
        parts = value.split("/")
        if len(parts) == 3:
            d, m, y = (p.strip() for p in parts)
            if len(y) == 4:
                return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    return value


def parse_documents(payload: bytes, direction: Direction) -> tuple[list[Document], dict[str, str]]:
    root = ET.fromstring(payload)
    docs = [parse_invoice(inv, direction) for inv in root.findall(".//ns:invoice", NS)]
    return docs, extract_cursors(root)

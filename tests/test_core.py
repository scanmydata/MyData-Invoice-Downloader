"""Tests πυρήνα — χωρίς δίκτυο."""

from __future__ import annotations

from pathlib import Path

import pytest

from timologio.config import load_settings
from timologio.crypto import Crypto, SecretRedactingFilter
from timologio.download import is_complete_pdf, pdf_url, sanitize, target_path, write_atomic
from timologio.models import Direction, Document
from timologio.mydata.parse import extract_cursors, iso_date, parse_documents
from timologio.normalize import mask, norm_afm, valid_afm, valid_subscription_key

# --------------------------------------------------------------------------
# pdf_url — το εύρημα ότι τα docs της ΑΑΔΕ είναι λάθος
# --------------------------------------------------------------------------

def test_pdf_suffix_is_appended() -> None:
    """Το επίσημο PDF (σελ. 31) λέει ότι το σκέτο url δίνει PDF· μετρημένα
    Epsilon και Impact γυρίζουν HTML. Το /pdf είναι υποχρεωτικό."""
    assert pdf_url("https://x.gr/fd/abc:201") == "https://x.gr/fd/abc:201/pdf"
    assert pdf_url("https://x.gr/fd/abc/") == "https://x.gr/fd/abc/pdf"


def test_pdf_url_is_idempotent() -> None:
    assert pdf_url("https://x.gr/fd/a/pdf") == "https://x.gr/fd/a/pdf"


def test_pdf_url_preserves_other_formats() -> None:
    for suffix in ("/myDATA", "/EN16931"):
        assert pdf_url(f"https://x.gr/p/a{suffix}") == f"https://x.gr/p/a{suffix}"


# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------

def test_target_path_uses_requested_naming_scheme(tmp_path: Path) -> None:
    """<ΠΡΟΜΗΘΕΥΤΗΣ>_<ΑΦΜ>_<ΗΜ/ΝΙΑ>_<ΣΕΙΡΑ>_<ΑΑ>_<ΑΞΙΑ>"""
    doc = Document(mark="400012146904534", invoice_type="1.1",
                   issuer_vat="987654324", issuer_name="ΧΡΩΜΑΤΑ ΠΑΡΑΔΕΙΓΜΑ ΟΕ",
                   counter_vat="123456783", series="ΤΔΑ", aa="1",
                   issue_date="2026-01-02", total_value=40.29)
    path = target_path(tmp_path, "123456783", doc)
    assert path.name == "ΧΡΩΜΑΤΑ ΠΑΡΑΔΕΙΓΜΑ ΟΕ_987654324_2026-01-02_ΤΔΑ_1_40,29.pdf"
    assert path.parent.name == "01" and path.parent.parent.name == "2026"
    assert path.is_relative_to(tmp_path / "123456783")


def test_amount_uses_greek_decimal_comma() -> None:
    from timologio.download import format_amount

    assert format_amount(40.29) == "40,29"
    assert format_amount(1234.5) == "1234,50"
    # Χωρίς τελεία χιλιάδων: θα έμπλεκε με την κατάληξη αρχείου.
    assert "." not in format_amount(1234567.89)


def test_target_path_picks_counterparty_for_outgoing(tmp_path: Path) -> None:
    """Στα εκδοθέντα ο «άλλος» είναι ο λήπτης, όχι ο εκδότης.

    Χωρίς αυτό, κάθε εκδοθέν θα ονομαζόταν με το ΑΦΜ του ίδιου του πελάτη.
    """
    doc = Document(mark="1", invoice_type="1.1",
                   issuer_vat="123456783", issuer_name="Ο ΠΕΛΑΤΗΣ ΜΑΣ",
                   counter_vat="044004008", counter_name="ΠΑΡΑΔΕΙΓΜΑ Α.Ε.",
                   series="Α", aa="7", issue_date="2026-07-01", total_value=10.0)
    name = target_path(tmp_path, "123456783", doc).name
    assert name.startswith("ΠΑΡΑΔΕΙΓΜΑ Α.Ε._044004008_")
    assert "123456783" not in name


def test_missing_supplier_name_falls_back_to_vat(tmp_path: Path) -> None:
    """Το myDATA δίνει επωνυμία μόνο στο ~70%. Χωρίς όνομα -> ξεκινά από ΑΦΜ."""
    doc = Document(mark="1", invoice_type="1.1", issuer_vat="094173365",
                   counter_vat="123456783", series="Β", aa="5",
                   issue_date="2026-07-01", total_value=14.69)
    name = target_path(tmp_path, "123456783", doc).name
    assert name == "094173365_2026-07-01_Β_5_14,69.pdf"
    assert "ΑΓΝΩΣΤΟΣ" not in name


def test_long_supplier_name_is_capped_not_path_overflow(tmp_path: Path) -> None:
    doc = Document(mark="1", invoice_type="1.1", issuer_vat="094222211",
                   issuer_name="ΠΛΑΙΣΙΟ COMPUTERS ΑΝΩΝΥΜΗ ΕΜΠΟΡΙΚΗ ΚΑΙ ΒΙΟΜΗΧΑΝΙΚΗ ΕΤΑΙΡΕΙΑ",
                   counter_vat="123456783", series="ΤΔ137", aa="001689250",
                   issue_date="2026-01-03", total_value=1234.56)
    path = target_path(tmp_path, "123456783", doc)
    assert len(str(path)) < 260, "δεν πρέπει να ξεπερνά το MAX_PATH"
    assert path.name.endswith("_094222211_2026-01-03_ΤΔ137_001689250_1234,56.pdf")


def test_target_path_survives_missing_date(tmp_path: Path) -> None:
    doc = Document(mark="1", invoice_type="1.1", issue_date="")
    path = target_path(tmp_path, "123456783", doc)
    assert path.parent.name == "00" and path.parent.parent.name == "0000"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('a<b>c:d"e/f\\g|h?i*j', "a_b_c_d_e_f_g_h_i_j"),
        ("CON", "_CON"),
        ("nul.pdf", "_nul.pdf"),
        ("trailing. ", "trailing"),
        ("", "_"),
    ],
)
def test_sanitize(raw: str, expected: str) -> None:
    assert sanitize(raw) == expected


def test_write_atomic_leaves_no_part_file(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b.pdf"
    size, sha = write_atomic(path, b"%PDF-1.4 hello")
    assert size == 14 and len(sha) == 64
    assert path.read_bytes() == b"%PDF-1.4 hello"
    assert not list(tmp_path.rglob("*.part"))


def test_is_complete_pdf_rejects_html_and_stubs(tmp_path: Path) -> None:
    good = tmp_path / "g.pdf"
    write_atomic(good, b"%PDF-1.4" + b"x" * 200)
    assert is_complete_pdf(good)

    html = tmp_path / "h.pdf"
    write_atomic(html, b"<!DOCTYPE html>" + b"x" * 200)
    assert not is_complete_pdf(html)

    tiny = tmp_path / "t.pdf"
    write_atomic(tiny, b"%PDF")
    assert not is_complete_pdf(tiny), "πολύ μικρό για να είναι αληθινό PDF"

    assert not is_complete_pdf(tmp_path / "missing.pdf")


# --------------------------------------------------------------------------
# normalize
# --------------------------------------------------------------------------

def test_norm_afm_handles_excel_artifacts() -> None:
    assert norm_afm("123456783") == "123456783"
    assert norm_afm("123456783.0") == "123456783"  # Excel float
    assert norm_afm(" 123456783 ") == "123456783"
    assert norm_afm("75155090") == "075155090"     # χαμένο αρχικό μηδέν
    assert norm_afm("άκυρο") == ""
    assert norm_afm(None) == ""


def test_valid_afm_checksum() -> None:
    assert valid_afm("123456783")
    assert not valid_afm("802576638")
    assert not valid_afm("123")


def test_valid_subscription_key_is_32_hex() -> None:
    assert valid_subscription_key("deadbeefcafef00d0123456789abcdef")
    assert not valid_subscription_key("κοντό")
    assert not valid_subscription_key("g" * 32)  # όχι hex
    assert not valid_subscription_key("")


def test_mask_never_reveals_full_secret() -> None:
    secret = "deadbeefcafef00d0123456789abcdef"
    masked = mask(secret)
    assert secret not in masked and len(masked) < len(secret)
    assert mask("") == "—"


# --------------------------------------------------------------------------
# crypto
# --------------------------------------------------------------------------

def test_roundtrip_and_prefix(tmp_path: Path) -> None:
    c = Crypto(tmp_path / ".enckey")
    token = c.enc("μυστικό")
    assert token.startswith("enc:1:")
    assert c.dec(token) == "μυστικό"
    assert c.enc("") == "" and c.dec("") == ""


def test_plaintext_passthrough(tmp_path: Path) -> None:
    """το παλιότερο εργαλείο — τιμή χωρίς prefix επιστρέφεται ως έχει, ώστε η
    ενεργοποίηση κρυπτογράφησης να μη σπάει υπάρχοντα δεδομένα."""
    c = Crypto(tmp_path / ".enckey")
    assert c.dec("σκέτο κείμενο") == "σκέτο κείμενο"


def test_wrong_key_returns_empty_not_crash(tmp_path: Path) -> None:
    token = Crypto(tmp_path / "a.key").enc("μυστικό")
    assert Crypto(tmp_path / "b.key").dec(token) == ""


def test_redaction_filter_hides_keys() -> None:
    import logging

    f = SecretRedactingFilter()
    rec = logging.LogRecord("t", logging.INFO, "f", 1,
                            "key=deadbeefcafef00d0123456789abcdef", (), None)
    f.filter(rec)
    assert "deadbeefcafef00d0123456789abcdef" not in rec.getMessage()
    assert "<redacted-key>" in rec.getMessage()


# --------------------------------------------------------------------------
# parse
# --------------------------------------------------------------------------

INVOICE_XML = """<?xml version="1.0" encoding="utf-8"?>
<RequestedDoc xmlns="http://www.aade.gr/myDATA/invoice/v1.0">
 <invoicesDoc>
  <invoice>
   <issuer><vatNumber>044004008</vatNumber><name>ΠΡΟΜΗΘΕΥΤΗΣ ΑΕ</name></issuer>
   <counterpart><vatNumber>123456783</vatNumber></counterpart>
   <invoiceHeader><series>TDA</series><aa>3949</aa>
     <issueDate>2026-07-15</issueDate><invoiceType>1.1</invoiceType></invoiceHeader>
   <invoiceSummary><totalNetValue>163.25</totalNetValue>
     <totalVatAmount>39.18</totalVatAmount><totalGrossValue>202.43</totalGrossValue></invoiceSummary>
   <mark>400014401148454</mark>
   <downloadingInvoiceUrl>https://einvoice.impact.gr/p/EL044004008/AAA/BBB</downloadingInvoiceUrl>
  </invoice>
  <invoice>
   <issuer><vatNumber>802664834</vatNumber></issuer>
   <invoiceHeader><issueDate>2026-07-13</issueDate><invoiceType>2.1</invoiceType></invoiceHeader>
   <invoiceSummary><totalNetValue>2.80</totalNetValue><totalVatAmount>0</totalVatAmount></invoiceSummary>
   <mark>400014195430160</mark>
  </invoice>
 </invoicesDoc>
 <continuationToken><nextPartitionKey>PK1</nextPartitionKey><nextRowKey>RK1</nextRowKey></continuationToken>
</RequestedDoc>""".encode("utf-8")


def test_parse_one_row_per_mark() -> None:
    """Το fetch.py σπάει ανά κατηγορία ΦΠΑ· εδώ θέλουμε 1 MARK = 1 εγγραφή."""
    docs, cursors = parse_documents(INVOICE_XML, Direction.INCOMING)
    assert len(docs) == 2
    assert len({d.mark for d in docs}) == 2

    first = docs[0]
    assert first.mark == "400014401148454"
    assert first.invoice_type == "1.1"
    assert first.issuer_vat == "044004008"
    assert first.issuer_name == "ΠΡΟΜΗΘΕΥΤΗΣ ΑΕ"
    assert first.counter_vat == "123456783"
    assert first.series == "TDA" and first.aa == "3949"
    assert first.total_value == 202.43
    assert first.provider_host == "einvoice.impact.gr"
    assert first.xml_blob is None, "με provider url δεν κρατάμε άσκοπα XML"

    assert cursors["nextPartitionKey"] == "PK1"
    assert cursors["nextRowKey"] == "RK1"


def test_invoice_without_url_keeps_xml_fallback() -> None:
    """~11% δεν πέρασαν από πάροχο — κρατάμε το XML τους."""
    docs, _ = parse_documents(INVOICE_XML, Direction.INCOMING)
    second = docs[1]
    assert second.downloading_invoice_url == ""
    assert second.provider_host == ""
    assert second.xml_blob is not None
    assert b"400014195430160" in second.xml_blob


def test_iso_date_conversion() -> None:
    assert iso_date("2026-07-15") == "2026-07-15"
    assert iso_date("15/07/2026") == "2026-07-15"
    assert iso_date("5/7/2026") == "2026-07-05"
    assert iso_date("") == ""


def test_extract_cursors_supports_legacy_token() -> None:
    from xml.etree import ElementTree as ET

    xml = b"""<R xmlns="http://www.aade.gr/myDATA/invoice/v1.0">
      <nextPartitionToken>TOK</nextPartitionToken></R>"""
    cursors = extract_cursors(ET.fromstring(xml))
    assert cursors["nextPartitionToken"] == "TOK"
    assert cursors["nextPartitionKey"] == ""


# --------------------------------------------------------------------------
# ασφάλεια
# --------------------------------------------------------------------------

def test_client_repr_never_leaks_credentials() -> None:
    from timologio.models import Client

    c = Client(vat="123456783", label="X", mydata_user="U", mydata_key="k" * 32)
    assert "k" * 32 not in repr(c)
    assert "U" not in repr(c).replace("123456783", "")


def test_mydata_client_refuses_non_aade_host(tmp_path: Path) -> None:
    """Δικλείδα: τα διαπιστευτήρια δεν φεύγουν ποτέ εκτός ΑΑΔΕ."""
    from timologio.mydata import MydataClient

    settings = load_settings()
    with MydataClient("u", "k", settings) as api:
        with pytest.raises(ValueError, match="δεν στέλνονται"):
            api._get("https://einvoice.impact.gr/steal", {})


def test_provider_session_has_no_auth_headers() -> None:
    from timologio.download import ProviderDownloader

    d = ProviderDownloader(load_settings())
    try:
        keys = {k.lower() for k in d._session.headers}
        assert "ocp-apim-subscription-key" not in keys
        assert "aade-user-id" not in keys
    finally:
        d.close()

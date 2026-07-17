"""RequestE3Info — κατάσταση χαρακτηρισμού ανά παραστατικό.

Μετρημένο σε πραγματικό πελάτη (Ιούλιος 2026, 32 εισερχόμενα + 2 εκδοθέντα):

    V_Class_Category = «ΜΗ ΧΑΡΑΚΤΗΡΙΣΜΕΝΑ ΕΞΟΔΑ»  -> 24 παραστατικά
    V_Class_Category = category2_2 / category1_3 / category2_4 ->  5
    καθόλου εγγραφή E3 (τύποι 9.3, 8.4)            ->  5

Άρα **η απουσία εγγραφής E3 δεν σημαίνει αχαρακτήριστο**: σημαίνει ότι το
παραστατικό δεν υπόκειται σε χαρακτηρισμό εξόδων (π.χ. δελτία διακίνησης).
Το «αχαρακτήριστο» το λέει ρητά η ΑΑΔΕ με την κατηγορία «ΜΗ ΧΑΡΑΚΤΗΡΙΣΜΕΝΑ
ΕΞΟΔΑ». Γι' αυτό έχουμε τρεις καταστάσεις, όχι δύο.

Ο κανόνας ταυτίζεται με το fetch.py:347.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

from ..models import Classification

_UNCLASSIFIED_MARKER = "ΧΑΡΑΚΤΗΡΙΣΜΕΝΑ"


def _local(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _record_fields(node: ET.Element) -> dict[str, str]:
    return {_local(s.tag): (s.text or "").strip() for s in node.iter()}


def classify_category(category: str) -> Classification:
    """«ΜΗ ΧΑΡΑΚΤΗΡΙΣΜΕΝΑ ΕΞΟΔΑ» -> αχαρακτήριστο, οτιδήποτε άλλο -> χαρακτηρισμένο."""
    value = (category or "").strip().upper()
    if value.startswith("ΜΗ") and _UNCLASSIFIED_MARKER in value:
        return Classification.UNCLASSIFIED
    return Classification.CLASSIFIED


def parse_e3(payload: bytes) -> dict[str, Classification]:
    """MARK -> κατάσταση χαρακτηρισμού, για όσα MARK έχουν εγγραφή E3."""
    root = ET.fromstring(payload)
    out: dict[str, Classification] = {}
    for node in root.iter():
        if _local(node.tag) != "E3Info":
            continue
        fields = _record_fields(node)
        mark = fields.get("V_Mark", "")
        if not mark:
            continue
        status = classify_category(fields.get("V_Class_Category", ""))
        # Αν ένα MARK έχει πολλές γραμμές E3, αρκεί μία αχαρακτήριστη για να
        # θεωρηθεί ότι θέλει δουλειά.
        if out.get(mark) is not Classification.UNCLASSIFIED:
            out[mark] = status
    return out

"""Ανάγνωση .xlsx χωρίς openpyxl.

Τα αρχεία που εξάγει η ΑΑΔΕ σπάνε το openpyxl με «could not read stylesheet ...
invalid XML», και το pandas.read_excel πέφτει από κάτω στο ίδιο. Ξεζιπάρουμε
μόνοι μας και διαβάζουμε το sheet XML — μας νοιάζουν οι τιμές, όχι τα styles.

Ίδια προσέγγιση με το ένα παλιότερο εργαλείο, με δύο διαφορές: επιστρέφουμε **όλα**
τα φύλλα με το όνομά τους, και κρατάμε το γράμμα στήλης κάθε κελιού (ο block
parser της Μορφής Α το χρειάζεται για να διατηρήσει τη σειρά).
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_COL = re.compile(r"([A-Z]+)(\d+)")


@dataclass
class Sheet:
    name: str
    rows: list[dict[str, str]] = field(default_factory=list)
    """Κάθε γραμμή: {γράμμα στήλης -> τιμή}. Τα κενά κελιά λείπουν."""

    def row_values(self, index: int) -> list[str]:
        """Οι μη-κενές τιμές μιας γραμμής, με σειρά στήλης."""
        if index >= len(self.rows):
            return []
        row = self.rows[index]
        return [row[k] for k in sorted(row, key=_col_index) if row[k]]

    def row_text(self, index: int) -> str:
        return " ".join(self.row_values(index))


def _col_index(letters: str) -> int:
    value = 0
    for ch in letters:
        value = value * 26 + (ord(ch) - 64)
    return value


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(f"{_NS}t")) for si in root.findall(f"{_NS}si")]


def _cell_value(cell: ET.Element, shared: list[str]) -> str:
    ctype = cell.get("t")
    if ctype == "inlineStr":
        node = cell.find(f"{_NS}is")
        return "".join(t.text or "" for t in node.iter(f"{_NS}t")) if node is not None else ""
    node = cell.find(f"{_NS}v")
    if node is None or node.text is None:
        return ""
    if ctype == "s":
        try:
            return shared[int(node.text)]
        except (ValueError, IndexError):
            return ""
    return node.text


def _sheet_targets(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    """(όνομα φύλλου, διαδρομή xml) με τη σειρά του βιβλίου."""
    names = zf.namelist()
    if "xl/workbook.xml" not in names:
        return []
    book = ET.fromstring(zf.read("xl/workbook.xml"))

    rels: dict[str, str] = {}
    if "xl/_rels/workbook.xml.rels" in names:
        rel_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        for rel in rel_root:
            rid, target = rel.get("Id"), rel.get("Target")
            if rid and target:
                rels[rid] = target if target.startswith("xl/") else f"xl/{target.lstrip('/')}"

    out: list[tuple[str, str]] = []
    for idx, sheet in enumerate(book.iter(f"{_NS}sheet"), start=1):
        name = sheet.get("name") or f"Sheet{idx}"
        rid = sheet.get(f"{_REL_NS}id")
        path = rels.get(rid or "", f"xl/worksheets/sheet{idx}.xml")
        if path in names:
            out.append((name, path))
    return out


def read_workbook(path: Path | str) -> list[Sheet]:
    """Διαβάζει όλα τα φύλλα. Σηκώνει ValueError αν δεν είναι xlsx."""
    path = Path(path)
    if not zipfile.is_zipfile(path):
        raise ValueError(
            f"Το {path.name} δεν είναι αρχείο .xlsx. "
            "Οι μορφές .xls / .csv δεν υποστηρίζονται — αποθηκεύστε ως .xlsx."
        )
    sheets: list[Sheet] = []
    with zipfile.ZipFile(path) as zf:
        shared = _shared_strings(zf)
        for name, target in _sheet_targets(zf):
            root = ET.fromstring(zf.read(target))
            sheet = Sheet(name=name)
            for row in root.iter(f"{_NS}row"):
                values: dict[str, str] = {}
                for cell in row.findall(f"{_NS}c"):
                    ref = cell.get("r") or ""
                    match = _COL.match(ref)
                    if not match:
                        continue
                    text = _cell_value(cell, shared).strip()
                    if text:
                        values[match.group(1)] = text
                sheet.rows.append(values)
            sheets.append(sheet)
    return sheets

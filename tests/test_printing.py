"""Μαζική εκτύπωση — προεπισκόπηση.

Δεν μπορούμε να ανοίξουμε πραγματικό modal σε CI, οπότε ελέγχουμε τα ασφαλή
μονοπάτια (κενή/ανύπαρκτη λίστα) και ότι ξαναχρησιμοποιούμε τη native
προεπισκόπηση του Qt — αυτήν με τα εικονίδια/κουμπιά της που ζήτησε ο χρήστης,
αντί για μια δική μας γυμνή γραμμή εργαλείων.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from timologio.gui import printing  # noqa: E402
from timologio.gui.printing import print_pdfs  # noqa: E402


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


def test_empty_list_opens_nothing(app):
    assert print_pdfs([], None) == (0, 0)


def test_missing_paths_are_dropped(app, tmp_path: Path):
    assert print_pdfs([tmp_path / "δεν-υπάρχει.pdf"], None) == (0, 0)


def test_uses_native_qt_preview():
    """Native QPrintPreviewDialog = τα εικονίδια/κουμπιά/hints του Qt."""
    source = Path(printing.__file__).read_text(encoding="utf-8")
    assert "QPrintPreviewDialog" in source


def test_toolbar_icons_and_greek_tooltips(app):
    """Τα κενά κουμπιά (Εκτύπωση/Ζουμ) παίρνουν δικά μας εικονίδια και ελληνικά
    tooltips, χωρίς να αλλάξει το native preview."""
    from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
    from PySide6.QtWidgets import QToolBar

    dialog = QPrintPreviewDialog(QPrinter())
    printing._fix_toolbar_icons(dialog)
    found: dict[str, tuple[bool, str]] = {}
    for toolbar in dialog.findChildren(QToolBar):
        for action in toolbar.actions():
            if action.text() in ("Print", "Zoom in", "Zoom out"):
                found[action.text()] = (not action.icon().isNull(), action.toolTip())
    assert all(icon_set for icon_set, _ in found.values())
    assert found["Print"][1] == "Εκτύπωση"
    assert found["Zoom in"][1] == "Μεγέθυνση"
    assert found["Zoom out"][1] == "Σμίκρυνση"


def test_manual_rebuilds_stale_empty_pdf(app, tmp_path: Path):
    """Ένα παλιό «άδειο» εγχειρίδιο με σωστή σφραγίδα ΔΕΝ μένει για πάντα:
    ξαναχτίζεται σε έγκυρο PDF."""
    import hashlib

    from timologio.gui import manual
    from timologio.gui.theme import apply_theme

    apply_theme(app, "light")
    target = tmp_path / manual.FILENAME
    target.write_bytes(b"%PDF-1.4 tiny")  # άδειο/χαλασμένο
    (tmp_path / ".manual.hash").write_text(
        hashlib.sha256(manual._html().encode("utf-8")).hexdigest(), encoding="utf-8"
    )
    assert not manual._looks_built(target)
    path = manual.ensure_manual(tmp_path)
    assert manual._looks_built(path)
    assert path.stat().st_size > 20_000


def test_wait_cursor_is_balanced_inside_render():
    """Ο δείκτης αναμονής μπαίνει/βγαίνει ΜΕΣΑ στο render, όχι γύρω από το
    exec(): αλλιώς έμενε κολλημένος «loading» σε όλη την προεπισκόπηση."""
    source = Path(printing.__file__).read_text(encoding="utf-8")
    # Δεν τυλίγουμε το exec() με override cursor.
    assert "setOverrideCursor" in source
    body = source[source.index("def render("):source.index("printer = QPrinter(")]
    assert "setOverrideCursor" in body
    assert "restoreOverrideCursor" in body

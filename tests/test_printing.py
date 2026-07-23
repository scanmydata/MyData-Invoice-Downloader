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


def test_wait_cursor_is_balanced_inside_render():
    """Ο δείκτης αναμονής μπαίνει/βγαίνει ΜΕΣΑ στο render, όχι γύρω από το
    exec(): αλλιώς έμενε κολλημένος «loading» σε όλη την προεπισκόπηση."""
    source = Path(printing.__file__).read_text(encoding="utf-8")
    # Δεν τυλίγουμε το exec() με override cursor.
    assert "setOverrideCursor" in source
    body = source[source.index("def render("):source.index("printer = QPrinter(")]
    assert "setOverrideCursor" in body
    assert "restoreOverrideCursor" in body

"""Tests για τα γραφικά που φτιάχνονται στη στιγμή.

Το `icon()` επιστρέφει άδειο QIcon όταν δεν βρει σχέδιο — δεν σκάει, δεν
προειδοποιεί. Έτσι η Λήψη και τα Παραστατικά έμειναν χωρίς εικονίδιο και το
είδαμε μόνο με το μάτι, δύο φορές. Αυτά τα tests το πιάνουν αντί για εμάς.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def app():
    """Το QPixmap χρειάζεται QGuiApplication για να υπάρξει."""
    existing = QApplication.instance()
    yield existing or QApplication([])


def test_every_menu_button_has_an_icon(app) -> None:
    from timologio.gui.side_menu import _ICONS
    from timologio.gui.icons import _SVG

    from timologio.gui.side_menu import SideMenu

    menu = SideMenu()
    missing = [
        name for name in menu._buttons
        if _ICONS.get(name, name) not in _SVG
    ]
    assert missing == [], f"κουμπιά μενού χωρίς σχέδιο εικονιδίου: {missing}"


def test_menu_buttons_render_a_non_empty_icon(app) -> None:
    from timologio.gui.side_menu import SideMenu

    menu = SideMenu()
    blank = [name for name, button in menu._buttons.items() if button.icon().isNull()]
    assert blank == [], f"κουμπιά μενού με άδειο εικονίδιο: {blank}"


def test_icon_alias_targets_exist(app) -> None:
    from timologio.gui.icons import _SVG
    from timologio.gui.side_menu import _ICONS

    for action, drawing in _ICONS.items():
        assert drawing in _SVG, f"το «{action}» δείχνει σε ανύπαρκτο «{drawing}»"


def test_indicator_image_is_written_and_readable(app) -> None:
    """Το ✓ των checkbox: χωρίς αρχείο, το κουτάκι μένει βαμμένο αλλά κενό."""
    from pathlib import Path

    from PySide6.QtGui import QImage

    from timologio.gui.icons import indicator_image

    path = Path(indicator_image("#ffffff"))
    assert path.exists()
    image = QImage(str(path))
    assert not image.isNull(), "το PNG δεν διαβάζεται"
    assert image.width() == 14


def test_indicator_image_has_a_retina_twin(app) -> None:
    """Το Qt ψάχνει το @2x μόνο του σε οθόνες 150%+."""
    from pathlib import Path

    from timologio.gui.icons import indicator_image

    path = Path(indicator_image("#ffffff"))
    assert path.with_name(f"{path.stem}@2x.png").exists()


def test_indicator_actually_draws_something(app) -> None:
    """Ένα εντελώς διάφανο PNG θα περνούσε όλα τα προηγούμενα tests."""
    from pathlib import Path

    from PySide6.QtGui import QImage

    from timologio.gui.icons import indicator_image

    image = QImage(indicator_image("#ffffff"))
    opaque = sum(
        1
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 40
    )
    assert opaque > 10, f"το ✓ είναι σχεδόν κενό ({opaque} pixel)"


@pytest.fixture
def seeded_window(app, tmp_path, monkeypatch):
    """Παράθυρο πάνω σε δική του βάση με έναν πελάτη.

    Χρειάζεται πελάτη: το βήμα της ανάλυσης δεν έχει τι να φωτίσει σε άδεια
    εγκατάσταση, και δεν θέλουμε να εξαρτιόμαστε από τα πραγματικά δεδομένα.
    """
    monkeypatch.setenv("TIMOLOGIO_DATA_DIR", str(tmp_path))
    from timologio.crypto import Crypto
    from timologio.db import init_db
    from timologio.models import Client
    from timologio.repo import upsert_client

    conn = init_db(tmp_path / "timologio.db")
    upsert_client(
        conn,
        Client(vat="802576637", label="ΤΟ ΒΑΨΙΜΟ Ε Ε", mydata_user="u",
               mydata_key="k" * 32),
        Crypto(tmp_path / ".enckey"),
    )
    conn.commit()
    conn.close()

    from timologio.gui.main_window import MainWindow

    window = MainWindow()
    window.show()
    yield window
    window.close()


def test_every_tour_step_has_a_visible_target(seeded_window) -> None:
    """Ένα βήμα που δείχνει κρυμμένο widget φωτίζει το τίποτα.

    Συνέβη: το δεξί panel έγινε «κλειστό όσο δεν υπάρχει επιλεγμένος πελάτης»
    και το βήμα της ανάλυσης έμεινε να δείχνει αέρα.
    """
    blank = []
    for index, step in enumerate(seeded_window._tour_steps(), start=1):
        if step.before:
            step.before()
        target = step.target()
        if target is None or not target.isVisible():
            blank.append(f"{index}. {step.title}")
    assert blank == [], f"βήματα χωρίς ορατό στόχο: {blank}"


def test_tour_explains_column_resizing(seeded_window) -> None:
    """Ζητήθηκε ρητά να το λέει η ξενάγηση."""
    text = " ".join(f"{s.title} {s.text}" for s in seeded_window._tour_steps())
    assert "πλάτος" in text
    assert "σειρά" in text
    assert "αποθηκεύεται" in text


def test_tour_survives_an_empty_installation(app, tmp_path, monkeypatch) -> None:
    """Χωρίς κανέναν πελάτη η ξενάγηση δεν πρέπει να σκάει — απλώς δεν φωτίζει."""
    monkeypatch.setenv("TIMOLOGIO_DATA_DIR", str(tmp_path))
    from timologio.gui.main_window import MainWindow

    window = MainWindow()
    window.show()
    window.start_tour()
    for index in range(len(window._tour_steps())):
        window._tour.go(index)
    window._tour.stop()
    window.close()

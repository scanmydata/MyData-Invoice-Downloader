"""Tests για την εναλλαγή θέματος.

Το σφάλμα που φυλάνε: τα modules γράφουν `from .theme import CURRENT`, που δένει
το αντικείμενο τη στιγμή του import. Όσο το `apply_theme` ξανάδενε το όνομα, το
`theme.CURRENT` γινόταν LIGHT ενώ το `side_menu.CURRENT` έμενε DARK — και το
φωτεινό θέμα ζωγράφιζε εικονίδια με σκούρα χρώματα, δηλαδή αόρατα.

Δεν φαίνεται σε code review και δεν σκάει· απλώς βγαίνει άσχημο.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def restore_dark(app):
    """Κάθε test αφήνει το θέμα όπως το βρήκε."""
    from timologio.gui.theme import apply_theme

    yield
    apply_theme(app, "dark")


def test_apply_theme_changes_every_module_view(app) -> None:
    from timologio.gui import documents_view, side_menu, theme, tour, widgets
    from timologio.gui.theme import apply_theme

    apply_theme(app, "light")
    for module in (theme, side_menu, widgets, documents_view, tour):
        assert module.CURRENT.name == "light", (
            f"το {module.__name__} βλέπει ακόμη «{module.CURRENT.name}»"
        )


def test_current_is_the_same_object_across_themes(app) -> None:
    """Αν το apply_theme ξαναδέσει το όνομα, το σφάλμα επιστρέφει σιωπηλά."""
    from timologio.gui import theme
    from timologio.gui.theme import apply_theme

    before = id(theme.CURRENT)
    apply_theme(app, "light")
    assert id(theme.CURRENT) == before


def test_colours_actually_differ_between_themes(app) -> None:
    from timologio.gui import side_menu
    from timologio.gui.theme import DARK, LIGHT, apply_theme

    apply_theme(app, "light")
    light_muted = side_menu.CURRENT.muted
    apply_theme(app, "dark")
    dark_muted = side_menu.CURRENT.muted

    assert light_muted == LIGHT.muted
    assert dark_muted == DARK.muted
    assert light_muted != dark_muted


def test_menu_icons_repaint_on_theme_change(app) -> None:
    """Τα εικονίδια είναι bitmaps: αν δεν ξαναφτιαχτούν, μένουν στο παλιό χρώμα."""
    from timologio.gui.side_menu import SideMenu
    from timologio.gui.theme import apply_theme

    menu = SideMenu()
    apply_theme(app, "dark")
    menu.restyle()
    dark = menu.button("clients").icon().pixmap(18, 18).toImage()

    apply_theme(app, "light")
    menu.restyle()
    light = menu.button("clients").icon().pixmap(18, 18).toImage()

    assert dark != light, "το εικονίδιο έμεινε βαμμένο στο χρώμα του σκούρου θέματος"


def test_toggle_knob_follows_blocked_setChecked(app) -> None:
    """Η εκκίνηση θυμάται το θέμα με blockSignals — η μπίλια πρέπει να ακολουθεί.

    Αλλιώς ο διακόπτης δείχνει «κλειστό» ενώ το φωτεινό θέμα είναι αναμμένο.
    """
    from timologio.gui.widgets import ToggleSwitch

    switch = ToggleSwitch("Φωτεινό θέμα")
    switch.blockSignals(True)
    switch.setChecked(True)
    switch.blockSignals(False)
    switch._anim.setCurrentTime(switch._anim.duration())  # τελείωσε η κίνηση
    assert switch.knob == 1.0, "η μπίλια έμεινε στο «κλειστό»"


def test_toggle_knob_returns_when_unchecked(app) -> None:
    from timologio.gui.widgets import ToggleSwitch

    switch = ToggleSwitch()
    switch.setChecked(True)
    switch._anim.setCurrentTime(switch._anim.duration())
    switch.setChecked(False)
    switch._anim.setCurrentTime(switch._anim.duration())
    assert switch.knob == 0.0


def test_stat_tile_default_colour_follows_theme(app) -> None:
    """Η προεπιλογή του color αποτιμιόταν στο import και πάγωνε το θέμα."""
    from timologio.gui.analysis_panel import StatTile
    from timologio.gui.theme import LIGHT, apply_theme

    apply_theme(app, "light")
    tile = StatTile("5", "Δοκιμή")
    label = tile.findChild(type(tile.layout().itemAt(0).widget()))
    assert LIGHT.accent in label.styleSheet()

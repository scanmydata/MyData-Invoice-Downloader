"""Θέματα εμφάνισης — σκούρο και φωτεινό.

Το σκούρο κρατά την παλέτα του το αδελφό εργαλείο, ώστε τα δύο εργαλεία να
μοιάζουν. Το φωτεινό είναι ο ίδιος σκελετός με αντεστραμμένες τιμές.

Τα χρώματα εκτίθενται ως module-level ονόματα (ACCENT, OK, BAD…) γιατί τα
χρησιμοποιεί κώδικας που βάφει κελιά πινάκων στη στιγμή. Το `apply_theme()` τα
ξαναγράφει, οπότε όποιος διαβάζει `theme.OK` παίρνει πάντα το τρέχον θέμα.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    panel: str
    panel_alt: str
    chip: str
    line: str
    txt: str
    muted: str
    accent: str
    accent_deep: str
    on_accent: str
    ok: str
    bad: str
    warn: str
    menu_bg: str
    log_bg: str
    log_txt: str
    tile_hover: str


DARK = Palette(
    name="dark",
    bg="#0b1220",
    panel="#131f33",
    panel_alt="#16233a",
    chip="#0b2942",
    line="#2b3b54",
    txt="#e6edf6",
    muted="#93a4bd",
    accent="#38bdf8",
    accent_deep="#0ea5e9",
    on_accent="#04222f",
    ok="#22c55e",
    bad="#ef4444",
    warn="#f59e0b",
    menu_bg="#0a111e",
    log_bg="#08101c",
    log_txt="#c7d5e8",
    tile_hover="#182742",
)

LIGHT = Palette(
    name="light",
    bg="#f4f7fb",
    panel="#ffffff",
    panel_alt="#f0f4f9",
    chip="#e2effa",
    line="#d3dde9",
    txt="#0d2340",
    muted="#5f7285",
    accent="#0e7fbf",
    accent_deep="#0ea5e9",
    on_accent="#ffffff",
    # Πιο σκούρα από το σκούρο θέμα: το #22c55e σε λευκό φόντο δεν διαβάζεται.
    ok="#15803d",
    bad="#c81e1e",
    warn="#b45309",
    menu_bg="#e9eff7",
    log_bg="#ffffff",
    log_txt="#22364f",
    tile_hover="#eaf4fd",
)

RADIUS = "14px"


class _LivePalette:
    """Ζωντανή όψη της τρέχουσας παλέτας.

    Υπάρχει για έναν λόγο: τα modules γράφουν `from .theme import CURRENT`, που
    δένει το ίδιο το *αντικείμενο* τη στιγμή του import. Αν το `apply_theme`
    ξανάδενε απλώς το όνομα `CURRENT`, το `theme.CURRENT` θα γινόταν LIGHT ενώ
    το `side_menu.CURRENT` θα έμενε DARK για πάντα — και το φωτεινό θέμα θα
    ζωγράφιζε εικονίδια με `#93a4bd` πάνω σε ανοιχτό φόντο, δηλαδή αόρατα.

    Έτσι το αντικείμενο μένει το ίδιο και αλλάζει από μέσα· όποιος κρατά
    αναφορά, βλέπει πάντα το τρέχον θέμα.
    """

    __slots__ = ("_palette",)

    def __init__(self, palette: Palette) -> None:
        object.__setattr__(self, "_palette", palette)

    def _swap(self, palette: Palette) -> None:
        object.__setattr__(self, "_palette", palette)

    def __getattr__(self, field: str) -> str:
        # Το _palette βρίσκεται από το slot descriptor, οπότε δεν αναδρομεί.
        return getattr(object.__getattribute__(self, "_palette"), field)

    def __repr__(self) -> str:
        return f"<CURRENT {self._palette.name}>"


#: Το τρέχον θέμα. Το `apply_theme` αλλάζει το περιεχόμενό του, ποτέ το όνομα.
CURRENT = _LivePalette(DARK)

# Συμβατά ονόματα για κώδικα που βάφει κελιά.
BG = CURRENT.bg
PANEL = CURRENT.panel
CHIP = CURRENT.chip
LINE = CURRENT.line
TXT = CURRENT.txt
MUTED = CURRENT.muted
ACCENT = CURRENT.accent
ACCENT_DEEP = CURRENT.accent_deep
OK = CURRENT.ok
BAD = CURRENT.bad
WARN = CURRENT.warn


def _refresh_names(p: Palette) -> None:
    """Ενημερώνει το CURRENT και τα συμβατά ονόματα.

    Προσοχή: τα BG/PANEL/OK/… είναι απλά strings και **ξαναδένονται**. Όποιος τα
    κάνει `from .theme import OK` κρατά την παλιά τιμή. Χρησιμοποιήστε
    `CURRENT.ok`, που είναι ζωντανό.
    """
    global BG, PANEL, CHIP, LINE, TXT, MUTED, ACCENT, ACCENT_DEEP, OK, BAD, WARN
    CURRENT._swap(p)
    BG, PANEL, CHIP, LINE = p.bg, p.panel, p.chip, p.line
    TXT, MUTED = p.txt, p.muted
    ACCENT, ACCENT_DEEP = p.accent, p.accent_deep
    OK, BAD, WARN = p.ok, p.bad, p.warn


def build(p: Palette) -> str:
    # Το ✓ γεννιέται εδώ γιατί το χρώμα του εξαρτάται από το θέμα. Η εισαγωγή
    # είναι τοπική: το icons.py χρειάζεται QGuiApplication, ενώ αυτό το module
    # φορτώνεται και από κώδικα χωρίς GUI (π.χ. tests του CLI).
    from .icons import indicator_image

    check = indicator_image(p.on_accent)
    return f"""
QWidget {{ background: {p.bg}; color: {p.txt}; font-size: 13px; }}
QMainWindow, QDialog {{ background: {p.bg}; }}

QLabel {{ background: transparent; }}
QLabel#h1 {{ font-size: 19px; font-weight: 600; color: {p.txt}; }}
QLabel#muted {{ color: {p.muted}; }}
QLabel#stat {{ font-size: 22px; font-weight: 700; color: {p.accent}; }}
QLabel#statLabel {{ color: {p.muted}; font-size: 11px; }}
QLabel#hint {{ color: {p.accent}; font-size: 11px; }}

QFrame#card {{
    background: {p.panel};
    border: 1px solid {p.line};
    border-radius: {RADIUS};
}}
QFrame#line {{ background: {p.line}; max-height: 1px; border: none; }}
QFrame#banner {{
    background: {p.chip};
    border: 1px solid {p.accent};
    border-radius: 9px;
}}

QPushButton {{
    background: {p.chip};
    color: {p.txt};
    border: 1px solid {p.line};
    border-radius: 9px;
    padding: 7px 14px;
    font-weight: 600;
}}
QPushButton:hover  {{ border-color: {p.accent}; color: {p.accent}; }}
QPushButton:pressed {{ background: {p.line}; }}
QPushButton:disabled {{ color: {p.muted}; border-color: {p.line}; background: {p.panel}; }}

QPushButton#primary {{
    background: {p.accent_deep};
    border: 1px solid {p.accent};
    color: {p.on_accent};
}}
QPushButton#primary:hover {{ background: {p.accent}; }}
QPushButton#primary:disabled {{
    background: {p.panel}; color: {p.muted}; border-color: {p.line};
}}

QPushButton#danger {{ border-color: {p.bad}; color: {p.bad}; }}
QPushButton#danger:hover {{ background: {p.bad}; color: {p.on_accent}; }}

QLineEdit, QComboBox, QDateEdit, QSpinBox {{
    background: {p.panel};
    border: 1px solid {p.line};
    border-radius: 9px;
    padding: 6px 9px;
    color: {p.txt};
    selection-background-color: {p.accent_deep};
    selection-color: {p.on_accent};
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus {{ border-color: {p.accent}; }}
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled {{ color: {p.muted}; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {p.panel};
    border: 1px solid {p.line};
    selection-background-color: {p.chip};
    selection-color: {p.txt};
    outline: none;
}}
QCalendarWidget QWidget {{ alternate-background-color: {p.panel_alt}; }}
QCalendarWidget QAbstractItemView:enabled {{
    background: {p.panel}; color: {p.txt};
    selection-background-color: {p.accent_deep};
    selection-color: {p.on_accent};
}}
QCalendarWidget QToolButton {{ color: {p.txt}; background: transparent; }}
QCalendarWidget QMenu {{ background: {p.panel}; color: {p.txt}; }}

QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {p.line};
    border-radius: 4px;
    background: {p.panel};
}}
QCheckBox::indicator:hover {{ border-color: {p.accent}; }}
QCheckBox::indicator:checked {{
    background: {p.accent_deep};
    border-color: {p.accent};
    image: url({check});
}}
QCheckBox::indicator:disabled {{ background: {p.panel_alt}; border-color: {p.line}; }}

QTableWidget {{
    background: {p.panel};
    alternate-background-color: {p.panel_alt};
    border: 1px solid {p.line};
    border-radius: {RADIUS};
    gridline-color: {p.line};
    selection-background-color: {p.chip};
    selection-color: {p.txt};
    outline: none;
}}
QTableWidget::item {{ padding: 5px 7px; border: none; }}
QTableWidget::item:selected {{ background: {p.chip}; }}
QTableWidget::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {p.line};
    border-radius: 4px;
    background: {p.panel};
}}
QTableWidget::indicator:checked {{
    background: {p.accent_deep};
    border-color: {p.accent};
    image: url({check});
}}
QTableWidget::indicator:disabled {{ background: {p.panel_alt}; border-color: {p.line}; }}
QHeaderView::section {{
    background: {p.bg};
    color: {p.muted};
    border: none;
    border-bottom: 1px solid {p.line};
    padding: 7px;
    font-weight: 600;
}}
QTableCornerButton::section {{ background: {p.bg}; border: none; }}

QPlainTextEdit {{
    background: {p.log_bg};
    border: 1px solid {p.line};
    border-radius: {RADIUS};
    padding: 7px;
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 12px;
    color: {p.log_txt};
}}

QProgressBar {{
    background: {p.panel};
    border: 1px solid {p.line};
    border-radius: 7px;
    height: 15px;
    text-align: center;
    color: {p.txt};
}}
QProgressBar::chunk {{ background: {p.accent_deep}; border-radius: 6px; }}

QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px 2px 2px 0; border: none;
}}
QScrollBar::handle:vertical {{ background: {p.line}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p.muted}; }}
QScrollBar:horizontal {{
    background: transparent; height: 10px; margin: 0 2px 2px 2px; border: none;
}}
QScrollBar::handle:horizontal {{ background: {p.line}; border-radius: 4px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {p.muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; border: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 7px; }}
QSplitter::handle:vertical {{ height: 7px; }}
QSplitter::handle:hover {{ background: {p.accent_deep}; }}
QSplitter::handle:pressed {{ background: {p.accent}; }}

QStatusBar {{ background: {p.bg}; color: {p.muted}; border-top: 1px solid {p.line}; }}
QToolTip {{
    background: {p.panel};
    color: {p.txt};
    border: 1px solid {p.accent};
    border-radius: 7px;
    padding: 5px;
}}
QMenu {{ background: {p.panel}; border: 1px solid {p.line}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p.chip}; color: {p.accent}; }}
QMenu::separator {{ height: 1px; background: {p.line}; margin: 4px 8px; }}

/* ---------- Πλαϊνό μενού ---------- */
QWidget#sideMenu {{ background: {p.menu_bg}; border-right: 1px solid {p.line}; }}
QLabel#menuTitle {{ font-size: 17px; font-weight: 800; color: {p.accent}; }}
QLabel#menuSubtitle {{ font-size: 10px; color: {p.muted}; }}
QLabel#menuSection {{
    font-size: 10px; font-weight: 700; color: {p.muted}; letter-spacing: 1px;
}}
QLabel#menuVersion {{ font-size: 10px; color: {p.line}; }}

QPushButton#menuButton {{
    background: transparent; border: none; border-radius: 8px;
    padding: 8px 10px; text-align: left; font-weight: 600; color: {p.muted};
}}
QPushButton#menuButton:hover {{ background: {p.panel}; color: {p.txt}; }}
QPushButton#menuButton[active="true"] {{ background: {p.chip}; color: {p.accent}; }}
QPushButton#menuButton:disabled {{ color: {p.line}; }}
QPushButton#menuToggle {{
    background: transparent; border: none; border-radius: 8px; padding: 6px;
}}
QPushButton#menuToggle:hover {{ background: {p.panel}; }}

/* ---------- Ξενάγηση ---------- */
QFrame#tourCard {{
    background: {p.panel};
    border: 2px solid {p.accent};
    border-radius: {RADIUS};
}}
QLabel#tourTitle {{ font-size: 15px; font-weight: 700; color: {p.accent}; }}
QLabel#tourStep {{ font-size: 11px; color: {p.muted}; }}

/* ---------- Πλακίδια ---------- */
QPushButton#tile {{
    background: {p.panel};
    border: 1px solid {p.line};
    border-radius: 11px;
    text-align: left;
    padding: 0;
}}
QPushButton#tile:hover {{ border-color: {p.accent}; background: {p.tile_hover}; }}
QPushButton#tile:pressed {{ background: {p.chip}; }}

QPushButton#linkButton {{
    background: transparent; border: none; padding: 2px 0; text-align: left;
}}
QPushButton#linkButton:hover {{ text-decoration: underline; }}

QPushButton#rowButton {{
    background: transparent; border: 1px solid {p.line}; border-radius: 6px; padding: 0;
}}
QPushButton#rowButton:hover {{ border-color: {p.accent}; background: {p.chip}; }}
QPushButton#rowButton:disabled {{ border-color: transparent; }}
"""


def apply_theme(app, name: str) -> Palette:
    """Εφαρμόζει θέμα σε ολόκληρη την εφαρμογή και ενημερώνει τα χρώματα."""
    palette = LIGHT if name == "light" else DARK
    _refresh_names(palette)
    app.setStyleSheet(build(palette))
    return palette


def paint_title_bar(window, dark: bool) -> bool:
    """Βάφει τη γραμμή τίτλου (minimize/close) στο χρώμα του θέματος.

    Η γραμμή τίτλου ανήκει στα Windows, όχι στο Qt: κανένα stylesheet δεν τη
    φτάνει, γι' αυτό έμενε λευκή πάνω από σκούρα εφαρμογή. Το DWM δέχεται τη
    ρύθμιση από το Windows 10 20H1 και μετά — σε παλιότερα απλώς αγνοείται και
    επιστρέφουμε False.

    Επιστρέφει αν εφαρμόστηκε.
    """
    if os.name != "nt":
        return False
    try:
        import ctypes

        # 20 από το build 19041· 19 στα πρώτα insider builds. Δοκιμάζουμε και τα
        # δύο: το λάθος attribute απλώς γυρίζει σφάλμα, δεν χαλάει το παράθυρο.
        handle = int(window.winId())
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):
            ok = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(handle),
                ctypes.c_int(attribute),
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
            if ok == 0:
                return True
    except (OSError, AttributeError, ValueError):
        # Χωρίς dwmapi (Wine, παλιά Windows) η εφαρμογή δουλεύει μια χαρά με
        # λευκή γραμμή τίτλου — δεν είναι λόγος να μην ανοίξει.
        pass
    return False


def money(value: float) -> str:
    """Ελληνική μορφή: 1.234,56"""
    return f"{value:,.2f}".replace(",", "~").replace(".", ",").replace("~", ".")

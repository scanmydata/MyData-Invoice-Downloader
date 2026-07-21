"""Εικονίδια SVG, σχεδιασμένα inline.

Δεν φορτώνουμε αρχεία εικόνων: το PyInstaller θα έπρεπε να τα πακετάρει και οι
διαδρομές αλλάζουν μέσα στο bundle. Ένα SVG σε string ζωγραφίζεται παντού και
βάφεται στο χρώμα που θέλουμε.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_SVG: dict[str, str] = {
    # Ομάδα προσώπων και όχι «πρόσωπο με +»: το τελευταίο διαφέρει από το
    # add_client μόνο κατά μια παύλα, και στα 18 pixel του μενού τα δύο κουμπιά
    # έμοιαζαν ίδια.
    "clients": (
        '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>'
        '<circle cx="9" cy="7" r="4"/>'
        '<path d="M23 21v-2a4 4 0 0 0-3-3.87"/>'
        '<path d="M16 3.13a4 4 0 0 1 0 7.75"/>'
    ),
    "download": (
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>'
    ),
    "import": (
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>'
    ),
    "backup": (
        '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>'
        '<polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/>'
    ),
    "restore": (
        '<polyline points="1 4 1 10 7 10"/>'
        '<path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>'
    ),
    "csv": (
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/>'
        '<line x1="16" y1="17" x2="8" y2="17"/>'
    ),
    "key": (
        '<path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 '
        '7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>'
    ),
    "folder": (
        '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>'
    ),
    "lock": (
        '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>'
        '<path d="M7 11V7a5 5 0 0 1 10 0v4"/>'
    ),
    "info": (
        '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/>'
        '<line x1="12" y1="8" x2="12.01" y2="8"/>'
    ),
    # Δύο «κουτιά» στοιβαγμένα: ο κόσμος αναγνωρίζει τον server ως rack, ενώ
    # ένα σύννεφο θα υπονοούσε υπηρεσία στο internet — που ακριβώς δεν είναι.
    "network": (
        '<rect x="2" y="3" width="20" height="7" rx="2"/>'
        '<rect x="2" y="14" width="20" height="7" rx="2"/>'
        '<line x1="6" y1="6.5" x2="6.01" y2="6.5"/>'
        '<line x1="6" y1="17.5" x2="6.01" y2="17.5"/>'
    ),
    "back": '<line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>',
    "search": '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    "cancel": (
        '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/>'
        '<line x1="9" y1="9" x2="15" y2="15"/>'
    ),
    "check": '<polyline points="20 6 9 17 4 12"/>',
    "gap": (
        '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 '
        '3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/>'
        '<line x1="12" y1="17" x2="12.01" y2="17"/>'
    ),
    "pdf": (
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<polyline points="14 2 14 8 20 8"/>'
    ),
    "add_client": (
        '<path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>'
        '<circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/>'
        '<line x1="23" y1="11" x2="17" y2="11"/>'
    ),
    "wipe": (
        '<polyline points="3 6 5 6 21 6"/>'
        '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 '
        '2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/>'
        '<line x1="14" y1="11" x2="14" y2="17"/>'
    ),
    "delete": (
        '<polyline points="3 6 5 6 21 6"/>'
        '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 '
        '2 0 0 1 2 2v2"/>'
    ),
    "edit": (
        '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>'
        '<path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>'
    ),
    "excel": (
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<polyline points="14 2 14 8 20 8"/><line x1="9" y1="12" x2="15" y2="18"/>'
        '<line x1="15" y1="12" x2="9" y2="18"/>'
    ),
    "calendar": (
        '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>'
        '<line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/>'
        '<line x1="3" y1="10" x2="21" y2="10"/>'
    ),
    "menu": (
        '<line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/>'
        '<line x1="3" y1="18" x2="21" y2="18"/>'
    ),
    "manual": (
        '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>'
        '<path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>'
    ),
    "tour": (
        '<circle cx="12" cy="12" r="10"/>'
        '<path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>'
        '<line x1="12" y1="17" x2="12.01" y2="17"/>'
    ),
    "income": '<polyline points="17 11 12 6 7 11"/><line x1="12" y1="6" x2="12" y2="18"/>',
    "expense": '<polyline points="7 13 12 18 17 13"/><line x1="12" y1="18" x2="12" y2="6"/>',
    # Εξωτερικός σύνδεσμος: «άνοιγμα στον browser» για τα μόνο-online παραστατικά.
    "link": (
        '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'
        '<polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>'
    ),
}

_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="{color}" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round">{body}</svg>'
)

_cache: dict[tuple[str, str, int], QIcon] = {}


def icon(name: str, color: str = "#e6edf6", size: int = 20) -> QIcon:
    """Εικονίδιο βαμμένο στο χρώμα που ζητήθηκε."""
    key = (name, color, size)
    if key in _cache:
        return _cache[key]

    body = _SVG.get(name)
    if body is None:
        return QIcon()

    svg = _TEMPLATE.format(color=color, body=body)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()

    result = QIcon(pixmap)
    _cache[key] = result
    return result


#: Το ✓ των checkbox. Ξεχωριστό από το "check" των κουμπιών: σε 14 pixel μια
#: γραμμή πάχους 2 χάνεται, ενώ οι στρογγυλεμένες άκρες γίνονται μουτζούρα.
_CHECK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="{color}" stroke-width="3.6" stroke-linecap="round" '
    'stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'
)

_indicator_cache: dict[tuple[str, int], str] = {}


def _ui_cache_dir() -> Path:
    import tempfile

    path = Path(tempfile.gettempdir()) / "timologio-ui"
    path.mkdir(parents=True, exist_ok=True)
    return path


def indicator_image(color: str, size: int = 14) -> str:
    """Γράφει το ✓ ως PNG και επιστρέφει διαδρομή για το `image:` του QSS.

    PNG και όχι SVG: το `image: url(...)` με SVG χρειάζεται το plugin
    imageformats/qsvg, που μπορεί να μη μπει στο bundle του PyInstaller — και
    τότε το κουτάκι θα έμενε βαμμένο αλλά κενό, δηλαδή ακριβώς το σφάλμα που
    διορθώνουμε. Το PNG διαβάζεται πάντα.

    Γράφεται και σε @2x ώστε σε οθόνη 150% να μη φαίνεται θολό — το Qt το
    διαλέγει μόνο του από τη σύμβαση ονόματος.
    """
    key = (color, size)
    if key in _indicator_cache:
        return _indicator_cache[key]

    stem = f"check-{color.lstrip('#')}-{size}"
    target = _ui_cache_dir() / f"{stem}.png"
    svg = _CHECK_SVG.format(color=color)
    for scale, path in ((1, target), (2, target.with_name(f"{stem}@2x.png"))):
        pixmap = QPixmap(QSize(size * scale, size * scale))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
        painter.end()
        pixmap.save(str(path), "PNG")

    # Το QSS θέλει καθέτους μπροστά ακόμη και στα Windows.
    result = str(target).replace("\\", "/")
    _indicator_cache[key] = result
    return result


_logo_cache: dict[int, QPixmap] = {}


def _logo_path() -> Path | None:
    """Το logo.svg, από το bundle ή από τον φάκελο του έργου."""
    candidates: list[Path] = []
    base = getattr(sys, "_MEIPASS", "")
    if base:
        candidates.append(Path(base) / "logo.svg")
    here = Path(__file__).resolve()
    candidates.append(here.parents[3] / "installer" / "logo.svg")
    for path in candidates:
        if path.exists():
            return path
    return None


def logo_pixmap(size: int = 38) -> QPixmap:
    """Το λογότυπο για μέσα στην εφαρμογή.

    Επιστρέφει κενό pixmap αν λείπει το SVG — ένα λογότυπο που λείπει δεν είναι
    λόγος να μην ανοίξει η εφαρμογή.
    """
    if size in _logo_cache:
        return _logo_cache[size]
    path = _logo_path()
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)
    if path is not None:
        renderer = QSvgRenderer(str(path))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
    _logo_cache[size] = pixmap
    return pixmap

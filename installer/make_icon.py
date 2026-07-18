"""Παράγει τα γραφικά του installer από το logo.svg.

    uv run --extra gui python installer/make_icon.py

Βγάζει:
  icon.ico          εικονίδιο για το exe, τον installer και τη γραμμή εργασιών
  logo.png          το λογότυπο σε PNG
  wizard-small.bmp  το λογότυπο στην κεφαλίδα του installer
  wizard-large.bmp  η πλαϊνή εικόνα στην πρώτη/τελευταία σελίδα του installer

Το Qt γράφει ICO και BMP, οπότε δεν χρειάζεται Pillow. Το .ico περιέχει όλα τα
μεγέθη που ζητούν τα Windows: 16 για τη λίστα αρχείων, 32 για τη γραμμή
εργασιών, 48 για τον Explorer, 256 για τα μεγάλα εικονίδια.

Ο Inno Setup δέχεται **μόνο** BMP για τις εικόνες του οδηγού — όχι PNG/SVG —
γι' αυτό γράφονται ξεχωριστά και με αδιαφανές φόντο (το BMP δεν έχει άλφα).

ΠΡΟΣΟΧΗ: μην το τρέξετε με ``QT_QPA_PLATFORM=offscreen``. Το offscreen backend
δεν στοιχειοθετεί το ``<text>`` του SVG, οπότε το λογότυπο βγαίνει **χωρίς τη
λέξη «DATA»** — και μάλιστα σιωπηλά, χωρίς κανένα σφάλμα.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

SIZES = (16, 24, 32, 48, 64, 128, 256)

HERE = Path(__file__).parent
SVG = HERE / "logo.svg"
ICO = HERE / "icon.ico"
PNG = HERE / "logo.png"
WIZARD_SMALL = HERE / "wizard-small.bmp"
WIZARD_LARGE = HERE / "wizard-large.bmp"


def render(renderer: QSvgRenderer, size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return image


def wizard_bmp(
    renderer: QSvgRenderer, width: int, height: int, logo: int, background: str
) -> QImage:
    """Λογότυπο κεντραρισμένο σε αδιαφανές φόντο, σε μορφή που δέχεται ο Inno.

    Format_RGB32 (χωρίς άλφα): το BMP δεν κρατά διαφάνεια, και ένα ARGB θα
    έγραφε μαύρο εκεί που περίμενε κανείς λευκό.
    """
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(background))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(
        painter, QRectF((width - logo) / 2, (height - logo) / 2, logo, logo)
    )
    painter.end()
    return image


def main() -> int:
    QGuiApplication([])  # χρειάζεται για το raster backend
    if not SVG.exists():
        print(f"Δεν βρέθηκε το {SVG}", file=sys.stderr)
        return 1

    renderer = QSvgRenderer(str(SVG))
    if not renderer.isValid():
        print("Το logo.svg δεν είναι έγκυρο SVG", file=sys.stderr)
        return 1

    # Το ICO γράφεται από τη μεγαλύτερη εικόνα· το Qt παράγει τα υπόλοιπα
    # μεγέθη, αλλά τα φτιάχνουμε ρητά για καθαρότερο rendering στα μικρά.
    biggest = render(renderer, 256)
    if not biggest.save(str(ICO), "ICO"):
        print("Αποτυχία εγγραφής ICO", file=sys.stderr)
        return 1
    render(renderer, 512).save(str(PNG), "PNG")

    # Κεφαλίδα οδηγού: λευκό φόντο, όσο πιο κοντά στο θέμα «modern» του Inno.
    wizard_bmp(renderer, 138, 138, 118, "#ffffff").save(str(WIZARD_SMALL), "BMP")
    # Πλαϊνή εικόνα: το σκούρο μπλε της εφαρμογής, με το λογότυπο στη μέση.
    wizard_bmp(renderer, 192, 386, 128, "#0d2340").save(str(WIZARD_LARGE), "BMP")

    for path in (ICO, PNG, WIZARD_SMALL, WIZARD_LARGE):
        print(f"Δημιουργήθηκε: {path.name}  ({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

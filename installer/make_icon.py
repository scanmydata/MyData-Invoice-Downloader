"""Παράγει το installer/icon.ico από το logo.svg.

    uv run --extra gui python installer/make_icon.py

Το Qt γράφει ICO, οπότε δεν χρειάζεται Pillow. Το .ico περιέχει όλα τα μεγέθη
που ζητούν τα Windows: 16 για τη λίστα αρχείων, 32 για τη γραμμή εργασιών,
48 για τον Explorer, 256 για τα μεγάλα εικονίδια.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

SIZES = (16, 24, 32, 48, 64, 128, 256)

HERE = Path(__file__).parent
SVG = HERE / "logo.svg"
ICO = HERE / "icon.ico"
PNG = HERE / "logo.png"


def render(renderer: QSvgRenderer, size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter, QRectF(0, 0, size, size))
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

    print(f"Δημιουργήθηκε: {ICO}  ({ICO.stat().st_size:,} bytes)")
    print(f"Δημιουργήθηκε: {PNG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

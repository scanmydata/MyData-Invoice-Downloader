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

import struct
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


def _dib_entry(image: QImage) -> bytes:
    """Μία εικόνα ICO σε κλασική μορφή DIB (BITMAPINFOHEADER + BGRA + μάσκα).

    Τα μικρά μεγέθη γράφονται ως DIB και όχι ως PNG: το PNG μέσα σε ICO το
    δέχονται τα Windows από τα Vista και μετά, αλλά αρκετά σημεία του κελύφους
    (γραμμή εργασιών, Alt-Tab) το αγνοούν σιωπηλά στα μικρά μεγέθη και δείχνουν
    το γενικό εικονίδιο — ακριβώς το σύμπτωμα «χάθηκε το λογότυπο».
    """
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    width, height = image.width(), image.height()

    # Το ARGB32 του Qt είναι 0xAARRGGBB σε little-endian, δηλαδή bytes B,G,R,A —
    # ακριβώς η σειρά που θέλει το DIB. Οι γραμμές γράφονται από κάτω προς τα πάνω.
    rows = []
    for y in range(height - 1, -1, -1):
        rows.append(bytes(image.constScanLine(y))[: width * 4])
    xor = b"".join(rows)

    # Μάσκα διαφάνειας 1bpp, με γραμμές στοιχισμένες σε 4 bytes. Μένει μηδενική:
    # η διαφάνεια δίνεται από το κανάλι άλφα του 32bit XOR.
    mask_row = ((width + 31) // 32) * 4
    and_mask = b"\x00" * (mask_row * height)

    header = struct.pack(
        "<IiiHHIIiiII",
        40, width, height * 2, 1, 32, 0, len(xor) + len(and_mask), 0, 0, 0, 0,
    )
    return header + xor + and_mask


def write_ico(images: list[QImage], path: Path) -> None:
    """Γράφει ICO με όλα τα μεγέθη — το Qt γράφει μόνο ένα."""
    payloads = [_dib_entry(image) for image in images]

    offset = 6 + 16 * len(images)
    directory = b""
    for image, payload in zip(images, payloads):
        size = image.width()
        directory += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,
            0 if size >= 256 else size,
            0, 0, 1, 32, len(payload), offset,
        )
        offset += len(payload)

    path.write_bytes(
        struct.pack("<HHH", 0, 1, len(images)) + directory + b"".join(payloads)
    )


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

    # Κάθε μέγεθος ζωγραφίζεται ξεχωριστά από το SVG: μια υποβάθμιση του 256
    # στα 16 pixel μετατρέπει το λογότυπο σε θολή κηλίδα.
    write_ico([render(renderer, size) for size in SIZES], ICO)
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

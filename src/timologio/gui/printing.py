"""Μαζική εκτύπωση των PDF των επιλεγμένων παραστατικών.

Ο λογιστής θέλει συχνά να τυπώσει με τη μία όλα τα τιμολόγια που μόλις κατέβασε
(π.χ. για τον φάκελο ενός πελάτη). Εδώ φορτώνουμε κάθε PDF με το ``QtPdf`` και το
στέλνουμε σε **μία** εργασία εκτύπωσης, ώστε ο χρήστης να διαλέξει εκτυπωτή μία
φορά και να μη χρειάζεται να ανοίγει ένα-ένα τα αρχεία.

Γιατί render-σε-εικόνα και όχι απευθείας: το Qt δεν τυπώνει PDF κατευθείαν. Το
``QPdfDocument`` όμως στοιχειοθετεί τη σελίδα σε εικόνα, την οποία ζωγραφίζουμε
στον ``QPrinter``. Το DPI της απόδοσης το φράζουμε (RENDER_DPI) ώστε ένα A4 να
μη γίνεται εικόνα εκατοντάδων MB — για κείμενο τιμολογίου είναι υπεραρκετό.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import QDialog, QWidget

log = logging.getLogger(__name__)

#: Ανάλυση απόδοσης της σελίδας σε εικόνα. 200 DPI διαβάζεται άνετα και κρατά
#: μια σελίδα A4 γύρω στα ~15MP αντί για ~35MP στα 300 DPI.
RENDER_DPI = 200


def _load(doc: QPdfDocument, path: Path) -> bool:
    """Φορτώνει τοπικό PDF (σύγχρονο) και λέει αν είναι έτοιμο για απόδοση."""
    try:
        doc.load(str(path))
    except Exception:  # noqa: BLE001
        return False
    # Το None_ (=0) σημαίνει «καμία» βλάβη· κρατάμε και τον έλεγχο σελίδων ως
    # πρακτικό σήμα επιτυχίας, ανεξάρτητα από ονόματα enum ανά έκδοση.
    return doc.status() == QPdfDocument.Status.Ready and doc.pageCount() > 0


def print_pdfs(paths: list[Path], parent: QWidget | None = None) -> tuple[int, int, bool]:
    """Τυπώνει όλα τα PDF σε μία εργασία, αφού ο χρήστης διαλέξει εκτυπωτή.

    Επιστρέφει ``(τυπώθηκαν, απέτυχαν, ακυρώθηκε)``. ``ακυρώθηκε=True`` όταν ο
    χρήστης έκλεισε τον διάλογο εκτυπωτή — τότε δεν έγινε τίποτα.
    """
    paths = [p for p in paths if p.exists()]
    if not paths:
        return 0, 0, False

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    dialog = QPrintDialog(printer, parent)
    dialog.setWindowTitle("Μαζική εκτύπωση παραστατικών")
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return 0, 0, True

    painter = QPainter()
    if not painter.begin(printer):
        log.warning("Δεν άνοιξε ο εκτυπωτής για εκτύπωση")
        return 0, len(paths), False

    doc = QPdfDocument(parent)
    printed = failed = 0
    first_page = True
    try:
        for path in paths:
            if not _load(doc, path):
                failed += 1
                log.warning("Το PDF δεν φορτώθηκε για εκτύπωση: %s", path)
                continue
            for page in range(doc.pageCount()):
                if not first_page:
                    printer.newPage()
                first_page = False
                _draw_page(painter, printer, doc, page)
            printed += 1
    finally:
        painter.end()
        doc.close()
    return printed, failed, False


def _draw_page(
    painter: QPainter, printer: QPrinter, doc: QPdfDocument, page: int
) -> None:
    """Αποδίδει μία σελίδα σε εικόνα και τη ζωγραφίζει, κεντραρισμένη, στη σελίδα.

    Διατηρεί τις αναλογίες: ένα A4 τιμολόγιο δεν πρέπει να «τεντωθεί» στο πλάτος
    ενός φακέλου εκτυπωτή με άλλη αναλογία.
    """
    pt = doc.pagePointSize(page)  # σε points (1/72 ίντσας)
    w = max(1, round(pt.width() / 72.0 * RENDER_DPI))
    h = max(1, round(pt.height() / 72.0 * RENDER_DPI))
    image: QImage = doc.render(page, QSize(w, h))
    if image.isNull():
        return

    target = painter.viewport()  # εκτυπώσιμη περιοχή σε pixels συσκευής
    scaled = image.size().scaled(target.size(), Qt.AspectRatioMode.KeepAspectRatio)
    x = target.x() + (target.width() - scaled.width()) // 2
    y = target.y() + (target.height() - scaled.height()) // 2
    painter.drawImage(QRect(x, y, scaled.width(), scaled.height()), image)

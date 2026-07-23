"""Μαζική εκτύπωση των PDF των επιλεγμένων παραστατικών, με προεπισκόπηση.

Ο λογιστής θέλει συχνά να τυπώσει με τη μία όλα τα τιμολόγια που μόλις κατέβασε
(π.χ. για τον φάκελο ενός πελάτη). Ανοίγουμε **native προεπισκόπηση**
(``QPrintPreviewDialog``): ο χρήστης βλέπει όλες τις σελίδες, διαλέγει εκτυπωτή
και τυπώνει από τη γραμμή εργαλείων της προεπισκόπησης — μία εργασία, χωρίς να
ανοίγει ένα-ένα τα αρχεία.

Γιατί render-σε-εικόνα: το Qt δεν τυπώνει PDF κατευθείαν. Το ``QPdfDocument``
στοιχειοθετεί κάθε σελίδα σε εικόνα, την οποία ζωγραφίζουμε στον ``QPrinter``. Η
προεπισκόπηση ξαναζητά ζωγράφισμα σε κάθε zoom/σελιδοποίηση, οπότε κρατάμε
**cache** των εικόνων ανά σελίδα ώστε να μένει responsive.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QAction, QImage, QKeySequence, QPainter
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewWidget
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

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
    return doc.status() == QPdfDocument.Status.Ready and doc.pageCount() > 0


def print_pdfs(paths: list[Path], parent: QWidget | None = None) -> tuple[int, int]:
    """Ανοίγει προεπισκόπηση εκτύπωσης για όλα τα PDF. Επιστρέφει ``(έτοιμα,
    απέτυχαν)`` — «έτοιμα» = παραστατικά που μπήκαν στην προεπισκόπηση.

    Η ίδια η εκτύπωση γίνεται από τη γραμμή εργαλείων της προεπισκόπησης.
    """
    paths = [p for p in paths if p.exists()]
    if not paths:
        return 0, 0

    # Φορτώνουμε μία φορά κάθε έγγραφο· τα κρατάμε ζωντανά όσο ζει η
    # προεπισκόπηση ώστε να αποδίδουμε σελίδες on-demand.
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    docs: list[QPdfDocument] = []
    pages: list[tuple[QPdfDocument, int]] = []
    failed = 0
    try:
        for path in paths:
            doc = QPdfDocument(parent)
            if _load(doc, path):
                docs.append(doc)
                pages.extend((doc, i) for i in range(doc.pageCount()))
            else:
                failed += 1
                log.warning("Το PDF δεν φορτώθηκε για εκτύπωση: %s", path)
    finally:
        QApplication.restoreOverrideCursor()

    if not pages:
        return 0, failed

    cache: dict[tuple[int, int], QImage] = {}

    def render(printer: QPrinter) -> None:
        # Ο δείκτης αναμονής μπαίνει/βγαίνει ΜΕΣΑ στο render (ισοσκελισμένο), ώστε
        # να μη μένει ποτέ κολλημένος: παλιά τον βάζαμε γύρω από το exec() του
        # modal, οπότε έμενε «loading» σε όλη τη διάρκεια της προεπισκόπησης.
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        painter = QPainter()
        try:
            if not painter.begin(printer):
                return
            first = True
            for doc, page in pages:
                if not first:
                    printer.newPage()
                first = False
                _draw_page(painter, printer, doc, page, cache)
        finally:
            if painter.isActive():
                painter.end()
            QApplication.restoreOverrideCursor()

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)

    # Δικό μας παράθυρο προεπισκόπησης: το built-in QPrintPreviewDialog έβγαζε
    # κενό dropdown ζουμ, χωρίς hints και χωρίς ξεκάθαρο κουμπί εκτύπωσης. Εδώ
    # ελέγχουμε πλήρως τη γραμμή εργαλείων (κουμπί «Εκτύπωση», ζουμ, tooltips).
    dialog = QDialog(parent)
    dialog.setWindowTitle("Προεπισκόπηση εκτύπωσης")
    dialog.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)

    preview = QPrintPreviewWidget(printer, dialog)
    preview.paintRequested.connect(render)

    toolbar = QToolBar(dialog)
    toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)

    def add(text: str, tip: str, slot, shortcut=None) -> QAction:
        act = QAction(text, dialog)
        act.setToolTip(tip)
        act.setStatusTip(tip)
        if shortcut is not None:
            act.setShortcut(shortcut)
        act.triggered.connect(slot)
        toolbar.addAction(act)
        return act

    def do_print() -> None:
        pdlg = QPrintDialog(printer, dialog)
        pdlg.setWindowTitle("Εκτύπωση")
        if pdlg.exec() == QDialog.DialogCode.Accepted:
            preview.print_()  # -> paintRequested(printer) -> render()
            dialog.accept()

    add("🖨  Εκτύπωση…", "Επιλογή εκτυπωτή και εκτύπωση όλων των σελίδων",
        do_print, QKeySequence.StandardKey.Print)
    toolbar.addSeparator()
    add("Μεγέθυνση", "Μεγέθυνση της προεπισκόπησης", preview.zoomIn,
        QKeySequence.StandardKey.ZoomIn)
    add("Σμίκρυνση", "Σμίκρυνση της προεπισκόπησης", preview.zoomOut,
        QKeySequence.StandardKey.ZoomOut)
    add("Πλάτος", "Προσαρμογή στο πλάτος της σελίδας", preview.fitToWidth)
    add("Σελίδα", "Ολόκληρη η σελίδα στην οθόνη", preview.fitInView)
    toolbar.addSeparator()
    add("Κλείσιμο", "Κλείσιμο της προεπισκόπησης", dialog.reject,
        QKeySequence.StandardKey.Close)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addWidget(toolbar)
    layout.addWidget(preview, 1)
    if parent is not None:
        dialog.resize(parent.size())
    try:
        dialog.exec()
    finally:
        for doc in docs:
            doc.close()
    return len(docs), failed


def _draw_page(
    painter: QPainter,
    printer: QPrinter,
    doc: QPdfDocument,
    page: int,
    cache: dict[tuple[int, int], QImage],
) -> None:
    """Αποδίδει (με cache) μία σελίδα σε εικόνα και τη ζωγραφίζει κεντραρισμένη.

    Διατηρεί τις αναλογίες: ένα A4 τιμολόγιο δεν πρέπει να «τεντωθεί» στο πλάτος
    ενός φακέλου εκτυπωτή με άλλη αναλογία.
    """
    key = (id(doc), page)
    image = cache.get(key)
    if image is None:
        pt = doc.pagePointSize(page)  # σε points (1/72 ίντσας)
        w = max(1, round(pt.width() / 72.0 * RENDER_DPI))
        h = max(1, round(pt.height() / 72.0 * RENDER_DPI))
        image = doc.render(page, QSize(w, h))
        cache[key] = image
    if image.isNull():
        return

    target = painter.viewport()  # εκτυπώσιμη περιοχή σε pixels συσκευής
    scaled = image.size().scaled(target.size(), Qt.AspectRatioMode.KeepAspectRatio)
    x = target.x() + (target.width() - scaled.width()) // 2
    y = target.y() + (target.height() - scaled.height()) // 2
    painter.drawImage(QRect(x, y, scaled.width(), scaled.height()), image)

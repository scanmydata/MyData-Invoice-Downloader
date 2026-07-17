"""Entry point του desktop GUI."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ..crypto import SecretRedactingFilter

#: Δικό μας AppUserModelID. Χωρίς αυτό, τα Windows ομαδοποιούν το παράθυρο κάτω
#: από τον host (python.exe) και δείχνουν ΤΟ ΔΙΚΟ ΤΟΥ εικονίδιο στη γραμμή
#: εργασιών — γι' αυτό το λογότυπο «δεν εμφανιζόταν». Δηλώνοντας δική μας
#: ταυτότητα, τα Windows χρησιμοποιούν το εικονίδιο του παραθύρου παντού.
_APP_ID = "scanmydata.TimologioDownloader.gui.0.1.0"


def _set_app_user_model_id() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_APP_ID)
    except (OSError, AttributeError):
        pass


def main(argv: list[str] | None = None) -> int:
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(SecretRedactingFilter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])

    _set_app_user_model_id()

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Timologio Downloader")
    app.setOrganizationName("scanmydata")
    icon = app_icon()
    app.setWindowIcon(icon)

    # Το import γίνεται εδώ ώστε το QApplication να υπάρχει πριν από widgets.
    from .main_window import MainWindow

    window = MainWindow()
    # Ρητά και στο παράθυρο (όχι μόνο global): η γραμμή τίτλου και το alt-tab
    # διαβάζουν το εικονίδιο του παραθύρου, όχι πάντα το global του app.
    window.setWindowIcon(icon)
    window.show()
    return app.exec()


def app_icon() -> QIcon:
    """Το λογότυπο, από το bundle ή από τον φάκελο του έργου.

    Το PyInstaller ξεπακετάρει τα δεδομένα σε προσωρινό φάκελο και τα βάζει στο
    sys._MEIPASS· εκτός bundle ψάχνουμε δίπλα στον κώδικα.
    """
    base = Path(getattr(sys, "_MEIPASS", "")) if hasattr(sys, "_MEIPASS") else None
    candidates = []
    if base:
        candidates.append(base / "icon.ico")
    here = Path(__file__).resolve()
    candidates.append(here.parents[3] / "installer" / "icon.ico")
    candidates.append(here.parent / "icon.ico")
    for path in candidates:
        if path.exists():
            return QIcon(str(path))
    return QIcon()


if __name__ == "__main__":
    raise SystemExit(main())

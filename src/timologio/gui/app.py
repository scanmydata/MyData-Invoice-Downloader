"""Entry point του desktop GUI."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from ..crypto import SecretRedactingFilter
from . import i18n

log = logging.getLogger(__name__)

#: Δικό μας AppUserModelID. Χωρίς αυτό, τα Windows ομαδοποιούν το παράθυρο κάτω
#: από τον host (python.exe) και δείχνουν ΤΟ ΔΙΚΟ ΤΟΥ εικονίδιο στη γραμμή
#: εργασιών — γι' αυτό το λογότυπο «δεν εμφανιζόταν». Δηλώνοντας δική μας
#: ταυτότητα, τα Windows χρησιμοποιούν το εικονίδιο του παραθύρου παντού.
_APP_ID = "scanmydata.TimologioDownloader"


def _instance_key() -> str:
    """Μοναδικό όνομα socket ανά χρήστη-λογαριασμό.

    Δύο αντίγραφα στον ίδιο λογαριασμό μοιράζονται την ίδια βάση — μόνο ένα
    πρέπει να τρέχει. Το username στο κλειδί αφήνει διαφορετικούς χρήστες του
    ίδιου μηχανήματος (fast user switching) να τρέχουν ο καθένας το δικό του.
    """
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    return f"scanmydata.TimologioDownloader.{user}"


def _activate_running_instance() -> bool:
    """Αν τρέχει ήδη αντίγραφο, του ζητά να έρθει μπροστά.

    Επιστρέφει ``True`` αν βρέθηκε (οπότε ΑΥΤΟ το αντίγραφο πρέπει να βγει χωρίς
    να ανοίξει δεύτερο παράθυρο). Δουλεύει και όταν το άλλο αντίγραφο είναι
    μαζεμένο στο tray: του στέλνει «show» και εκείνο ξεμαζεύεται.
    """
    socket = QLocalSocket()
    socket.connectToServer(_instance_key())
    if not socket.waitForConnected(400):
        return False
    socket.write(b"show")
    socket.flush()
    socket.waitForBytesWritten(400)
    socket.disconnectFromServer()
    return True


def _install_instance_guard(window) -> QLocalServer | None:
    """Στήνει τον φρουρό μοναδικού instance και επιστρέφει τον server.

    Όσο ζει, κάθε νέο αντίγραφο που ξεκινά συνδέεται εδώ και φέρνει μπροστά το
    υπάρχον παράθυρο. Κρατήστε αναφορά στον server ώστε να μην τον μαζέψει ο
    garbage collector.
    """
    server = QLocalServer()
    # Καθάρισε τυχόν ορφανό socket από προηγούμενο crash — αλλιώς το listen
    # αποτυγχάνει με «address in use» και ο φρουρός δεν στήνεται ποτέ.
    QLocalServer.removeServer(_instance_key())
    if not server.listen(_instance_key()):
        log.warning("Ο φρουρός μοναδικού instance δεν στήθηκε: %s",
                    server.errorString())
        return None

    def _on_second_instance() -> None:
        conn = server.nextPendingConnection()
        if conn is not None:
            # Άδειασε ό,τι στάλθηκε και κλείσε — μας ενδιαφέρει μόνο το γεγονός.
            conn.readyRead.connect(conn.readAll)
            conn.disconnected.connect(conn.deleteLater)
        window.bring_to_front()

    server.newConnection.connect(_on_second_instance)
    return server


def _set_app_user_model_id() -> None:
    """Μόνο όταν τρέχουμε από πηγαίο κώδικα.

    Το πρόβλημα που λύνει υπάρχει μόνο εκεί: ο host είναι το python.exe, τα
    Windows ομαδοποιούν το παράθυρο κάτω από αυτό και δείχνουν το δικό του
    εικονίδιο.

    Στο πακεταρισμένο exe δεν χρειάζεται: η διεργασία είναι ήδη το
    TimologioDownloader.exe, που έχει το λογότυπο ενσωματωμένο ως resource και
    τα Windows το βρίσκουν μόνα τους. Ένα δικό μας AppUserModelID εκεί απλώς
    αντικαθιστά τη φυσική ταυτότητα του exe με ένα αναγνωριστικό που δεν
    αντιστοιχεί σε καμία εγκατεστημένη συντόμευση.

    ΣΗΜΕΙΩΣΗ: δοκιμάστηκε ως πιθανή αιτία για το γενικό εικονίδιο στη γραμμή
    εργασιών των Windows 11 και **δεν** ήταν αυτή — το σύμπτωμα παραμένει και
    χωρίς αυτή την κλήση, ακόμη και με τελείως άλλο, έγκυρο .ico. Η παράλειψη
    μένει γιατί είναι σωστή καθαυτή, όχι επειδή διορθώνει κάτι.
    """
    if os.name != "nt" or getattr(sys, "frozen", False):
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

    args = argv if argv is not None else sys.argv
    # Ο installer μας τρέχει με --show στο τέλος της εγκατάστασης, ώστε η πρώτη
    # εμφάνιση να γίνεται κανονικά (όχι μαζεμένη στο tray).
    force_show = "--show" in args

    app = QApplication(args)
    app.setApplicationName("Timologio Downloader")
    app.setOrganizationName("scanmydata")
    # Ελληνικά και για ό,τι γράφει το ίδιο το Qt (κουμπιά «Ναι/Άκυρο», μενού
    # δεξιού κλικ, ονόματα μηνών). Κρατιέται σε μεταβλητή: αν τον μαζέψει ο
    # garbage collector, το Qt ξαναγυρνά στα αγγλικά.
    app._greek = i18n.install(app)  # noqa: SLF001
    icon = app_icon()
    app.setWindowIcon(icon)
    # Με το tray, το παράθυρο μπορεί να είναι κρυμμένο ενώ η εφαρμογή δουλεύει.
    # Χωρίς αυτό, το πρώτο hide() θα τερμάτιζε τη διεργασία. Ο πραγματικός
    # τερματισμός γίνεται ρητά από το MainWindow.closeEvent.
    app.setQuitOnLastWindowClosed(False)

    # Πριν από κάθε βαρύ βήμα (ξεκλείδωμα, άνοιγμα βάσης): αν τρέχει ήδη
    # αντίγραφο, φέρ' το μπροστά και βγες σιωπηλά. Έτσι μια δεύτερη διπλή-κλικ
    # στη συντόμευση ανοίγει το ήδη ανοιχτό (ή μαζεμένο στο tray) παράθυρο αντί
    # για δεύτερο αντίγραφο.
    if _activate_running_instance():
        log.info("Τρέχει ήδη αντίγραφο — φέρνω μπροστά το υπάρχον παράθυρο.")
        return 0

    # Το import γίνεται εδώ ώστε το QApplication να υπάρχει πριν από widgets.
    from ..config import load_settings
    from .main_window import MainWindow
    from .unlock import ask_unlock

    # Πριν από οτιδήποτε άλλο: αν ο φάκελος δεδομένων είναι προστατευμένος, το
    # κλειδί πρέπει να ξεκλειδωθεί εδώ. Το MainWindow φτιάχνει Crypto στον
    # constructor του και θα έσκαγε με KeyfileLocked.
    if not ask_unlock(load_settings().enckey_path):
        return 1

    window = MainWindow(force_show=force_show)
    # Ρητά και στο παράθυρο (όχι μόνο global): η γραμμή τίτλου και το alt-tab
    # διαβάζουν το εικονίδιο του παραθύρου, όχι πάντα το global του app.
    window.setWindowIcon(icon)
    # Ο φρουρός μοναδικού instance μένει ζωντανός όσο ζει το παράθυρο· η αναφορά
    # πάνω στο window τον προστατεύει από τον garbage collector.
    window._single_instance_server = _install_instance_guard(window)  # noqa: SLF001
    # Το show() γίνεται πάντα· αν έχει επιλεγεί «εκκίνηση στο tray» (και δεν
    # είναι η πρώτη εμφάνιση μετά την εγκατάσταση), το MainWindow._setup_tray
    # κρύβει αμέσως το παράθυρο.
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

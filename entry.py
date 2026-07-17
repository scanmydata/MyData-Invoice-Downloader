"""Σημείο εισόδου για το PyInstaller.

Το bundle δεν έχει console, οπότε ένα σφάλμα κατά την εκκίνηση θα εξαφανιζόταν
σιωπηλά. Εδώ το πιάνουμε και το δείχνουμε σε παράθυρο — αλλιώς ο χρήστης βλέπει
απλώς ένα εικονίδιο που δεν ανοίγει.
"""

from __future__ import annotations

import sys
import traceback


def main() -> int:
    try:
        from timologio.gui.app import main as gui_main

        return gui_main(sys.argv)
    except Exception:
        detail = traceback.format_exc()
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(
                None,
                "Σφάλμα εκκίνησης",
                "Η εφαρμογή δεν μπόρεσε να ξεκινήσει.\n\n" + detail[:1500],
            )
        except Exception:
            print(detail, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

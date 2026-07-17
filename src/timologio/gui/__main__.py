"""Εκκίνηση με `python -m timologio.gui`.

Δεν ορίζουμε `[project.gui-scripts]` στο pyproject: το uv γράφει τότε έναν GUI
trampoline .exe, και η εγγραφή του αποτυγχάνει σε αυτό το μηχάνημα με
«Access is denied» — παρότι το site-packages και το Scripts είναι εγγράψιμα και
το Defender δεν καταγράφει τίποτα. Το `python -m` δεν χρειάζεται launcher, οπότε
παρακάμπτει όλη την κατηγορία προβλήματος.

Ο τελικός χρήστης δεν επηρεάζεται: εκείνος τρέχει το exe του PyInstaller.
"""

from __future__ import annotations

import sys

from .app import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

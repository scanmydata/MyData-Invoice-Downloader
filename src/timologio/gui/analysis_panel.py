"""Panel ανάλυσης ανά πελάτη.

Τα πλακίδια είναι κουμπιά: κλικ πάνω τους ανοίγει τον πίνακα παραστατικών
φιλτραρισμένο σε ακριβώς ό,τι μετράνε.
"""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..reports import ClientAnalysis, analyse_client
from .theme import CURRENT, money

#: Ρόλος όπου κρύβεται το κλειδί φίλτρου κάθε γραμμής (ΑΦΜ ή τύπος).
_KEY_ROLE = Qt.ItemDataRole.UserRole + 1


class StatTile(QPushButton):
    """Πλακίδιο-κουμπί: δείχνει έναν αριθμό και ανοίγει το τι μετράει."""

    # Το color δεν έχει προεπιλογή `CURRENT.accent`: οι προεπιλεγμένες τιμές
    # αποτιμώνται μία φορά, στο import, οπότε το πλακίδιο θα κρατούσε για πάντα
    # το χρώμα του θέματος που έτυχε να ισχύει τότε.
    def __init__(self, value: str, caption: str, color: str = "",
                 filter_key: str = "", tip: str = "") -> None:
        super().__init__()
        color = color or CURRENT.accent
        self.setObjectName("tile")
        self.filter_key = filter_key
        self.setCursor(Qt.CursorShape.PointingHandCursor if filter_key
                       else Qt.CursorShape.ArrowCursor)
        # Ελάχιστο πλάτος αντί για σταθερό: σε στενό παράθυρο τα πλακίδια
        # συρρικνώνονται αντί να ξεχειλίζουν το ένα πάνω στο άλλο.
        self.setMinimumWidth(92)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        box = QVBoxLayout(self)
        box.setContentsMargins(12, 9, 12, 9)
        box.setSpacing(1)
        v = QLabel(value)
        v.setObjectName("stat")
        v.setStyleSheet(f"color:{color}; background:transparent;")
        c = QLabel(caption)
        c.setObjectName("statLabel")
        c.setWordWrap(True)
        box.addWidget(v)
        box.addWidget(c)
        if tip:
            self.help_text = tip
            self.setToolTip(tip)

    # Το QPushButton υπολογίζει το μέγεθός του από το κείμενο/εικονίδιό του και
    # αγνοεί εντελώς το layout των παιδιών του. Χωρίς αυτά, το πλακίδιο
    # καταρρέει στο ύψος ενός άδειου κουμπιού και οι αριθμοί εξαφανίζονται.
    def sizeHint(self):  # noqa: N802 (Qt API)
        return self.layout().sizeHint()

    def minimumSizeHint(self):  # noqa: N802 (Qt API)
        return self.layout().minimumSize()


def _hint(text: str) -> QLabel:
    """Διακριτική υπόδειξη κάτω από πίνακα.

    Το ότι οι γραμμές είναι κλικαρίσιμες υπήρχε μόνο ως tooltip — δηλαδή το
    ήξερε όποιος το είχε ήδη ανακαλύψει.
    """
    label = QLabel(f"↗  {text}")
    label.setObjectName("hint")
    label.setWordWrap(True)
    return label


def _card(title: str = "") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 11, 14, 12)
    layout.setSpacing(8)
    if title:
        label = QLabel(title)
        label.setObjectName("statLabel")
        layout.addWidget(label)
    return frame, layout


def _mini_table(
    headers: list[str],
    rows: list[list[str]],
    aligns: list,
    keys: list[str] | None = None,
    tip: str = "",
) -> QTableWidget:
    """Μικρός πίνακας. Με `keys` οι γραμμές γίνονται κλικαρίσιμες."""
    table = QTableWidget(len(rows), len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    if keys:
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setCursor(Qt.CursorShape.PointingHandCursor)
    else:
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            item = QTableWidgetItem(value)
            item.setTextAlignment(aligns[c] | Qt.AlignmentFlag.AlignVCenter)
            if keys:
                item.setData(_KEY_ROLE, keys[r])
                if tip:
                    item.setToolTip(tip)
            table.setItem(r, c, item)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    table.setFixedHeight(min(32 + 27 * max(len(rows), 1), 214))
    return table


class AnalysisPanel(QScrollArea):
    """Σύνοψη για τον επιλεγμένο πελάτη."""

    filter_requested = Signal(str)      # κλικ σε πλακίδιο -> άνοιγμα παραστατικών
    supplier_requested = Signal(str)    # κλικ σε προμηθευτή -> φίλτρο ΑΦΜ
    type_requested = Signal(str)        # κλικ σε τύπο -> φίλτρο τύπου
    fill_gaps_requested = Signal(str)   # ISO|ISO

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tips: list[QWidget] = []
        self.show_placeholder()

    def _fresh_body(self) -> QVBoxLayout:
        """Νέο widget αντί για καθάρισμα του παλιού.

        Το προηγούμενο `_clear()` έσβηνε μόνο widgets· τα πλακίδια ζουν μέσα σε
        ένθετα layouts, οπότε επιβίωναν ως παιδιά του body και ζωγραφίζονταν από
        πάνω — τα «φαντάσματα» στο resize. Το setWidget() διαγράφει το παλιό
        δέντρο ολόκληρο, οπότε το πρόβλημα δεν μπορεί να ξανασυμβεί.
        """
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(9)
        self._tips = []
        self.setWidget(body)
        return layout

    def show_placeholder(self, text: str = "Επιλέξτε πελάτη για ανάλυση.") -> None:
        layout = self._fresh_body()
        label = QLabel(text)
        label.setObjectName("muted")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addStretch()

    def show_client(self, conn: sqlite3.Connection, vat: str) -> None:
        analysis = analyse_client(conn, vat)
        if analysis is None:
            self.show_placeholder("Ο πελάτης δεν βρέθηκε.")
            return
        layout = self._fresh_body()
        self._build(layout, analysis)
        layout.addStretch()

    def tooltip_widgets(self) -> list[QWidget]:
        return self._tips

    def _tile(self, layout: QHBoxLayout, tile: StatTile) -> None:
        if tile.filter_key:
            tile.clicked.connect(
                lambda _=False, k=tile.filter_key: self.filter_requested.emit(k)
            )
        if hasattr(tile, "help_text"):
            self._tips.append(tile)
        layout.addWidget(tile)

    def _build(self, root: QVBoxLayout, a: ClientAnalysis) -> None:
        title = QLabel(a.label or "—")
        title.setObjectName("h1")
        title.setWordWrap(True)
        root.addWidget(title)

        period = f"{_gr(a.first_date)} έως {_gr(a.last_date)}" if a.first_date else "καμία λήψη"
        sub = QLabel(f"ΑΦΜ {a.vat}  ·  {period}")
        sub.setObjectName("muted")
        root.addWidget(sub)

        # --- πλακίδια κατάστασης
        tiles = QHBoxLayout()
        tiles.setSpacing(7)
        self._tile(tiles, StatTile(str(a.total), "Παραστατικά", CURRENT.accent, "all",
                                   "Όλα τα παραστατικά — κλικ για τη λίστα"))
        self._tile(tiles, StatTile(str(a.downloaded), "Ελήφθησαν PDF", CURRENT.ok, "downloaded",
                                   "Κατέβηκαν από τον πάροχο — κλικ για τη λίστα"))
        self._tile(tiles, StatTile(str(a.no_provider_url), "Χωρίς PDF", CURRENT.muted,
                                   "no_provider_url",
                                   "Δεν πέρασαν από κανάλι παρόχου· αποθηκεύτηκε το XML"))
        if a.viewer_only:
            self._tile(tiles, StatTile(
                str(a.viewer_only), "Μόνο online", CURRENT.accent, "viewer_only",
                "Ο πάροχος (Epsilon, e-timologiera κ.ά.) δείχνει το παραστατικό "
                "μόνο online — δεν υπάρχει PDF για λήψη. Κλικ για τη λίστα· από "
                "εκεί ανοίγετε την προβολή του παρόχου."))
        if a.failed:
            self._tile(tiles, StatTile(str(a.failed), "Σφάλματα", CURRENT.bad, "failed",
                                       "Απέτυχε η λήψη — κλικ για τη λίστα"))
        root.addLayout(tiles)

        # --- έσοδα / έξοδα
        frame, layout = _card("ΕΣΟΔΑ / ΕΞΟΔΑ")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(3)
        for col, header in enumerate(["", "Πλήθος", "Καθαρή", "ΦΠΑ", "Σύνολο"]):
            h = QLabel(header)
            h.setObjectName("statLabel")
            if col:
                h.setAlignment(Qt.AlignmentFlag.AlignRight)
            grid.addWidget(h, 0, col)

        for row, (name, totals, color, key, tip) in enumerate(
            [
                ("Έσοδα", a.income, CURRENT.ok, "income",
                 "Παραστατικά που εξέδωσε ο πελάτης"),
                ("Έξοδα", a.expense, CURRENT.warn, "expense",
                 "Παραστατικά που εξέδωσαν άλλοι προς τον πελάτη, "
                 "και λιανικά έξοδα που δήλωσε ο ίδιος"),
            ],
            start=1,
        ):
            link = QPushButton(name)
            link.setObjectName("linkButton")
            link.setStyleSheet(f"color:{color}; font-weight:700; text-align:left;")
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            link.setToolTip(tip)
            link.help_text = tip
            self._tips.append(link)
            link.clicked.connect(lambda _=False, k=key: self.filter_requested.emit(k))
            grid.addWidget(link, row, 0)
            for col, value in enumerate(
                [str(totals.count), money(totals.net), money(totals.vat),
                 money(totals.gross)], start=1
            ):
                label = QLabel(value + (" €" if col > 1 else ""))
                label.setAlignment(Qt.AlignmentFlag.AlignRight)
                if col == 4:
                    label.setStyleSheet("font-weight:700;")
                grid.addWidget(label, row, col)
        grid.setColumnStretch(0, 1)
        layout.addLayout(grid)
        root.addWidget(frame)

        # --- χαρακτηρισμός
        frame, layout = _card("ΧΑΡΑΚΤΗΡΙΣΜΟΣ (RequestE3Info)")
        row = QHBoxLayout()
        row.setSpacing(7)
        for value, caption, color, key, tip in [
            (a.classified, "Χαρακτηρισμένα", CURRENT.ok, "classified",
             "Έχουν χαρακτηριστεί στα Ηλεκτρονικά Βιβλία"),
            (a.unclassified, "Αχαρακτήριστα", CURRENT.warn, "unclassified",
             "Η ΑΑΔΕ τα αναφέρει ως «ΜΗ ΧΑΡΑΚΤΗΡΙΣΜΕΝΑ ΕΞΟΔΑ» — θέλουν δουλειά"),
            (a.unknown_classification, "Χωρίς E3", CURRENT.muted, "unknown_cls",
             "Δεν υπόκεινται σε χαρακτηρισμό εξόδων (π.χ. δελτία διακίνησης)"),
        ]:
            self._tile(row, StatTile(str(value), caption, color, key, tip))
        layout.addLayout(row)
        root.addWidget(frame)

        # --- κάλυψη & κενά
        if a.covered or a.gaps:
            frame, layout = _card("ΚΑΛΥΨΗ ΗΜΕΡΟΜΗΝΙΩΝ")
            if a.covered:
                text = " · ".join(r.label() for r in a.covered[:4])
                if len(a.covered) > 4:
                    text += f" · +{len(a.covered) - 4}"
                covered = QLabel(f"Ελήφθησαν: {text}")
                covered.setWordWrap(True)
                covered.setToolTip("Διαστήματα που έχουν ζητηθεί από την ΑΑΔΕ")
                layout.addWidget(covered)
            if a.gaps:
                for gap in a.gaps[:5]:
                    line = QHBoxLayout()
                    warn = QLabel(f"⚠ Κενό: {gap.label()}  ({gap.days} ημέρες)")
                    warn.setStyleSheet(f"color:{CURRENT.warn};")
                    warn.setToolTip(
                        "Αυτό το διάστημα δεν ζητήθηκε ποτέ — μπορεί να λείπουν "
                        "παραστατικά."
                    )
                    line.addWidget(warn)
                    line.addStretch()
                    button = QPushButton("Λήψη κενού")
                    button.setToolTip(f"Λήψη παραστατικών για {gap.label()}")
                    button.clicked.connect(
                        lambda _=False, g=gap: self.fill_gaps_requested.emit(
                            f"{g.start}|{g.end}"
                        )
                    )
                    line.addWidget(button)
                    layout.addLayout(line)
            else:
                ok = QLabel("✓ Χωρίς κενά στις ημερομηνίες")
                ok.setStyleSheet(f"color:{CURRENT.ok};")
                layout.addWidget(ok)
            root.addWidget(frame)

        # --- κορυφαίοι προμηθευτές (κλικ -> φιλτραρισμένα παραστατικά)
        if a.top_suppliers:
            frame, layout = _card("ΚΟΡΥΦΑΙΟΙ ΠΡΟΜΗΘΕΥΤΕΣ (ανά αξία)")
            table = _mini_table(
                ["Επωνυμία", "ΑΦΜ", "Πλήθος", "Αξία"],
                [[name or "—", vat, str(count), f"{money(value)} €"]
                 for name, vat, count, value in a.top_suppliers],
                [Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignLeft,
                 Qt.AlignmentFlag.AlignRight, Qt.AlignmentFlag.AlignRight],
                keys=[vat for _, vat, _, _ in a.top_suppliers],
                tip="Κλικ για τα παραστατικά αυτού του προμηθευτή",
            )
            table.itemClicked.connect(
                lambda item: self.supplier_requested.emit(item.data(_KEY_ROLE) or "")
            )
            layout.addWidget(table)
            layout.addWidget(_hint("Πατήστε σε προμηθευτή για τα παραστατικά του."))
            root.addWidget(frame)

        # --- ανά τύπο (κλικ -> φιλτραρισμένα παραστατικά)
        if a.by_type:
            frame, layout = _card("ΑΝΑ ΤΥΠΟ ΠΑΡΑΣΤΑΤΙΚΟΥ")
            table = _mini_table(
                ["Τύπος", "Πλήθος", "Αξία"],
                [[t, str(c), f"{money(v)} €"] for t, c, v in a.by_type],
                [Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignRight,
                 Qt.AlignmentFlag.AlignRight],
                keys=[t for t, _, _ in a.by_type],
                tip="Κλικ για τα παραστατικά αυτού του τύπου",
            )
            table.itemClicked.connect(
                lambda item: self.type_requested.emit(item.data(_KEY_ROLE) or "")
            )
            layout.addWidget(_hint("Πατήστε σε τύπο για τα παραστατικά του."))
            layout.addWidget(table)
            root.addWidget(frame)


def _gr(iso: str) -> str:
    if not iso or len(iso) < 10:
        return iso or "—"
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"

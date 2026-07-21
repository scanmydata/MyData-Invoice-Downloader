"""Μικρά widgets που ξαναχρησιμοποιούνται σε πολλές σελίδες."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import (
    Property,
    QDate,
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QCheckBox, QDateEdit, QHeaderView, QTableWidget

from .theme import CURRENT


def _blend(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


class ToggleSwitch(QCheckBox):
    """Διακόπτης on/off αντί για τετράγωνο κουτάκι.

    Ζωγραφίζεται εξ ολοκλήρου εδώ και όχι μέσω stylesheet: το Qt δεν έχει
    sub-control για «κάψουλα με μπίλια», οπότε ένα QSS θα κατέληγε σε εικόνες
    ανά θέμα και ανά κατάσταση.
    """

    _W, _H, _PAD = 40, 22, 3

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._knob = 1.0 if self.isChecked() else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def checkStateSet(self) -> None:  # noqa: N802 (Qt API)
        """Η μπίλια ακολουθεί την κατάσταση — ακόμη και με μπλοκαρισμένα signals.

        Δεν ακούμε το `toggled`: η εκκίνηση κάνει `blockSignals(True)` για να
        θυμηθεί το αποθηκευμένο θέμα χωρίς να το ξαναεφαρμόσει, οπότε ο
        διακόπτης έδειχνε «κλειστό» ενώ το φωτεινό θέμα ήταν αναμμένο. Το
        checkStateSet είναι virtual, όχι signal, και καλείται πάντα.
        """
        super().checkStateSet()
        self._animate(self.isChecked())

    def nextCheckState(self) -> None:  # noqa: N802 (Qt API)
        """Το κλικ του χρήστη περνά από εδώ — όχι από το checkStateSet.

        Σε Qt 6.11 το πάτημα με το ποντίκι καλεί μόνο το nextCheckState (αλλάζει
        την κατάσταση και εκπέμπει το toggled), ενώ το checkStateSet καλείται
        μόνο μέσω setChecked. Χωρίς αυτή την υπέρβαση η μπίλια έμενε ακίνητη σε
        κάθε κλικ: ο διακόπτης άλλαζε κατάσταση αλλά έμοιαζε «νεκρός».
        """
        super().nextCheckState()
        self._animate(self.isChecked())

    def _animate(self, on: bool) -> None:
        target = 1.0 if on else 0.0
        if self._knob == target:
            return
        self._anim.stop()
        self._anim.setStartValue(self._knob)
        self._anim.setEndValue(target)
        self._anim.start()

    def _get_knob(self) -> float:
        return self._knob

    def _set_knob(self, value: float) -> None:
        self._knob = value
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def sizeHint(self) -> QSize:
        width = self._W + (8 + self.fontMetrics().horizontalAdvance(self.text())
                           if self.text() else 0)
        return QSize(width, max(self._H + 4, self.fontMetrics().height() + 6))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos) -> bool:
        # Ολόκληρο το widget, ώστε να πιάνει και το κείμενο δίπλα στον διακόπτη.
        return self.rect().contains(pos)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        top = (self.height() - self._H) / 2
        track = QRectF(0, top, self._W, self._H)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(
            _blend(QColor(CURRENT.line), QColor(CURRENT.accent_deep), self._knob)
        )
        painter.drawRoundedRect(track, self._H / 2, self._H / 2)

        diameter = self._H - 2 * self._PAD
        travel = self._W - 2 * self._PAD - diameter
        painter.setBrush(
            _blend(QColor(CURRENT.muted), QColor(CURRENT.on_accent), self._knob)
        )
        painter.drawEllipse(
            QRectF(self._PAD + self._knob * travel, top + self._PAD, diameter, diameter)
        )

        if self.text():
            painter.setPen(QColor(CURRENT.txt if self.isEnabled() else CURRENT.muted))
            painter.drawText(
                self.rect().adjusted(self._W + 8, 0, 0, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.text(),
            )
        painter.end()


class GrDateEdit(QDateEdit):
    """Ημερομηνία με ημερολόγιο και ελληνική μορφή ηη/μμ/εεεε.

    Αντικατέστησε τα QLineEdit: το QDateEdit βάζει μόνο του τις καθέτους καθώς
    πληκτρολογεί ο χρήστης και δεν επιτρέπει να γραφτεί άκυρη ημερομηνία, οπότε
    το «31/02» δεν φτάνει ποτέ ως αίτημα στην ΑΑΔΕ.
    """

    def __init__(self, initial: date | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.setDisplayFormat("dd/MM/yyyy")
        self.setFixedWidth(128)
        # Χωρίς όριο, το βελάκι «κάτω» ταξιδεύει στο 1752.
        self.setMinimumDate(QDate(2000, 1, 1))
        self.setMaximumDate(QDate.currentDate().addYears(1))
        self.setDate(QDate(initial) if initial else QDate.currentDate())
        # Χωρίς keyboard tracking, το πεδίο δεν προσπαθεί να «διορθώσει» την
        # ημερομηνία σε κάθε πληκτρολόγηση — ο χρήστης γράφει ολόκληρη την
        # ημέρα/μήνα/έτος και μετά επικυρώνεται, αντί να πηδά ο κέρσορας.
        self.setKeyboardTracking(False)
        # StrongFocus (όχι WheelFocus): το πεδίο δέχεται ρόδα ΜΟΝΟ αφού το
        # κλικάρει ο χρήστης. Αλλιώς, κάθε κύλιση της σελίδας που περνούσε πάνω
        # από το πεδίο άλλαζε σιωπηλά την ημερομηνία — το κλασικό «η ημερομηνία
        # αλλάζει μόνη της» που έκανε το datepicker να μοιάζει ασταθές.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if not self.hasFocus():
            # Δεν το καταναλώνουμε: αφήνουμε τη σελίδα από κάτω να κυλήσει.
            event.ignore()
            return
        super().wheelEvent(event)

    def gr(self) -> str:
        return self.date().toString("dd/MM/yyyy")

    def set_gr(self, value: str) -> None:
        parsed = QDate.fromString(value, "dd/MM/yyyy")
        if not parsed.isValid():
            parsed = QDate.fromString(value, "yyyy-MM-dd")
        if parsed.isValid():
            self.setDate(parsed)


def persist_header(table: QTableWidget, prefs: QSettings, key: str):
    """Κάνει τις στήλες μετακινήσιμες και θυμάται πλάτη, σειρά και ταξινόμηση.

    Το κλειδί περιέχει το πλήθος στηλών: αν αργότερα προστεθεί στήλη, το παλιό
    state δεν ταιριάζει πια και το restoreState θα το απέρριπτε σιωπηλά,
    αφήνοντας τον χρήστη με «κολλημένα» πλάτη που δεν εξηγούνται.

    Επιστρέφει συνάρτηση που γράφει το state αμέσως, για όποιον χρειάζεται να
    το αποθηκεύσει συγχρονισμένα με κάτι άλλο.
    """
    header = table.horizontalHeader()
    header.setSectionsMovable(True)
    header.setFirstSectionMovable(False)  # το checkbox μένει πρώτο
    setting = f"header/{key}/{table.columnCount()}"

    state = prefs.value(setting)
    table._sort_chosen = bool(state) and header.restoreState(state)  # type: ignore[attr-defined]

    def save() -> None:
        prefs.setValue(setting, header.saveState())

    # Το sectionResized πυροδοτείται σε κάθε pixel του συρσίματος· χωρίς
    # debounce θα γράφαμε στο μητρώο δεκάδες φορές ανά κίνηση του ποντικιού.
    timer = QTimer(table)
    timer.setSingleShot(True)
    timer.setInterval(400)
    timer.timeout.connect(save)
    for signal in (header.sectionResized, header.sectionMoved,
                   header.sortIndicatorChanged):
        signal.connect(lambda *_: timer.start())

    def chosen(*_) -> None:
        table._sort_chosen = True  # type: ignore[attr-defined]

    header.sortIndicatorChanged.connect(chosen)
    return save


def resort(table: QTableWidget, default_column: int | None = None) -> None:
    """Ξαναταξινομεί έναν πίνακα αφού γεμίσει.

    Το setSortingEnabled(True) δεν αγγίζει όσες γραμμές υπάρχουν ήδη — ταξινομεί
    μόνο ό,τι μπει μετά. Χωρίς αυτό, η ταξινόμηση που διάλεξε ο χρήστης θα
    χανόταν σε κάθε ανανέωση του πίνακα.
    """
    header = table.horizontalHeader()
    if getattr(table, "_sort_chosen", False) and header.sortIndicatorSection() >= 0:
        table.sortItems(header.sortIndicatorSection(), header.sortIndicatorOrder())
    elif default_column is not None:
        table.sortItems(default_column, Qt.SortOrder.DescendingOrder)


class _FillColumn(QObject):
    """Δίνει σε μια στήλη ό,τι περισσεύει, χωρίς να την κλειδώνει.

    Το Stretch mode γεμίζει τον πίνακα αλλά κάνει τη στήλη **αδύνατη να συρθεί**
    — και είναι ακριβώς η στήλη (Επωνυμία / Αντισυμβαλλόμενος) που θέλει κανείς
    να φαρδύνει. Interactive + αυτό εδώ δίνει και τα δύο: γεμίζει μόνη της, μέχρι
    τη στιγμή που θα την πιάσει ο χρήστης· από εκεί και πέρα το πλάτος είναι
    δικό του και το θυμόμαστε.
    """

    def __init__(self, table: QTableWidget, column: int, prefs: QSettings, key: str,
                 save_state):
        super().__init__(table)
        self._table = table
        self._column = column
        self._prefs = prefs
        self._save_state = save_state
        self._setting = f"header/{key}/{table.columnCount()}/manual"
        self._manual = bool(prefs.value(self._setting, False, type=bool))
        self._guard = False

        header = table.horizontalHeader()
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.sectionResized.connect(self._on_resized)
        table.viewport().installEventFilter(self)

    def _on_resized(self, index: int, _old: int, _new: int) -> None:
        if index == self._column and not self._guard:
            # Ο χρήστης την έπιασε: από εδώ και πέρα δεν την ξαναπειράζουμε.
            self._manual = True
            self._prefs.setValue(self._setting, True)
            # Η σημαία και το πλάτος γράφονται μαζί. Το state αποθηκεύεται
            # κανονικά με καθυστέρηση 400ms· αν έκλεινε κανείς την εφαρμογή
            # ενδιάμεσα, θα θυμόμασταν «ο χρήστης διάλεξε πλάτος» χωρίς να
            # ξέρουμε ποιο — και η στήλη θα έμενε για πάντα στα 100 pixel.
            self._save_state()
        elif not self._manual:
            # Άλλη στήλη άλλαξε — μαζεύουμε ή δίνουμε τη διαφορά.
            self.fit()

    def eventFilter(self, watched, event) -> bool:
        if event.type() is QEvent.Type.Resize and not self._manual:
            self.fit()
        return False

    def fit(self) -> None:
        header = self._table.horizontalHeader()
        others = sum(
            header.sectionSize(i)
            for i in range(self._table.columnCount())
            if i != self._column and not header.isSectionHidden(i)
        )
        room = self._table.viewport().width() - others
        if room < 140 or abs(room - header.sectionSize(self._column)) <= 1:
            return
        self._guard = True
        header.resizeSection(self._column, room)
        self._guard = False


def setup_columns(
    table: QTableWidget, spec: list[tuple[str, int, str]], prefs: QSettings, key: str
) -> None:
    """Στήνει τις στήλες ενός πίνακα από το spec (επικεφαλίδα, πλάτος, tooltip).

    Πλάτος 0 σημαίνει «πάρε ό,τι περισσεύει». Όλες οι στήλες είναι Interactive:
    καμία δεν είναι κλειδωμένη, όλες σύρονται και αναδιατάσσονται.
    """
    header = table.horizontalHeader()
    fill = -1
    for column, (_, width, tip) in enumerate(spec):
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        if width:
            table.setColumnWidth(column, width)
        else:
            fill = column
        item = table.horizontalHeaderItem(column)
        if item and tip:
            item.setToolTip(tip)

    save = persist_header(table, prefs, key)
    if fill >= 0:
        # Μετά το restoreState: αλλιώς το φίλτρο θα υπολόγιζε το κενό με τα
        # αρχικά πλάτη και θα ξανάγραφε αμέσως το αποθηκευμένο.
        table._fill_column = _FillColumn(  # type: ignore[attr-defined]
            table, fill, prefs, key, save
        )

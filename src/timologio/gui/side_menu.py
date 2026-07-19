"""Πλαϊνό μενού με λογότυπο, εικονίδια και κείμενο.

Ό,τι δεν είναι η καθημερινή δουλειά ζει εδώ, ώστε η κύρια οθόνη να μένει καθαρή.
Το μενού μαζεύεται σε μια λωρίδα εικονιδίων όταν ο χρήστης θέλει τον χώρο.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import APP_VERSION
from .icons import icon, logo_pixmap
from .theme import CURRENT
from .widgets import ToggleSwitch

# Το WIDE δεν είναι στρογγυλός αριθμός για την ομορφιά: στα 200 ο υπότιτλος
# «Λήψη Παραστατικών» ζητούσε 96px σε κουτί 94px και κοβόταν το τελευταίο
# γράμμα. Τα 226 αφήνουν ~12px περιθώριο, ώστε να αντέχει και μεγαλύτερη
# γραμματοσειρά συστήματος ή άλλη κλίμακα οθόνης.
WIDE, NARROW = 226, 58


#: Εικονίδιο ανά ενέργεια, όπου το όνομα της ενέργειας δεν είναι και όνομα
#: εικονιδίου. Χωρίς αυτό το `icon()` δεν έβρισκε σχέδιο για το «sync» και
#: γύριζε σιωπηλά άδειο QIcon — γι' αυτό η Λήψη και τα Παραστατικά έμεναν χωρίς
#: εικονίδιο ενώ όλα τα υπόλοιπα είχαν.
_ICONS = {
    "sync": "download",
    "documents": "pdf",
    "logfile": "csv",
    "password": "lock",
    "control": "network",
}


class MenuButton(QPushButton):
    def __init__(self, name: str, text: str, tip: str = "") -> None:
        super().__init__(text)
        self._name = name
        self._icon = _ICONS.get(name, name)
        self._label = text
        self._tip = tip
        self._active = False
        self.setObjectName("menuButton")
        self.setIconSize(QSize(18, 18))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.help_text = tip
        if tip:
            self.setToolTip(tip)
        self.restyle()

    def restyle(self) -> None:
        """Ξαναβάφει το εικονίδιο — το SVG είναι μονόχρωμο, οπότε πρέπει να
        ξαναφτιαχτεί όταν αλλάξει θέμα."""
        self.setIcon(icon(self._icon, CURRENT.accent if self._active else CURRENT.muted))

    def set_active(self, active: bool) -> None:
        self._active = active
        self.setProperty("active", active)
        self.restyle()
        # Το Qt δεν ξαναδιαβάζει το stylesheet μόνο του σε αλλαγή property.
        self.style().unpolish(self)
        self.style().polish(self)

    def set_collapsed(self, collapsed: bool) -> None:
        """Μαζεμένο: μόνο εικονίδιο, με το κείμενο να επιβιώνει ως tooltip.

        Χωρίς αυτό η λωρίδα θα ήταν εικονίδια χωρίς όνομα — αναγνωρίσιμα μόνο
        από όποιον ξέρει ήδη το πρόγραμμα.
        """
        self.setText("" if collapsed else self._label)
        full = f"{self._label} — {self._tip}" if self._tip else self._label
        self.help_text = full if collapsed else self._tip
        self.setToolTip(self.help_text)
        self.setProperty("help_text", self.help_text)


class SideMenu(QWidget):
    """Εκπέμπει το όνομα της ενέργειας· δεν ξέρει τι κάνει η καθεμιά."""

    triggered = Signal(str)
    tooltips_toggled = Signal(bool)
    theme_toggled = Signal(bool)  # True = φωτεινό
    collapsed_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sideMenu")
        self.setFixedWidth(WIDE)
        self._collapsed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)
        self._layout = layout

        layout.addWidget(self._header())
        layout.addSpacing(12)

        self._buttons: dict[str, MenuButton] = {}
        self._sections: list[QLabel] = []

        # Ο «Νέος πελάτης» πάνω από τη λίστα: είναι το πρώτο πράγμα που κάνει
        # κάποιος σε άδεια εγκατάσταση.
        self._add(layout, "add_client", "Νέος πελάτης",
                  "Προσθήκη πελάτη — χειροκίνητα ή από Excel")
        layout.addSpacing(6)

        # --- η καθημερινή ροή
        self._pages = ("clients", "sync", "documents")
        for name, text, tip in [
            ("clients", "Πελάτες", "Η λίστα των πελατών σας"),
            ("sync", "Λήψη", "Επιλογή πελατών, περιόδου και έναρξη λήψης"),
            ("documents", "Παραστατικά", "Τα παραστατικά του επιλεγμένου πελάτη"),
        ]:
            self._add(layout, name, text, tip)

        layout.addSpacing(10)
        layout.addWidget(self._separator("ΔΕΔΟΜΕΝΑ"))
        for name, text, tip in [
            ("folder", "Φάκελος αρχείων", "Άνοιγμα του φακέλου με τα PDF"),
            ("csv", "Εξαγωγή CSV",
             "Αναλυτική κατάσταση σε CSV — επιλέξτε πρώτα πελάτη/πελάτες"),
        ]:
            self._add(layout, name, text, tip)

        layout.addSpacing(10)
        layout.addWidget(self._separator("ΑΣΦΑΛΕΙΑ"))
        for name, text, tip in [
            ("backup", "Αντίγραφο ασφαλείας",
             "Αντίγραφο ασφαλείας της βάσης αυτή τη στιγμή"),
            ("restore", "Επαναφορά", "Επαναφορά της βάσης από αντίγραφο ασφαλείας"),
            ("password", "Κύριος κωδικός",
             "Προστασία του φακέλου δεδομένων με κωδικό"),
            ("wipe", "Εκκαθάριση",
             "Διαγραφή ληφθέντων παραστατικών και αρχείων — οι πελάτες μένουν"),
        ]:
            self._add(layout, name, text, tip)

        layout.addSpacing(10)
        layout.addWidget(self._separator("ΣΥΣΤΗΜΑ"))
        self._add(layout, "control", "Πίνακας ελέγχου",
                  "Συνδέσεις δικτύου, κατάσταση βάσης και ρυθμίσεις")

        layout.addSpacing(10)
        layout.addWidget(self._separator("ΒΟΗΘΕΙΑ"))
        for name, text, tip in [
            ("tour", "Ξενάγηση", "Σύντομη περιήγηση στις λειτουργίες της εφαρμογής"),
            ("manual", "Εγχειρίδιο PDF", "Άνοιγμα του πλήρους εγχειριδίου χρήσης"),
            ("logfile", "Αρχείο καταγραφής",
             "Άνοιγμα του αρχείου με το αναλυτικό ιστορικό"),
        ]:
            self._add(layout, name, text, tip)

        layout.addStretch()
        self._settings_label = self._separator("ΡΥΘΜΙΣΕΙΣ")
        layout.addWidget(self._settings_label)

        self.chk_light = ToggleSwitch("Φωτεινό θέμα")
        self.chk_light.setToolTip("Εναλλαγή ανάμεσα σε σκούρο και φωτεινό")
        self.chk_light.toggled.connect(self.theme_toggled.emit)
        layout.addWidget(self.chk_light)

        self.chk_tooltips = ToggleSwitch("Βοηθητικά μηνύματα")
        self.chk_tooltips.setChecked(True)
        self.chk_tooltips.setToolTip(
            "Εμφάνιση επεξηγήσεων όταν αφήνετε τον δείκτη πάνω από ένα κουμπί"
        )
        self.chk_tooltips.toggled.connect(self.tooltips_toggled.emit)
        layout.addWidget(self.chk_tooltips)

        layout.addSpacing(8)
        layout.addWidget(self._footer())

    # ------------------------------------------------------------------ UI
    def _header(self) -> QWidget:
        holder = QWidget()
        # Όταν το μενού δεν χωρά σε ύψος, το Qt συμπιέζει ό,τι μπορεί. Η
        # κεφαλίδα συρρικνωνόταν στα 31px ενώ το λογότυπο είναι 38, οπότε του
        # κοβόταν το κάτω μέρος. Το λογότυπο δεν είναι διαπραγματεύσιμο.
        holder.setMinimumHeight(38)
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(9)

        self.logo = QLabel()
        self.logo.setPixmap(logo_pixmap(38))
        self.logo.setFixedSize(38, 38)
        self.logo.setScaledContents(True)
        row.addWidget(self.logo)

        self._title_box = QWidget()
        text = QVBoxLayout(self._title_box)
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(0)
        title = QLabel("myDATA")
        title.setObjectName("menuTitle")
        sub = QLabel("Λήψη Παραστατικών")
        sub.setObjectName("menuSubtitle")
        text.addWidget(title)
        text.addWidget(sub)
        row.addWidget(self._title_box)
        row.addStretch()

        self.btn_toggle = QPushButton()
        self.btn_toggle.setObjectName("menuToggle")
        self.btn_toggle.setIcon(icon("menu", CURRENT.muted))
        self.btn_toggle.setIconSize(QSize(18, 18))
        self.btn_toggle.setFixedSize(30, 30)
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setToolTip("Σύμπτυξη/ανάπτυξη του μενού")
        self.btn_toggle.clicked.connect(lambda: self.set_collapsed(not self._collapsed))
        row.addWidget(self.btn_toggle)
        return holder

    def _footer(self) -> QWidget:
        """Λογότυπο και έκδοση στο κάτω μέρος."""
        holder = QWidget()
        holder.setMinimumHeight(22)  # ίδιος λόγος με την κεφαλίδα
        row = QHBoxLayout(holder)
        row.setContentsMargins(4, 0, 0, 0)
        row.setSpacing(8)

        self.logo_bottom = QLabel()
        self.logo_bottom.setPixmap(logo_pixmap(22))
        self.logo_bottom.setFixedSize(22, 22)
        self.logo_bottom.setScaledContents(True)
        row.addWidget(self.logo_bottom)

        self.version = QLabel(f"myDATA · έκδοση {APP_VERSION}")
        self.version.setObjectName("menuVersion")
        row.addWidget(self.version)
        row.addStretch()
        return holder

    def _add(self, layout: QVBoxLayout, name: str, text: str, tip: str) -> None:
        button = MenuButton(name, text, tip)
        button.clicked.connect(lambda _=False, n=name: self.triggered.emit(n))
        layout.addWidget(button)
        self._buttons[name] = button

    def _separator(self, text: str) -> QWidget:
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(6, 4, 0, 2)
        box.setSpacing(3)
        label = QLabel(text)
        label.setObjectName("menuSection")
        box.addWidget(label)
        self._sections.append(label)
        line = QFrame()
        line.setObjectName("line")
        box.addWidget(line)
        return holder

    # ------------------------------------------------------------ σύμπτυξη
    @property
    def collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool, *, animate: bool = True) -> None:
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        for button in self._buttons.values():
            button.set_collapsed(collapsed)
        for label in self._sections:
            label.setVisible(not collapsed)
        self._title_box.setVisible(not collapsed)
        self.version.setVisible(not collapsed)
        # Στη λωρίδα δεν χωρούν λογότυπο (38px) και ☰ (30px) μαζί. Φεύγει το
        # λογότυπο: χωρίς το ☰ δεν υπάρχει τρόπος να ξανανοίξει το μενού — και
        # το λογότυπο μένει ούτως ή άλλως στο κάτω μέρος.
        self.logo.setVisible(not collapsed)
        self.chk_light.setText("" if collapsed else "Φωτεινό θέμα")
        self.chk_tooltips.setText("" if collapsed else "Βοηθητικά μηνύματα")
        self._layout.setContentsMargins(*((8, 10, 8, 10) if collapsed
                                          else (10, 10, 10, 10)))

        target = NARROW if collapsed else WIDE
        if not animate:
            self.setFixedWidth(target)
        else:
            # Το πλάτος εκκίνησης διαβάζεται ΠΡΙΝ ξεκλειδώσουμε το maximumWidth:
            # αν το διαβάζαμε μετά, στο άνοιγμα το layout είχε ήδη επεκταθεί στο
            # WIDE, οπότε start == end και η κίνηση δεν φαινόταν — το μενού
            # «πεταγόταν» ανοιχτό ενώ το κλείσιμο κινούνταν ομαλά. Κρατάμε το
            # maximumWidth στο σημείο εκκίνησης ώστε να μην πηδήξει, και μετά το
            # κινούμε: έτσι άνοιγμα και κλείσιμο έχουν ακριβώς το ίδιο εφέ.
            start = self.width()
            self.setMinimumWidth(0)
            self.setMaximumWidth(start)
            anim = QPropertyAnimation(self, b"maximumWidth", self)
            anim.setDuration(160)
            anim.setStartValue(start)
            anim.setEndValue(target)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.finished.connect(lambda: self.setFixedWidth(target))
            anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self.collapsed_changed.emit(collapsed)

    # ------------------------------------------------------------------ API
    def restyle(self) -> None:
        """Μετά από αλλαγή θέματος: τα εικονίδια είναι bitmaps σε συγκεκριμένο
        χρώμα και δεν αλλάζουν μόνα τους από το stylesheet."""
        for button in self._buttons.values():
            button.restyle()
        self.btn_toggle.setIcon(icon("menu", CURRENT.muted))
        self.logo.setPixmap(logo_pixmap(38))
        self.logo_bottom.setPixmap(logo_pixmap(22))
        self.chk_light.update()
        self.chk_tooltips.update()

    def set_active(self, name: str) -> None:
        for key, button in self._buttons.items():
            if key in self._pages:
                button.set_active(key == name)

    def set_enabled_action(self, name: str, enabled: bool) -> None:
        if name in self._buttons:
            self._buttons[name].setEnabled(enabled)

    def button(self, name: str) -> MenuButton | None:
        return self._buttons.get(name)

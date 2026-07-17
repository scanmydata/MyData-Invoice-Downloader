"""Εγχειρίδιο χρήσης σε PDF.

Φτιάχνεται με Qt (QTextDocument + QPdfWriter) και όχι με βιβλιοθήκη PDF: το Qt
είναι ήδη εδώ, ξέρει ελληνικά και ξέρει να στοιχειοθετεί — μια εξάρτηση παραπάνω
θα πλήρωνε μόνο το privilege να ξαναγράψουμε τη σελιδοποίηση.
"""

from __future__ import annotations

import base64
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QMarginsF, QSizeF
from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument

from .icons import logo_pixmap
from .theme import LIGHT

VERSION = "0.1.0"
FILENAME = "Εγχειρίδιο χρήσης — Λήψη Παραστατικών myDATA.pdf"


def _logo_data_uri(size: int = 96) -> str:
    """Το λογότυπο ως data URI, για να ταξιδεύει μέσα στο ίδιο το HTML.

    Έτσι το έγγραφο δεν ψάχνει αρχείο στον δίσκο τη στιγμή της εκτύπωσης — μια
    διαδρομή που αλλάζει μέσα στο bundle του PyInstaller.
    """
    pixmap = logo_pixmap(size)
    if pixmap.isNull():
        return ""
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    buffer.close()
    return f"data:image/png;base64,{base64.b64encode(bytes(data)).decode('ascii')}"


def _html() -> str:
    p = LIGHT  # το χαρτί είναι λευκό — το σκούρο θέμα δεν τυπώνεται
    logo = _logo_data_uri()
    logo_tag = f'<img src="{logo}" width="86" height="86">' if logo else ""
    small_logo = f'<img src="{logo}" width="20" height="20">' if logo else ""

    return f"""
<html><body style="font-family:'Segoe UI',Calibri,sans-serif; color:{p.txt};">

<table width="100%"><tr>
  <td width="100">{logo_tag}</td>
  <td>
    <div style="font-size:26pt; font-weight:bold; color:{p.accent};">
      Λήψη Παραστατικών myDATA
    </div>
    <div style="font-size:13pt; color:{p.muted};">
      Εγχειρίδιο χρήσης &middot; έκδοση {VERSION}
    </div>
  </td>
</tr></table>

<hr color="{p.line}">

<p style="color:{p.muted};">
Η εφαρμογή κατεβάζει τα παραστατικά των πελατών σας από τα Ηλεκτρονικά Βιβλία
της ΑΑΔΕ (myDATA), τα αποθηκεύει ως PDF στον υπολογιστή σας με ονόματα που
διαβάζονται, και σας δείχνει τι λείπει και τι θέλει χαρακτηρισμό.
</p>

<h2 style="color:{p.accent};">1. Πριν ξεκινήσετε: το κλειδί myDATA</h2>
<p>
Για κάθε πελάτη χρειάζεστε δύο πράγματα, που τα εκδίδει <b>ο ίδιος ο υπόχρεος</b>
από το taxisnet (Ηλεκτρονικά Βιβλία myDATA &rarr; Εγγραφή στο myDATA REST API):
</p>
<ul>
  <li><b>Όνομα χρήστη</b> (aade-user-id)</li>
  <li><b>Κλειδί API</b> (Ocp-Apim-Subscription-Key)</li>
</ul>
<p style="color:{p.muted};">
Η εφαρμογή <b>δεν</b> μπορεί να τα δημιουργήσει. Όσοι πελάτες δεν τα έχουν
εμφανίζονται ως «Χωρίς κλειδί» και μπορείτε να βγάλετε λίστα τους σε CSV.
</p>

<h2 style="color:{p.accent};">2. Προσθήκη πελατών</h2>
<p><b>Ένας-ένας:</b> «Νέος πελάτης». Γράψτε το ΑΦΜ — μόλις συμπληρωθούν τα 9
ψηφία, η επωνυμία έρχεται μόνη της από το VIES. Συμπληρώστε όνομα χρήστη και
κλειδί.</p>
<p><b>Μαζικά:</b> στο ίδιο παράθυρο, «Εισαγωγή από Excel». Αναγνωρίζονται οι δύο
μορφές αρχείων που δίνει η ΑΑΔΕ. Το αρχείο δεν χρειάζεται να είναι καθαρό: όσες
γραμμές δεν έχουν κλειδί μπαίνουν ως «Χωρίς κλειδί».</p>

<h2 style="color:{p.accent};">3. Λήψη</h2>
<ol>
  <li><b>Περίοδος:</b> έτοιμα κουμπιά (μήνας, τρίμηνο, έτος) ή ημερομηνίες με
      ημερολόγιο.</li>
  <li><b>Είδος:</b> έσοδα (εκδοθέντα), έξοδα (ληφθέντα) ή και τα δύο. Ζητώντας
      μόνο το ένα, η λήψη τελειώνει στον μισό χρόνο.</li>
  <li><b>Πελάτες:</b> τσεκάρετε ποιοι. Χωρίς επιλογή, κατεβαίνουν όλοι οι
      διαθέσιμοι.</li>
</ol>
<p style="color:{p.muted};">
Η εφαρμογή ζητά κάθε φορά μόνο ό,τι είναι νεότερο από την προηγούμενη λήψη,
οπότε ένα δεύτερο τρέξιμο είναι σχεδόν ακαριαίο. Το «Πλήρης επανάληψη»
ξαναελέγχει ολόκληρο το διάστημα — τα ήδη κατεβασμένα αρχεία δεν ξανακατεβαίνουν.
</p>

<h2 style="color:{p.accent};">4. Παραστατικά</h2>
<p>
Ο πίνακας ανοίγει <b>στα αχαρακτήριστα</b>: αυτά είναι η μόνη εκκρεμότητα που
θέλει δουλειά από εσάς. Η μπλε ταινία το λέει ρητά — «Καθαρισμός» για να δείτε
τα πάντα.
</p>
<p>Τα τρία φίλτρα <b>συνδυάζονται</b>. Παραδείγματα:</p>
<ul>
  <li>Είδος «Έξοδα» + Λήψη «Ελήφθησαν PDF» &rarr; τα έξοδα που έχουν αρχείο.</li>
  <li>Είδος «Έξοδα» + Χαρακτηρισμός «Αχαρακτήριστα» &rarr; η λίστα εργασίας σας.</li>
  <li>Λήψη «Χωρίς PDF παρόχου» &rarr; όσα δεν πέρασαν από κανάλι παρόχου.</li>
</ul>
<p><b>Εξαγωγή σε ZIP:</b> τσεκάρετε παραστατικά και πατήστε «Εξαγωγή σε ZIP». Τα
αρχεία μπαίνουν χύμα, χωρίς υποφακέλους — το όνομα του καθενός έχει ήδη
προμηθευτή, ΑΦΜ, ημερομηνία, σειρά, Α/Α και αξία. Αν κάποια δεν έχουν PDF, η
εφαρμογή ρωτά αν θέλετε να μπουν με το XML της ΑΑΔΕ.</p>

<!-- Ρητή αλλαγή σελίδας: ο πίνακας που ακολουθεί δεν χωρά στην υπόλοιπη σελίδα
     και το Qt τον έκοβε στη μέση, στέλνοντας μια ορφανή γραμμή στην επόμενη. -->
<h2 style="color:{p.accent}; page-break-before:always;">
  5. Οι τρεις καταστάσεις χαρακτηρισμού
</h2>
<table width="100%" cellpadding="6" cellspacing="0" border="1"
       style="border-color:{p.line};">
  <tr style="background-color:{p.panel_alt};">
    <td width="30%"><b>Ένδειξη</b></td><td><b>Τι σημαίνει</b></td>
  </tr>
  <tr><td style="color:{p.ok};"><b>Χαρακτηρισμένο</b></td>
      <td>Έχει χαρακτηριστεί στα Ηλεκτρονικά Βιβλία.</td></tr>
  <tr><td style="color:{p.warn};"><b>Αχαρακτήριστο</b></td>
      <td>Η ΑΑΔΕ το αναφέρει ως «μη χαρακτηρισμένο έξοδο» — θέλει δουλειά.</td></tr>
  <tr><td style="color:{p.muted};"><b>&mdash;</b></td>
      <td>Δεν υπάρχει στοιχείο E3: <b>δεν</b> υπόκειται σε χαρακτηρισμό εξόδων.
          Η απουσία δεν σημαίνει εκκρεμότητα.</td></tr>
</table>

<h2 style="color:{p.accent};">6. Έσοδα και έξοδα</h2>
<p>
Η κατάταξη γίνεται από το <b>ΑΦΜ του εκδότη</b> και όχι από το αν το παραστατικό
ήρθε ως «εκδοθέν» ή «ληφθέν». Ο λόγος: τα παραστατικά τύπου 13.x και 14.x τα
υποβάλλει ο <i>λήπτης</i>, οπότε εμφανίζονται στα εκδοθέντα ενώ είναι έξοδα.
</p>

<h2 style="color:{p.accent};">7. Πού αποθηκεύονται</h2>
<p>
Στα Έγγραφά σας, στον φάκελο <b>Παραστατικά myDATA</b> (ή όπου τον ορίσατε στην
εγκατάσταση), σε υποφάκελο ανά πελάτη με ΑΦΜ και επωνυμία, και μετά ανά έτος και
μήνα. Τα ονόματα έχουν τη μορφή:
</p>
<p style="font-family:Consolas,monospace; background-color:{p.panel_alt};
          padding:8px; color:{p.txt};">
ΑΦΟΙ ΛΑΓΟΥ ΧΡΩΜΑΤΑ ΟΕ_800916954_2026-01-02_ΤΔΑ_1_40,29.pdf
</p>

<h2 style="color:{p.accent};">8. Ασφάλεια</h2>
<ul>
  <li>Τα κλειδιά αποθηκεύονται <b>κρυπτογραφημένα</b> και δεν εμφανίζονται ποτέ
      σε αρχεία καταγραφής.</li>
  <li>Πριν από κάθε επικίνδυνη ενέργεια κρατιέται <b>αντίγραφο</b> της βάσης.
      Η «Επαναφορά» σας γυρίζει πίσω.</li>
  <li>Η <b>Εκκαθάριση</b> σβήνει τα ληφθέντα και μηδενίζει το ιστορικό λήψης,
      ώστε η επόμενη λήψη να τα ξαναφέρει όλα. Οι πελάτες και τα κλειδιά τους
      παραμένουν.</li>
  <li>Η <b>Διαγραφή πελάτη</b> σβήνει τις εγγραφές του από τη βάση. Τα αρχεία
      PDF στον δίσκο <b>δεν</b> διαγράφονται.</li>
</ul>

<h2 style="color:{p.accent};">9. Σε τοπικό δίκτυο</h2>
<p>
Η εγκατάσταση ρωτά τον ρόλο του υπολογιστή: <b>αυτόνομος</b>, <b>server</b>
(κρατά τη βάση) ή <b>τερματικό</b> (τη διαβάζει από τον server). Όσο ένας
υπολογιστής κατεβάζει, οι υπόλοιποι βλέπουν «Εκτελείται ήδη λήψη» — σκόπιμο,
ώστε να μη ζητούν δύο μηχανήματα τα ίδια παραστατικά ταυτόχρονα.
</p>

<h2 style="color:{p.accent};">10. Όταν κάτι πάει στραβά</h2>
<table width="100%" cellpadding="6" cellspacing="0" border="1"
       style="border-color:{p.line};">
  <tr style="background-color:{p.panel_alt};">
    <td width="38%"><b>Τι βλέπετε</b></td><td><b>Τι σημαίνει</b></td>
  </tr>
  <tr><td>Χωρίς PDF παρόχου</td>
      <td>Το παραστατικό δεν πέρασε από κανάλι παρόχου. Δεν υπάρχει PDF να
          κατέβει — κρατιέται το XML της ΑΑΔΕ.</td></tr>
  <tr><td>Σφάλμα</td>
      <td>Ο πάροχος δεν απάντησε ή δεν έδωσε PDF. Ξαναδοκιμάζεται μόνο του·
          δείτε το αρχείο καταγραφής.</td></tr>
  <tr><td>Χωρίς κλειδί</td>
      <td>Λείπει το κλειδί myDATA του πελάτη (δείτε §1).</td></tr>
</table>
<p style="color:{p.muted};">
Το αναλυτικό ιστορικό, με ώρα Ελλάδας, γράφεται στο αρχείο καταγραφής:
μενού <b>Βοήθεια &rarr; Αρχείο καταγραφής</b>.
</p>

<hr color="{p.line}">
<p style="color:{p.muted}; font-size:9pt;">
{small_logo} Λήψη Παραστατικών myDATA &middot; έκδοση {VERSION} &middot;
Οι επωνυμίες συμπληρώνονται από τα ίδια τα παραστατικά, τη λίστα πελατών σας και
το VIES της Ευρωπαϊκής Επιτροπής.
</p>
</body></html>
"""


def build_manual(target: Path) -> Path:
    """Γράφει το εγχειρίδιο. Απαιτεί ενεργό QGuiApplication (offscreen αρκεί)."""
    target.parent.mkdir(parents=True, exist_ok=True)

    writer = QPdfWriter(str(target))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(16, 14, 16, 14), QPageLayout.Unit.Millimeter)
    writer.setTitle("Εγχειρίδιο χρήσης — Λήψη Παραστατικών myDATA")
    writer.setCreator("Λήψη Παραστατικών myDATA")
    writer.setResolution(96)

    doc = QTextDocument()
    doc.setHtml(_html())
    # Χωρίς αυτό το Qt στοιχειοθετεί σε πλάτος οθόνης και το κείμενο βγαίνει
    # έξω από το χαρτί.
    page = writer.pageLayout().paintRectPixels(writer.resolution())
    doc.setPageSize(QSizeF(page.size()))
    doc.print_(writer)
    return target


def ensure_manual(data_dir: Path) -> Path:
    """Η διαδρομή του εγχειριδίου, φτιάχνοντάς το αν λείπει.

    Γράφεται στον φάκελο δεδομένων και όχι δίπλα στο εκτελέσιμο: το Program
    Files δεν είναι εγγράψιμο για απλό χρήστη.
    """
    target = data_dir / FILENAME
    if not target.exists():
        build_manual(target)
    return target

# Σημειώσεις μηχανικής (memory)

Μακροχρόνιες αποφάσεις/παγίδες που δεν φαίνονται από τον κώδικα. Κράτα το σύντομο.

## Αυτόματη ενημέρωση (self-update) — «universal» σχεδίαση

**Στόχος:** να εγκαθίσταται η νέα έκδοση αξιόπιστα σε **κάθε** μηχάνημα, παρά τα
εμπόδια των Windows (Job Objects, πολιτικές, antivirus, κλειδωμένα αρχεία).

**Ροή** (`gui/updater.py` → `updates.py` → `installer/timologio.iss`):
1. Ο χρήστης πατά «Ενημέρωση τώρα» (ποτέ σιωπηλά).
2. **Backup** της βάσης (`backup.create_backup`) — πάντα πρώτο.
3. Κατέβασμα του `setup.exe` (GitHub release asset).
4. Γράφεται PowerShell script (`build_updater_script`) και ξεκινά **αποσπασμένα**
   (`launch_detached`): **primary = Task Scheduler** (`schtasks`), fallback =
   detached `Popen` με `CREATE_BREAKAWAY_FROM_JOB`.
5. Το script: περιμένει να κλείσει η εφαρμογή → σκοτώνει instances → τρέχει τον
   installer `/SILENT` → ξαναανοίγει με `--show`.

**Γιατί Task Scheduler primary:** πολλοί launchers βάζουν την εφαρμογή σε **Job
Object με kill-on-close**. Ένα απλό detached child πεθαίνει μαζί της· ένα
scheduled task τρέχει έξω από το job και επιβιώνει πάντα.

**Ρίζα προβλήματος «δούλευε σε άλλο PC, εδώ όχι» (μέχρι 0.2.25):** το script είχε
έναν βρόχο **ενεργής αναμονής ξεκλειδώματος** του exe
(`[IO.File]::Open($exe,...)`). Στα logs, μια αποτυχημένη ενημέρωση σταματούσε
**ακριβώς μετά το `instances stopped` και πριν το `running installer`** — δηλαδή
μέσα σ' αυτόν τον βρόχο (πιθανή διακοπή από AV/kill). Ήταν εύθραυστο σημείο.

**Universal λύση (0.2.26+):**
- **Αφαιρέθηκε** ο βρόχος `[IO.File]::Open`. Τα κλειδωμένα αρχεία τα κλείνει
  πλέον ο **Restart Manager του ίδιου του installer** — `CloseApplications=yes`
  στο `.iss` (+ `RestartApplications=no`, την επανεκκίνηση την κάνει ο updater).
  Έτσι η εγκατάσταση δεν εξαρτάται από το να «μαντέψει» ο updater πότε
  ξεκλείδωσαν τα αρχεία.
- Το script μπήκε σε **try/finally**: ό,τι κι αν στραβώσει, καταγράφεται (`ERROR:`)
  και η εφαρμογή **ξανανοίγει πάντα** (δεν μένει ο χρήστης χωρίς πρόγραμμα).
- **Ορατότητα:** ο installer γράφει μία-φορά σημαία μητρώου `ShowWindowOnce=1`
  (κάθε εγκατάσταση/ενημέρωση)· η εφαρμογή την καταναλώνει
  (`config.consume_show_once`) και ανοίγει **κανονικά** (όχι στο tray) στην πρώτη
  εκκίνηση, ανεξάρτητα από το μονοπάτι. Επιπλέον περνά `--show`.
- **Διατήρηση ρυθμίσεων** σε update: `/DIR` (ο φάκελος που τρέχει τώρα το exe),
  `/DATADIR`, `/ROLE`, `/TRAY`· ο installer προ-συμπληρώνει και από το μητρώο
  (`PreselectFromExistingInstall`).

**Παγίδα «έφτιαξε νέο φάκελο δεδομένων μόνο του» (0.2.27):** το
`Start-Process -ArgumentList @('a','b c')` του **Windows PowerShell 5.1** ΔΕΝ
βάζει εισαγωγικά στα στοιχεία του πίνακα — τα ενώνει με κενά. Έτσι το
`/DATADIR=C:\...\Παραστατικά myDATA` έσπαγε στο κενό: ο installer έβλεπε
`/DATADIR=C:\...\Παραστατικά`, έφτιαχνε ΝΕΟ άδειο φάκελο και έγραφε εκεί το
μητρώο → η εφαρμογή άνοιγε σε άδεια βάση. **Λύση:** διπλά εισαγωγικά ΜΕΣΑ στο
ίδιο το όρισμα για ΚΑΘΕ διαδρομή (`/DIR="..."`, `/LOG="..."`,
`/DATADIR="..."`) στο `build_updater_script` — το `CommandLineToArgvW` του
setup.exe τα δέχεται ολόκληρα (ο Inno αφαιρεί τα εισαγωγικά). Επιπλέον, ο
προεπιλεγμένος φάκελος εγκατάστασης διαβάζεται από το μητρώο
(`DefaultDirName={code:GetInstallDir}`), ώστε ακόμη και χειροκίνητη
επανεγκατάσταση χωρίς `/DIR` να πέφτει πάνω στην υπάρχουσα.

**Στοιχεία εκδότη / SmartScreen:** exe (PyInstaller `version_info`) και setup.exe
(Inno `VersionInfo*`) φέρουν ήδη πλήρη VersionInfo («scanmydata»). Το SmartScreen
θέλει ΨΗΦΙΑΚΗ ΥΠΟΓΡΑΦΗ (Authenticode) — χρειάζεται πιστοποιητικό code-signing.
Το `build.ps1` υπογράφει αυτόματα ΑΝ οριστεί (`TIMOLOGIO_SIGN_PFX`+`_PASS` ή
`TIMOLOGIO_SIGN_SHA1`)· αλλιώς παραλείπει σιωπηλά.

**Μέγεθος παραθύρου:** το αρχικό/ελάχιστο μέγεθος κλείνεται πάντα στη διαθέσιμη
οθόνη (`main_window` `screen().availableGeometry()`) — αλλιώς σε φορητούς η
γραμμή κατάστασης έβγαινε κάτω από την μπάρα εργασιών («σωστά μόνο σε full-screen»).

**Παγίδα «η αυτόματη ενημέρωση δεν δουλεύει σιωπηλά» (0.2.28):** το `schtasks`
έχει παρατηρηθεί να επιστρέφει **επιτυχία** ενώ το task μένει *Queued* και ΔΕΝ
εκτελείται ποτέ — τότε ο παλιός κώδικας γύριζε `True` και δεν δοκίμαζε ποτέ την
εφεδρεία. **Λύση:** το `launch_detached` παίρνει `run_log`+`start_token` και
**ΕΠΑΛΗΘΕΥΕΙ** ότι το script όντως ξεκίνησε (γράφει το token ως πρώτη ενέργεια)·
αν όχι, σβήνει το queued task και πέφτει στον detached-process τρόπο, κι αν
κανένας δεν τρέξει επιστρέφει `False` (μήνυμα για χειροκίνητη λήψη). Επίσης:
`schtasks` απορρίπτει `/TR` > **261 χαρακτήρες** (μεγάλο username/βαθύ %TEMP%) —
το ανιχνεύουμε και πάμε κατευθείαν στην εφεδρεία.

**Διάγνωση αποτυχίας — 2 logs στο `%TEMP%`:**
- `timologio_update_run.log` — τα βήματα του δικού μας script (start → instances
  stopped → running installer → installer exit=N → relaunched). Πού σταμάτησε =
  πού κόλλησε.
- `timologio_update_inno.log` — το log του ίδιου του Inno (δείχνει «Installation
  process succeeded» + πού εγκαταστάθηκε).

**Τι ΔΕΝ αλλάζουμε αλόγιστα:** την επιλογή Task-Scheduler-primary και το ρητό
`/DIR` — και τα δύο έχουν συγκεκριμένο λόγο ύπαρξης (Job Objects· χαμένο Inno
uninstall key). Δες τα σχόλια στο `updates.py`.

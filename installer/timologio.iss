; Inno Setup script — Timologio Downloader
;
; Εγκατάσταση ανά χρήστη (PrivilegesRequired=lowest): δεν ζητά δικαιώματα
; διαχειριστή και δεν εμφανίζει UAC, ώστε να μπορεί να το εγκαταστήσει ο
; οποιοσδήποτε στον υπολογιστή του.
;
; Build:  "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\timologio.iss

#define AppName        "Timologio Downloader"
#define AppVersion     "0.1.0"
#define AppPublisher   "scanmydata"
#define AppExeName     "TimologioDownloader.exe"

[Setup]
AppId={{8F3A6C21-4E9B-4A7D-9C15-7E2B4D8A1F03}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\TimologioDownloader
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=TimologioDownloader-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
; Εικονίδιο του ίδιου του setup.exe και γραφικά του οδηγού. Παράγονται από το
; logo.svg με το make_icon.py — ο Inno δέχεται μόνο .ico και .bmp εδώ.
SetupIconFile=icon.ico
WizardSmallImageFile=wizard-small.bmp
WizardImageFile=wizard-large.bmp
; Το λογότυπο είναι τετράγωνο· χωρίς αυτό ο Inno το τεντώνει στο πλάτος της
; πλαϊνής λωρίδας και παραμορφώνεται.
WizardImageStretch=no
; Το bundle είναι ~120MB· χωρίς αυτό ο installer μπορεί να χτυπήσει σε 32bit όριο.
LZMAUseSeparateProcess=yes

[Languages]
; Το Inno Setup 6 δεν συνοδεύεται από επίσημο Greek.isl, οπότε ξεκινάμε από το
; Default (αγγλικά) και αντικαθιστούμε inline τα μηνύματα που βλέπει ο χρήστης.
; Έτσι ο installer μένει αυτάρκης — χωρίς εξωτερικό αρχείο μετάφρασης.
Name: "el"; MessagesFile: "compiler:Default.isl"

[Messages]
el.SetupAppTitle=Εγκατάσταση
el.SetupWindowTitle=Εγκατάσταση — %1
el.WelcomeLabel1=Καλώς ήρθατε στην εγκατάσταση του [name]
el.WelcomeLabel2=Θα εγκατασταθεί το [name/ver] στον υπολογιστή σας.%n%nΚλείστε τυχόν άλλες εφαρμογές πριν συνεχίσετε.
el.ButtonNext=&Επόμενο >
el.ButtonBack=< &Πίσω
el.ButtonCancel=Άκυρο
el.ButtonInstall=&Εγκατάσταση
el.ButtonFinish=&Τέλος
el.ButtonBrowse=&Αναζήτηση…
el.SelectDirLabel3=Το [name] θα εγκατασταθεί στον παρακάτω φάκελο.
el.SelectDirBrowseLabel=Πατήστε Επόμενο για συνέχεια ή Αναζήτηση για άλλον φάκελο.
el.DiskSpaceGBLabel=Απαιτούνται τουλάχιστον [gb] GB ελεύθερου χώρου.
el.DiskSpaceMBLabel=Απαιτούνται τουλάχιστον [mb] MB ελεύθερου χώρου.
el.WizardSelectDir=Φάκελος εγκατάστασης
el.WizardSelectTasks=Πρόσθετες ενέργειες
el.SelectTasksDesc=Ποιες πρόσθετες ενέργειες να εκτελεστούν;
el.SelectTasksLabel2=Επιλέξτε τι θέλετε να γίνει και πατήστε Επόμενο.
el.WizardReady=Έτοιμο για εγκατάσταση
el.ReadyLabel1=Η εγκατάσταση είναι έτοιμη να ξεκινήσει.
el.ReadyLabel2a=Πατήστε Εγκατάσταση για να συνεχίσετε ή Πίσω για αλλαγές.
el.WizardInstalling=Εγκατάσταση σε εξέλιξη
el.InstallingLabel=Παρακαλώ περιμένετε…
el.FinishedHeadingLabel=Η εγκατάσταση ολοκληρώθηκε
el.FinishedLabel=Το [name] εγκαταστάθηκε στον υπολογιστή σας.
el.ClickFinish=Πατήστε Τέλος για έξοδο.
el.ExitSetupTitle=Έξοδος από την εγκατάσταση
el.ExitSetupMessage=Η εγκατάσταση δεν ολοκληρώθηκε. Θέλετε σίγουρα έξοδο;
el.ConfirmUninstall=Θέλετε σίγουρα να αφαιρέσετε το %1;%n%nΤα παραστατικά και η βάση ΔΕΝ θα διαγραφούν.
el.UninstalledAll=Το %1 αφαιρέθηκε. Ο φάκελος δεδομένων παραμένει.

[Tasks]
Name: "desktopicon"; Description: "Δημιουργία συντόμευσης στην Επιφάνεια Εργασίας"; GroupDescription: "Συντομεύσεις:"

[Files]
Source: "..\dist\TimologioDownloader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Φάκελος παραστατικών"; Filename: "{code:GetDataDir}"
Name: "{group}\Απεγκατάσταση {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; Η εφαρμογή διαβάζει από εδώ τον φάκελο δεδομένων (config.py:_data_dir_from_registry).
Root: HKCU; Subkey: "Software\scanmydata\TimologioDownloader"; ValueType: string; \
    ValueName: "DataDir"; ValueData: "{code:GetDataDir}"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\scanmydata\TimologioDownloader"; ValueType: string; \
    ValueName: "Role"; ValueData: "{code:GetRole}"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\scanmydata\TimologioDownloader"; ValueType: string; \
    ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletekey

[Dirs]
; uninsneveruninstall: χωρίς αυτό ο Inno αφαιρεί όσους από αυτούς είναι κενοί
; κατά την απεγκατάσταση. Ο φάκελος δεδομένων μένει πάντα, όπως υποσχεθήκαμε.
; Check: το τερματικό δεν φτιάχνει φακέλους στον server — τους έχει ήδη.
Name: "{code:GetDataDir}"; Flags: uninsneveruninstall; Check: ShouldCreateDataDirs
Name: "{code:GetDataDir}\data"; Flags: uninsneveruninstall; Check: ShouldCreateDataDirs
Name: "{code:GetDataDir}\backups"; Flags: uninsneveruninstall; Check: ShouldCreateDataDirs

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Εκκίνηση {#AppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Σβήνουμε ΜΟΝΟ ό,τι φτιάχνει το πρόγραμμα. Ο φάκελος δεδομένων με τα
; παραστατικά, τη βάση και το .enckey ΔΕΝ διαγράφεται ποτέ.
Type: filesandordirs; Name: "{app}"

[Code]
var
  RolePage: TInputOptionWizardPage;
  DataDirPage: TInputDirWizardPage;

const
  ROLE_STANDALONE = 0;
  ROLE_SERVER     = 1;
  ROLE_TERMINAL   = 2;

procedure InitializeWizard;
begin
  RolePage := CreateInputOptionPage(wpSelectDir,
    'Τρόπος λειτουργίας',
    'Πώς θα χρησιμοποιηθεί αυτός ο υπολογιστής;',
    'Η βάση και τα παραστατικά ζουν σε έναν φάκελο δεδομένων. Σε γραφείο με' + #13#10 +
    'πολλούς υπολογιστές, ο φάκελος βρίσκεται σε έναν (τον server) και οι' + #13#10 +
    'υπόλοιποι (τα τερματικά) τον χρησιμοποιούν μέσω δικτύου.',
    True, False);
  RolePage.Add('Αυτόνομος υπολογιστής — τα δεδομένα εδώ, χωρίς δίκτυο');
  RolePage.Add('Server — τα δεδομένα εδώ, θα τα βλέπουν και τα τερματικά');
  RolePage.Add('Τερματικό — τα δεδομένα σε δικτυακό φάκελο άλλου υπολογιστή');
  RolePage.SelectedValueIndex := ROLE_STANDALONE;

  DataDirPage := CreateInputDirPage(RolePage.ID,
    'Φάκελος δεδομένων',
    'Πού βρίσκονται τα παραστατικά και η βάση;',
    'Εδώ μπαίνουν τα PDF (ανά ΑΦΜ πελάτη / έτος / μήνα), η βάση με τους' + #13#10 +
    'πελάτες και τα κλειδιά, και τα αντίγραφα ασφαλείας.' + #13#10#13#10 +
    'Ο φάκελος ΔΕΝ διαγράφεται κατά την απεγκατάσταση.',
    False, '');
  DataDirPage.Add('');
  DataDirPage.Values[0] := ExpandConstant('{userdocs}\Παραστατικά myDATA');
end;

function GetDataDir(Param: String): String;
begin
  Result := DataDirPage.Values[0];
end;

function GetRole(Param: String): String;
begin
  case RolePage.SelectedValueIndex of
    ROLE_SERVER:   Result := 'server';
    ROLE_TERMINAL: Result := 'terminal';
  else
    Result := 'standalone';
  end;
end;

function IsTerminal: Boolean;
begin
  Result := RolePage.SelectedValueIndex = ROLE_TERMINAL;
end;

// Τα τερματικά δεν φτιάχνουν τους φακέλους: ο server τους έχει ήδη, και ένα
// τερματικό που «φτιάχνει» φακέλους σε λάθος διαδρομή κρύβει το πραγματικό
// πρόβλημα (χαλασμένο share) πίσω από μια δεύτερη, άδεια βάση.
function ShouldCreateDataDirs: Boolean;
begin
  Result := not IsTerminal;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = DataDirPage.ID then
  begin
    if IsTerminal then
    begin
      DataDirPage.SubCaptionLabel.Caption :=
        'Δώστε τον δικτυακό φάκελο του server, σε μορφή \\ΟΝΟΜΑ-SERVER\ΚΟΙΝΟΧΡΗΣΤΟΣ.' + #13#10 +
        'Πρέπει να υπάρχει ήδη και να έχετε δικαίωμα εγγραφής.';
      if Pos('\\', DataDirPage.Values[0]) <> 1 then
        DataDirPage.Values[0] := '\\SERVER\Παραστατικά myDATA';
    end
    else
    begin
      DataDirPage.SubCaptionLabel.Caption :=
        'Εδώ μπαίνουν τα PDF, η βάση και τα αντίγραφα ασφαλείας.' + #13#10 +
        'Ο φάκελος ΔΕΝ διαγράφεται κατά την απεγκατάσταση.';
      if Pos('\\', DataDirPage.Values[0]) = 1 then
        DataDirPage.Values[0] := ExpandConstant('{userdocs}\Παραστατικά myDATA');
    end;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Dir: String;
begin
  Result := True;
  if CurPageID <> DataDirPage.ID then
    Exit;

  Dir := DataDirPage.Values[0];
  if Dir = '' then
  begin
    MsgBox('Δώστε φάκελο δεδομένων.', mbError, MB_OK);
    Result := False;
    Exit;
  end;

  // Ο φάκελος δεδομένων μέσα στον φάκελο εγκατάστασης θα σβηνόταν στην
  // απεγκατάσταση μαζί με το {app} — και μαζί του τα παραστατικά.
  if Pos(Uppercase(ExpandConstant('{app}')), Uppercase(Dir)) = 1 then
  begin
    MsgBox('Ο φάκελος δεδομένων δεν πρέπει να είναι μέσα στον φάκελο ' +
           'εγκατάστασης, γιατί θα διαγραφεί κατά την απεγκατάσταση.' + #13#10#13#10 +
           'Επιλέξτε άλλον φάκελο.', mbError, MB_OK);
    Result := False;
    Exit;
  end;

  if IsTerminal then
  begin
    if Pos('\\', Dir) <> 1 then
    begin
      MsgBox('Σε λειτουργία τερματικού ο φάκελος πρέπει να είναι δικτυακός,' + #13#10 +
             'σε μορφή \\ΟΝΟΜΑ-SERVER\ΚΟΙΝΟΧΡΗΣΤΟΣ.' + #13#10#13#10 +
             'Χρησιμοποιήστε τη διαδρομή δικτύου και όχι γράμμα δίσκου: τα' + #13#10 +
             'mapped drives δεν είναι διαθέσιμα σε όλες τις συνεδρίες.',
             mbError, MB_OK);
      Result := False;
      Exit;
    end;
    // Χωρίς αυτόν τον έλεγχο, ένα τυπογραφικό στο όνομα του server θα φαινόταν
    // μόνο αργότερα, ως «άδεια λίστα πελατών».
    if not DirExists(Dir) then
    begin
      if MsgBox('Ο φάκελος δεν είναι προσβάσιμος:' + #13#10#13#10 + Dir + #13#10#13#10 +
                'Βεβαιωθείτε ότι ο server είναι ανοιχτός και ο φάκελος ' +
                'κοινόχρηστος.' + #13#10#13#10 + 'Συνέχεια;',
                mbConfirmation, MB_YESNO) = IDNO then
        Result := False;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ReadmePath: String;
  Extra: String;
begin
  if CurStep <> ssPostInstall then
    Exit;

  // Το τερματικό δεν γράφει οδηγίες στον φάκελο του server — τις έχει βάλει
  // ήδη ο server, και δεν θέλουμε δύο μηχανήματα να γράφουν το ίδιο αρχείο.
  if IsTerminal then
    Exit;

  if GetRole('') = 'server' then
    Extra :=
      'ΛΕΙΤΟΥΡΓΙΑ SERVER' + #13#10 +
      '-----------------' + #13#10 +
      'Για να συνδεθούν τα τερματικά, κάντε αυτόν τον φάκελο κοινόχρηστο:' + #13#10 +
      '  δεξί κλικ -> Ιδιότητες -> Κοινή χρήση -> Κοινή χρήση για συγκεκριμένους χρήστες' + #13#10 +
      '  Δώστε δικαίωμα ΑΝΑΓΝΩΣΗ/ΕΓΓΡΑΦΗ στους χρήστες του γραφείου.' + #13#10#13#10 +
      'Μετά, στα τερματικά τρέξτε τον installer και επιλέξτε «Τερματικό»,' + #13#10 +
      'δίνοντας τη διαδρομή \\' + ExpandConstant('{computername}') + '\<όνομα κοινόχρηστου>' + #13#10#13#10 +
      'ΠΡΟΣΟΧΗ: μόνο ΕΝΑΣ υπολογιστής μπορεί να κατεβάζει κάθε φορά. Οι' + #13#10 +
      'υπόλοιποι θα δουν μήνυμα ότι εκτελείται ήδη λήψη — αυτό είναι' + #13#10 +
      'σκόπιμο και προστατεύει τη βάση.' + #13#10#13#10
  else
    Extra := '';

  ReadmePath := GetDataDir('') + '\ΔΙΑΒΑΣΕ ΜΕ.txt';
  if not FileExists(ReadmePath) then
    SaveStringToFile(ReadmePath,
      'Φάκελος δεδομένων — Timologio Downloader' + #13#10 +
      '========================================' + #13#10#13#10 +
      Extra +
      'ΠΕΡΙΕΧΟΜΕΝΑ' + #13#10 +
      '-----------' + #13#10 +
      'data\<ΑΦΜ>\<έτος>\<μήνας>\  τα PDF των παραστατικών' + #13#10 +
      'timologio.db                η βάση (πελάτες, κλειδιά, ιστορικό)' + #13#10 +
      '.enckey                     το κλειδί κρυπτογράφησης των credentials' + #13#10 +
      'backups\                    αντίγραφα ασφαλείας της βάσης' + #13#10 +
      'sync.lock                   υπάρχει μόνο όσο τρέχει λήψη' + #13#10#13#10 +
      'ΠΡΟΣΟΧΗ: χωρίς το .enckey τα αποθηκευμένα κλειδιά δεν διαβάζονται.' + #13#10 +
      'Αν χαθεί, κάντε ξανά εισαγωγή του Excel με τους κωδικούς.' + #13#10#13#10 +
      'Ο φάκελος αυτός ΔΕΝ διαγράφεται κατά την απεγκατάσταση.' + #13#10,
      False);
end;


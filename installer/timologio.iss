; Inno Setup script — Timologio Downloader
;
; Εγκατάσταση ανά χρήστη (PrivilegesRequired=lowest): δεν ζητά δικαιώματα
; διαχειριστή και δεν εμφανίζει UAC, ώστε να μπορεί να το εγκαταστήσει ο
; οποιοσδήποτε στον υπολογιστή του.
;
; Build:  "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\timologio.iss

#define AppName        "Timologio Downloader"
#define AppVersion     "0.2.0"
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
el.ConfirmUninstall=Θέλετε σίγουρα να αφαιρέσετε το %1;%n%nΘα ερωτηθείτε ξεχωριστά αν θέλετε να διαγραφούν και τα δεδομένα σας (παραστατικά και βάση).
el.UninstalledAll=Το %1 αφαιρέθηκε.

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
    ValueName: "StartMinimized"; ValueData: "{code:GetStartMinimized}"; Flags: uninsdeletevalue
; HKCU\...\Run: αυτόματη εκκίνηση μόνο για τον χρήστη που εγκατέστησε, χωρίς
; δικαιώματα διαχειριστή.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
    ValueName: "TimologioDownloader"; ValueData: """{app}\{#AppExeName}"""; \
    Flags: uninsdeletevalue; Check: WantsAutostart
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
  TrayPage: TInputOptionWizardPage;
  TrayFromCommandLine: Boolean;
  DataDirFromCommandLine: Boolean;
  UninstDataDir: String;
  UninstRole: String;

const
  ROLE_STANDALONE = 0;
  ROLE_SERVER     = 1;
  ROLE_TERMINAL   = 2;
  OPT_TRAY      = 0;
  OPT_AUTOSTART = 1;

// Σιωπηλή εγκατάσταση σε πολλά μηχανήματα: χωρίς αυτό, ένα /SILENT θα έπαιρνε
// πάντα τις προεπιλογές (αυτόνομος, Έγγραφα) — άχρηστο για γραφείο με server.
//   setup.exe /SILENT /ROLE=terminal /DATADIR="\\SERVER\Παραστατικά myDATA"
//   setup.exe /SILENT /ROLE=server /TRAY=1
procedure ApplyCommandLine;
var
  Value: String;
begin
  Value := ExpandConstant('{param:ROLE|}');
  if CompareText(Value, 'server') = 0 then
    RolePage.SelectedValueIndex := ROLE_SERVER
  else if CompareText(Value, 'terminal') = 0 then
    RolePage.SelectedValueIndex := ROLE_TERMINAL
  else if CompareText(Value, 'standalone') = 0 then
    RolePage.SelectedValueIndex := ROLE_STANDALONE;

  Value := ExpandConstant('{param:DATADIR|}');
  if Value <> '' then
  begin
    DataDirPage.Values[0] := Value;
    DataDirFromCommandLine := True;
  end;

  Value := ExpandConstant('{param:TRAY|}');
  if Value <> '' then
  begin
    TrayPage.Values[OPT_TRAY] := Value = '1';
    TrayPage.Values[OPT_AUTOSTART] := Value = '1';
    TrayFromCommandLine := True;
  end;
end;

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

  // Checkboxes (Exclusive=False): οι δύο επιλογές είναι ανεξάρτητες.
  TrayPage := CreateInputOptionPage(DataDirPage.ID,
    'Εκκίνηση',
    'Πώς θα ξεκινά η εφαρμογή;',
    'Στον υπολογιστή που κρατά τα δεδομένα, η εφαρμογή συνήθως μένει ανοιχτή' + #13#10 +
    'όλη μέρα. Μαζεμένη στο tray (δίπλα στο ρολόι) δεν πιάνει χώρο και' + #13#10 +
    'ανοίγει με διπλό κλικ.',
    False, False);
  TrayPage.Add('Εκκίνηση μαζεμένη στο tray, δίπλα στο ρολόι');
  TrayPage.Add('Αυτόματη εκκίνηση με τα Windows');

  ApplyCommandLine;
end;

// Ο server προτείνεται μαζεμένος και αυτόματος· ο σταθμός εργασίας όχι, γιατί
// εκεί η εφαρμογή ανοίγει όταν τη χρειάζεται κάποιος.
procedure ApplyRoleDefaults;
var
  IsServer: Boolean;
begin
  if TrayFromCommandLine then
    Exit;
  IsServer := RolePage.SelectedValueIndex = ROLE_SERVER;
  TrayPage.Values[OPT_TRAY] := IsServer;
  TrayPage.Values[OPT_AUTOSTART] := IsServer;
end;

function GetStartMinimized(Param: String): String;
begin
  if TrayPage.Values[OPT_TRAY] then Result := '1' else Result := '0';
end;

function WantsAutostart: Boolean;
begin
  Result := TrayPage.Values[OPT_AUTOSTART];
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
  if CurPageID = TrayPage.ID then
    ApplyRoleDefaults;

  if CurPageID = DataDirPage.ID then
  begin
    // Ό,τι δόθηκε ρητά στη γραμμή εντολών δεν το πειράζουμε: αλλιώς μια
    // σιωπηλή εγκατάσταση τερματικού θα αντικαθιστούσε τη διαδρομή του
    // πελάτη με το δείγμα \SERVER\... και θα αποτύγχανε.
    if DataDirFromCommandLine then
      Exit;

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
      'Για να συνδεθούν τα τερματικά, ανοίξτε την εφαρμογή και πηγαίνετε:' + #13#10 +
      '  μενού -> ΣΥΣΤΗΜΑ -> Πίνακας ελέγχου -> Κοινή χρήση φακέλου...' + #13#10 +
      'Η εφαρμογή ρυθμίζει μόνη της κοινή χρήση, δικαιώματα και τείχος' + #13#10 +
      'προστασίας, και σας δίνει τη διαδρομή για τα τερματικά.' + #13#10#13#10 +
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
      '                            (μοναδικό για αυτή την εγκατάσταση)' + #13#10 +
      'backups\                    αντίγραφα ασφαλείας της βάσης' + #13#10 +
      'sync.lock                   υπάρχει μόνο όσο τρέχει λήψη' + #13#10#13#10 +
      'ΠΡΟΣΟΧΗ: χωρίς το .enckey τα αποθηκευμένα κλειδιά δεν διαβάζονται.' + #13#10 +
      'Αν χαθεί, κάντε ξανά εισαγωγή του Excel με τους κωδικούς.' + #13#10#13#10 +
      'ΓΙΑ ΜΕΓΙΣΤΗ ΠΡΟΣΤΑΣΙΑ: ορίστε κύριο κωδικό από το μενού της' + #13#10 +
      'εφαρμογής (ΑΣΦΑΛΕΙΑ -> Κύριος κωδικός). Τότε το .enckey δεν' + #13#10 +
      'ξεκλειδώνει χωρίς αυτόν, ακόμη κι αν αντιγραφεί όλος ο φάκελος.' + #13#10#13#10 +
      'Ο φάκελος αυτός ΔΕΝ διαγράφεται κατά την απεγκατάσταση.' + #13#10,
      False);
end;


// --------------------------------------------------------------- απεγκατάσταση
// Ο φάκελος δεδομένων δεν διαγράφεται ποτέ σιωπηλά. Αν όμως ο χρήστης
// ξεριζώνει έναν server ή έναν αυτόνομο υπολογιστή, τα PDF και η βάση θα
// έμεναν για πάντα σε έναν φάκελο που κανείς δεν θυμάται — γι' αυτό ρωτάμε.
// Το τερματικό ΔΕΝ ρωτιέται: ο φάκελος ανήκει στον server και μια διαγραφή από
// εκεί θα έσβηνε τα δεδομένα όλου του γραφείου.
function InitializeUninstall(): Boolean;
begin
  // ΚΡΙΣΙΜΟ: και τα δύο διαβάζονται ΕΔΩ. Στο usPostUninstall τα κλειδιά μητρώου
  // έχουν ήδη σβηστεί (uninsdeletevalue/uninsdeletekey), οπότε μια ανάγνωση
  // εκεί αποτυγχάνει σιωπηλά — και ο ρόλος θα έπεφτε πίσω στο 'standalone',
  // δηλαδή ένα τερματικό θα έσβηνε τα δεδομένα ΟΛΟΥ του γραφείου.
  if not RegQueryStringValue(HKCU, 'Software\scanmydata\TimologioDownloader',
                             'DataDir', UninstDataDir) then
    UninstDataDir := '';
  if not RegQueryStringValue(HKCU, 'Software\scanmydata\TimologioDownloader',
                             'Role', UninstRole) then
    UninstRole := '';
  Result := True;
end;

procedure DeleteDataDir;
begin
  if DelTree(UninstDataDir, True, True, True) then
    Log('Ο φάκελος δεδομένων διαγράφηκε: ' + UninstDataDir)
  else
    Log('Ο φάκελος δεδομένων ΔΕΝ διαγράφηκε: ' + UninstDataDir);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Role: String;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;

  Role := UninstRole;
  // Άγνωστος ρόλος σημαίνει ότι δεν μπορέσαμε να διαβάσουμε το μητρώο. Σε
  // αμφιβολία δεν σβήνουμε τίποτα: τα δεδομένα του πελάτη δεν είναι το σημείο
  // να ρισκάρουμε.
  if (Role = '') or (Role = 'terminal') then
    Exit;
  // Το τερματικό ΔΕΝ ρωτιέται ποτέ: ο φάκελος ανήκει στον server και μια
  // διαγραφή από εδώ θα έσβηνε τα δεδομένα όλου του γραφείου.
  if (UninstDataDir = '') or (not DirExists(UninstDataDir)) then
    Exit;

  // Σιωπηλή απεγκατάσταση: ποτέ διάλογος που θα κολλούσε το script. Η διαγραφή
  // γίνεται μόνο αν ζητηθεί ρητά:  unins000.exe /VERYSILENT /DELETEDATA=1
  if UninstallSilent then
  begin
    if ExpandConstant('{param:DELETEDATA|0}') = '1' then
      DeleteDataDir;
    Exit;
  end;

  if MsgBox('Να διαγραφούν και τα δεδομένα σας;' + #13#10#13#10 +
            UninstDataDir + #13#10#13#10 +
            'Περιλαμβάνει ΟΛΑ τα κατεβασμένα PDF και XML, τη βάση με τους' + #13#10 +
            'πελάτες και τα κλειδιά, και τα αντίγραφα ασφαλείας.' + #13#10#13#10 +
            'Η ενέργεια ΔΕΝ αναιρείται. Επιλέξτε «Όχι» αν σκοπεύετε να' + #13#10 +
            'επανεγκαταστήσετε ή αν κρατάτε τα παραστατικά για έλεγχο.' + #13#10#13#10 +
            'Διαγραφή δεδομένων;',
            mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES then
    Exit;

  // Δεύτερη ερώτηση: η πρώτη πατιέται εύκολα από συνήθεια, και μετά δεν
  // υπάρχει επιστροφή.
  if MsgBox('Τελευταία επιβεβαίωση.' + #13#10#13#10 +
            'Θα διαγραφεί οριστικά ο φάκελος:' + #13#10 + UninstDataDir + #13#10#13#10 +
            'Σίγουρα;', mbError, MB_YESNO or MB_DEFBUTTON2) <> IDYES then
    Exit;

  if DelTree(UninstDataDir, True, True, True) then
    MsgBox('Τα δεδομένα διαγράφηκαν.', mbInformation, MB_OK)
  else
    MsgBox('Ο φάκελος δεν διαγράφηκε πλήρως:' + #13#10 + UninstDataDir + #13#10#13#10 +
           'Πιθανόν κάποιο αρχείο να είναι ανοιχτό. Διαγράψτε τον ' +
           'χειροκίνητα αν θέλετε.', mbError, MB_OK);
end;

# Χτίζει το .exe και τον Windows installer.
#
#   powershell -ExecutionPolicy Bypass -File installer\build.ps1
#
# Παράγει:  dist\installer\TimologioDownloader-<έκδοση>-setup.exe
#
# Δουλεύει είτε με uv είτε με σκέτο .venv: σε μηχάνημα χωρίς uv (π.χ. καθαρός
# υπολογιστής γραφείου) το build δεν πρέπει να κολλάει σε εργαλείο ανάπτυξης.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# --- Πώς τρέχουμε python -----------------------------------------------------
$uv = (Get-Command uv -ErrorAction SilentlyContinue)
$venvPy = Join-Path $root ".venv\Scripts\python.exe"

if ($uv) {
    Write-Host "== 1/5  Εξαρτήσεις (uv) ==" -ForegroundColor Cyan
    uv sync --extra gui --group dev
    $py = { param($a) & uv run --extra gui python @a }
    $pyi = { param($a) & uv run --extra gui pyinstaller @a }
} elseif (Test-Path $venvPy) {
    Write-Host "== 1/5  Εξαρτήσεις (.venv) ==" -ForegroundColor Cyan
    Write-Host "   uv δεν βρέθηκε — χρησιμοποιώ το υπάρχον .venv" -ForegroundColor Yellow
    & $venvPy -m pip install --quiet pyinstaller
    $py = { param($a) & $venvPy @a }
    $pyi = { param($a) & $venvPy -m PyInstaller @a }
} else {
    throw "Δεν βρέθηκε ούτε uv ούτε .venv. Τρέξτε:  py -m venv .venv ; .venv\Scripts\pip install -e .[gui] pyinstaller"
}

$env:PYTHONPATH = Join-Path $root "src"

# --- Ψηφιακή υπογραφή (προαιρετική) ------------------------------------------
# Το exe και το setup.exe φέρουν ήδη πλήρη VersionInfo (εκδότης «scanmydata»),
# που μειώνει τα ψευδώς-θετικά. Ωστόσο, χωρίς ψηφιακή υπογραφή (Authenticode) το
# SmartScreen δείχνει πάντα «άγνωστος εκδότης». Η υπογραφή θέλει πιστοποιητικό
# code-signing. Αν οριστεί (μέσω μεταβλητών περιβάλλοντος), υπογράφουμε ΚΑΙ το
# exe ΚΑΙ το setup.exe· αλλιώς το βήμα παραλείπεται σιωπηλά. Έτσι το build είναι
# «universal»: μόλις αποκτηθεί πιστοποιητικό, η υπογραφή γίνεται αυτόματα.
#   $env:TIMOLOGIO_SIGN_PFX  = 'C:\path\cert.pfx'; $env:TIMOLOGIO_SIGN_PASS='...'
#   -ή- $env:TIMOLOGIO_SIGN_SHA1 = '<thumbprint πιστοποιητικού στο store>'
function Find-SignTool {
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $roots = @("${env:ProgramFiles(x86)}\Windows Kits\10\bin",
               "$env:ProgramFiles\Windows Kits\10\bin")
    foreach ($r in $roots) {
        if (Test-Path $r) {
            $exe = Get-ChildItem -Path $r -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -match '\\x64\\' } |
                Sort-Object FullName -Descending | Select-Object -First 1
            if ($exe) { return $exe.FullName }
        }
    }
    return $null
}

function Invoke-Sign($file) {
    $pfx  = $env:TIMOLOGIO_SIGN_PFX
    $sha1 = $env:TIMOLOGIO_SIGN_SHA1
    if (-not $pfx -and -not $sha1) { return }   # δεν ρυθμίστηκε υπογραφή — σιωπηλή παράλειψη
    $st = Find-SignTool
    if (-not $st) { throw "Ζητήθηκε υπογραφή αλλά δεν βρέθηκε το signtool.exe (Windows SDK)." }
    $ts = 'http://timestamp.digicert.com'
    if ($pfx) {
        & $st sign /fd SHA256 /f $pfx /p $env:TIMOLOGIO_SIGN_PASS /tr $ts /td SHA256 $file
    } else {
        & $st sign /fd SHA256 /sha1 $sha1 /tr $ts /td SHA256 $file
    }
    if ($LASTEXITCODE -ne 0) { throw "Η υπογραφή απέτυχε: $file" }
    Write-Host "   υπογράφηκε: $file" -ForegroundColor Green
}

# --- Γραφικά -----------------------------------------------------------------
# ΠΡΟΣΟΧΗ: χωρίς offscreen. Το offscreen backend δεν στοιχειοθετεί το <text> του
# SVG και το λογότυπο βγαίνει σιωπηλά χωρίς τη λέξη «DATA».
Write-Host "== 2/5  Εικονίδιο και γραφικά installer ==" -ForegroundColor Cyan
Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue
& $py @("installer\make_icon.py")

# --- Εγχειρίδιο --------------------------------------------------------------
Write-Host "== 3/5  Εγχειρίδιο PDF (docs\manual.pdf) ==" -ForegroundColor Cyan
& $py @("-c", @"
from pathlib import Path
from PySide6.QtGui import QGuiApplication
app = QGuiApplication([])
from timologio.gui.manual import build_manual
out = Path('docs/manual.pdf'); out.parent.mkdir(exist_ok=True)
build_manual(out)
print('  ', out, out.stat().st_size, 'bytes')
"@)

# --- PyInstaller -------------------------------------------------------------
Write-Host "== 4/5  PyInstaller ==" -ForegroundColor Cyan
# Ένα ανοιχτό αντίγραφο της εφαρμογής κλειδώνει τα αρχεία του dist\ και το build
# σκάει με «Access is denied» / «Device or resource busy».
Get-Process TimologioDownloader -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "   τερματίζω ανοιχτή εφαρμογή (PID $($_.Id))" -ForegroundColor Yellow
    Stop-Process -Id $_.Id -Force
}
Start-Sleep -Seconds 1
Remove-Item "$root\dist\TimologioDownloader" -Recurse -Force -ErrorAction SilentlyContinue
& $pyi @("installer\timologio.spec", "--noconfirm", "--distpath", "dist", "--workpath", "build")
if (-not (Test-Path "$root\dist\TimologioDownloader\TimologioDownloader.exe")) {
    throw "Το PyInstaller δεν παρήγαγε το exe."
}
# Υπογράφουμε το exe ΠΡΙΝ το πακετάρει ο Inno, ώστε το υπογεγραμμένο αρχείο να
# μπει μέσα στο setup.
Invoke-Sign "$root\dist\TimologioDownloader\TimologioDownloader.exe"

# --- Inno Setup --------------------------------------------------------------
Write-Host "== 5/5  Inno Setup ==" -ForegroundColor Cyan
# Ο Inno Setup 6 εγκαθίσταται ανά χρήστη από το winget, οπότε ψάχνουμε και τις
# δύο συνηθισμένες τοποθεσίες πριν τα παρατήσουμε.
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    throw "Δεν βρέθηκε το Inno Setup. Εγκαταστήστε το με:  winget install JRSoftware.InnoSetup"
}

& $iscc installer\timologio.iss
if ($LASTEXITCODE -ne 0) { throw "Ο Inno Setup απέτυχε." }

# Ταξινόμηση κατά ώρα και όχι κατά όνομα: παλιότερες εκδόσεις μένουν στον φάκελο
# και αλφαβητικά προηγούνται, οπότε το μήνυμα ανέφερε το λάθος αρχείο.
$setup = Get-ChildItem "$root\dist\installer\*.exe" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
Invoke-Sign $setup.FullName
Write-Host ""
Write-Host "Έτοιμο: $($setup.FullName)" -ForegroundColor Green
Write-Host "Μέγεθος: $([math]::Round($setup.Length/1MB,1)) MB"

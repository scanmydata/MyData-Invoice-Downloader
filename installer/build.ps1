# Χτίζει το .exe και τον Windows installer.
#
#   powershell -ExecutionPolicy Bypass -File installer\build.ps1
#
# Παράγει:  dist\installer\TimologioDownloader-<έκδοση>-setup.exe

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "== 1/3  Εξαρτήσεις ==" -ForegroundColor Cyan
uv sync --extra gui --group dev

Write-Host "== 2/3  PyInstaller ==" -ForegroundColor Cyan
# Ένα ανοιχτό αντίγραφο της εφαρμογής κλειδώνει τα αρχεία του dist\ και το build
# σκάει με «Access is denied» / «Device or resource busy».
Get-Process TimologioDownloader -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "   τερματίζω ανοιχτή εφαρμογή (PID $($_.Id))" -ForegroundColor Yellow
    Stop-Process -Id $_.Id -Force
}
Start-Sleep -Seconds 1
Remove-Item "$root\dist\TimologioDownloader" -Recurse -Force -ErrorAction SilentlyContinue
uv run --extra gui pyinstaller installer\timologio.spec --noconfirm --distpath dist --workpath build
if (-not (Test-Path "$root\dist\TimologioDownloader\TimologioDownloader.exe")) {
    throw "Το PyInstaller δεν παρήγαγε το exe."
}

Write-Host "== 3/3  Inno Setup ==" -ForegroundColor Cyan
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

$setup = Get-ChildItem "$root\dist\installer\*.exe" | Select-Object -First 1
Write-Host ""
Write-Host "Έτοιμο: $($setup.FullName)" -ForegroundColor Green
Write-Host "Μέγεθος: $([math]::Round($setup.Length/1MB,1)) MB"

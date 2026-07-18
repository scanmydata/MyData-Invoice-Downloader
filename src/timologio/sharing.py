"""Κοινή χρήση του φακέλου δεδομένων, μέσα από την εφαρμογή.

Το στήσιμο ενός γραφείου σκόνταφτε πάντα στο ίδιο σημείο: «κάντε τον φάκελο
κοινόχρηστο». Στα ελληνικά Windows η διαδρομή είναι δεξί κλικ → Ιδιότητες →
Κοινή χρήση → Για προχωρημένους → δικαιώματα → και μετά ξεχνιέται το NTFS, ή
μένει μόνο ανάγνωση και τα τερματικά δεν μπορούν να γράψουν. Το κάνουμε εμείς.

Δύο πράγματα που δεν παρακάμπτονται:

* **Χρειάζεται δικαιώματα διαχειριστή.** Η δημιουργία share είναι ρύθμιση
  συστήματος. Δεν την κάνουμε στα κρυφά: ζητάμε ρητά ανύψωση (UAC) και ο
  χρήστης βλέπει τι θα τρέξει.
* **Δύο επίπεδα δικαιωμάτων.** Ένα share με σωστά δικαιώματα SMB αλλά λάθος
  NTFS δίνει «δεν έχετε πρόσβαση» — ρυθμίζονται και τα δύο μαζί.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

#: Τα ελληνικά και τα κενά επιτρέπονται σε όνομα share, αλλά κάθε τερματικό θα
#: πρέπει να τα πληκτρολογήσει σωστά. Κρατάμε το προτεινόμενο όνομα απλό.
DEFAULT_SHARE_NAME = "ParastatikaMyDATA"

_INVALID = re.compile(r'[\\/:*?"<>|]')


class NotWindows(RuntimeError):
    pass


@dataclass(frozen=True)
class ShareInfo:
    name: str
    path: str

    @property
    def unc(self) -> str:
        return rf"\\{host_name()}\{self.name}"


def host_name() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "SERVER"


def suggest_name(data_dir: Path) -> str:
    """Όνομα share που δεν χρειάζεται εξήγηση στο τηλέφωνο.

    Μένουμε σε λατινικούς χαρακτήρες: το όνομα θα πληκτρολογηθεί σε κάθε
    τερματικό, και ένα «Παραστατικά myDATA» με ελληνικά και κενό είναι τρεις
    ευκαιρίες για τυπογραφικό. Ο χρήστης μπορεί να το αλλάξει.
    """
    raw = _INVALID.sub("", data_dir.name).replace(" ", "").strip()
    if not raw or not raw.isascii():
        return DEFAULT_SHARE_NAME
    return raw


def is_valid_name(name: str) -> bool:
    return bool(name) and len(name) <= 80 and not _INVALID.search(name)


def _run(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        # Χωρίς αυτό, κάθε κλήση ανοίγει μαύρο παράθυρο κονσόλας πάνω από το GUI.
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def list_shares() -> list[ShareInfo]:
    """Τα υπάρχοντα shares. Δεν χρειάζεται ανύψωση — μόνο ανάγνωση."""
    if os.name != "nt":
        return []
    try:
        result = _run([
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            "Get-SmbShare | Select-Object Name,Path | ConvertTo-Json -Compress",
        ])
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("Δεν διαβάστηκαν τα shares: %s", exc)
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    shares = []
    for item in data:
        name, path = item.get("Name"), item.get("Path")
        if name and path:
            shares.append(ShareInfo(name=str(name), path=str(path)))
    return shares


def find_share_for(data_dir: Path) -> ShareInfo | None:
    """Το share που δείχνει ακριβώς σε αυτόν τον φάκελο, αν υπάρχει."""
    try:
        target = data_dir.resolve()
    except OSError:
        target = data_dir
    for share in list_shares():
        # Τα διαχειριστικά shares (C$, ADMIN$) δεν μετράνε: υπάρχουν πάντα και
        # απαιτούν δικαιώματα διαχειριστή από τον πελάτη.
        if share.name.endswith("$"):
            continue
        try:
            if Path(share.path).resolve() == target:
                return share
        except OSError:
            continue
    return None


def build_share_script(data_dir: Path, share_name: str, account: str) -> str:
    """Το PowerShell που θα τρέξει ανυψωμένο.

    Επιστρέφεται ως κείμενο ώστε να μπορεί να φανεί στον χρήστη πριν εγκριθεί:
    ζητάμε δικαιώματα διαχειριστή, οπότε του χρωστάμε να ξέρει για τι.
    """
    path = str(data_dir).replace("'", "''")
    name = share_name.replace("'", "''")
    who = account.replace("'", "''")
    return (
        f"$ErrorActionPreference='Stop'; "
        f"$p='{path}'; $n='{name}'; $who='{who}'; "
        # Το share μπορεί να υπάρχει ήδη με λάθος διαδρομή ή δικαιώματα.
        f"$ex = Get-SmbShare -Name $n -ErrorAction SilentlyContinue; "
        f"if ($ex) {{ Remove-SmbShare -Name $n -Force }}; "
        f"New-SmbShare -Name $n -Path $p -FullAccess $who | Out-Null; "
        # Χωρίς το NTFS, το share φαίνεται αλλά δίνει «δεν έχετε πρόσβαση».
        f"$acl = Get-Acl $p; "
        f"$rule = New-Object System.Security.AccessControl.FileSystemAccessRule("
        f"$who,'Modify','ContainerInherit,ObjectInherit','None','Allow'); "
        f"$acl.SetAccessRule($rule); Set-Acl $p $acl; "
        # Το group id είναι ανεξάρτητο γλώσσας· το DisplayGroup είναι
        # μεταφρασμένο και δεν θα έβρισκε τους κανόνες σε ελληνικά Windows.
        f"Enable-NetFirewallRule -Group '@FirewallAPI.dll,-28502' "
        f"-ErrorAction SilentlyContinue; "
        f"Write-Output 'OK'"
    )


def build_unshare_script(share_name: str) -> str:
    name = share_name.replace("'", "''")
    return (
        f"$ErrorActionPreference='Stop'; "
        f"Remove-SmbShare -Name '{name}' -Force; Write-Output 'OK'"
    )


def run_elevated(script: str) -> bool:
    """Τρέχει PowerShell με ανύψωση. False αν ο χρήστης απέρριψε το UAC.

    Δεν περιμένουμε το αποτέλεσμα εδώ: το ShellExecute επιστρέφει μόλις ξεκινήσει
    η ανυψωμένη διεργασία. Ο έλεγχος γίνεται μετά, ρωτώντας ξανά τα shares —
    που είναι ούτως ή άλλως η αλήθεια, ανεξάρτητα από το τι είπε το script.
    """
    if os.name != "nt":
        raise NotWindows("Η κοινή χρήση υποστηρίζεται μόνο στα Windows.")
    import ctypes

    params = f'-NoProfile -NonInteractive -WindowStyle Hidden -Command "{script}"'
    # >32 σημαίνει επιτυχής εκκίνηση· 5 (ACCESS_DENIED) σημαίνει «Όχι» στο UAC.
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", "powershell.exe", params, None, 0
    )
    if result <= 32:
        log.info("Η ανύψωση δικαιωμάτων δεν εγκρίθηκε (κωδικός %s)", result)
        return False
    return True

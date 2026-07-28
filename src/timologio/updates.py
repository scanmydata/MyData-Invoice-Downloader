"""Έλεγχος για νεότερη έκδοση, μέσω των Releases του GitHub.

Δεν υπάρχει auto-updater: το πρόγραμμα δεν κατεβάζει ούτε τρέχει τίποτα μόνο
του — απλώς ρωτά ποια είναι η τελευταία δημοσιευμένη έκδοση και, αν είναι
νεότερη, δείχνει σύνδεσμο. Η λήψη και η εγκατάσταση μένουν ρητά στον χρήστη.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

OWNER_REPO = "scanmydata/MyData-Invoice-Downloader"
API_URL = f"https://api.github.com/repos/{OWNER_REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{OWNER_REPO}/releases/latest"

#: Όνομα του προσωρινού scheduled task που τρέχει την ενημέρωση. Το ίδιο όνομα
#: το σβήνει το script στην αρχή του, ώστε να μη μένουν σκουπίδια στον
#: χρονοπρογραμματιστή.
UPDATE_TASK_NAME = "TimologioDownloaderUpdate"


def parse_version(text: str) -> tuple[int, ...]:
    """«v0.2.3» -> (0, 2, 3). Ανθεκτικό σε ό,τι δεν είναι αριθμός."""
    cleaned = text.strip().lstrip("vV")
    parts: list[int] = []
    for chunk in cleaned.split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


@dataclass(frozen=True)
class UpdateInfo:
    current: str
    latest: str
    url: str
    asset_url: str = ""   # άμεσος σύνδεσμος του setup.exe (κενό αν λείπει)
    asset_name: str = ""
    asset_size: int = 0
    notes: str = ""       # σημειώσεις έκδοσης (Markdown από το GitHub release)

    @property
    def is_newer(self) -> bool:
        return parse_version(self.latest) > parse_version(self.current)

    @property
    def can_auto_install(self) -> bool:
        """Υπάρχει installer να κατεβάσουμε; Χωρίς αυτόν μένει μόνο ο σύνδεσμος."""
        return bool(self.asset_url)


def check(current: str, timeout: int = 8) -> UpdateInfo:
    """Ρωτά το GitHub για την τελευταία έκδοση. Σηκώνει εξαίρεση αν αποτύχει."""
    import requests

    response = requests.get(
        API_URL,
        timeout=timeout,
        headers={"Accept": "application/vnd.github+json"},
    )
    response.raise_for_status()
    data = response.json()
    tag = str(data.get("tag_name") or "").strip()
    url = str(data.get("html_url") or "").strip() or RELEASES_URL

    asset_url = asset_name = ""
    asset_size = 0
    for asset in data.get("assets") or []:
        name = str(asset.get("name") or "")
        if name.lower().endswith(".exe"):
            asset_url = str(asset.get("browser_download_url") or "")
            asset_name = name
            asset_size = int(asset.get("size") or 0)
            break

    return UpdateInfo(
        current=current,
        latest=tag.lstrip("vV") or "?",
        url=url,
        asset_url=asset_url,
        asset_name=asset_name,
        asset_size=asset_size,
        notes=str(data.get("body") or "").strip(),
    )


def download(asset_url: str, dest: Path, progress=None, timeout: int = 30) -> Path:
    """Κατεβάζει τον installer σε ``dest``. ``progress(done, total)`` προαιρετικό.

    Γράφεται σε προσωρινό αρχείο και μετονομάζεται στο τέλος, ώστε μια διακοπή
    στη μέση να μην αφήσει μισό «έγκυρο» installer.
    """
    import requests

    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(asset_url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        with open(tmp, "wb") as handle:
            for chunk in response.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                handle.write(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)
    tmp.replace(dest)
    return dest


def build_updater_script(
    *, pid: int, setup: Path, app_exe: Path, data_dir: Path, role: str, tray: bool,
    install_dir: Path | None = None,
) -> str:
    """PowerShell που τρέχει ΑΦΟΥ κλείσει η εφαρμογή: εγκαθιστά και ξαναανοίγει.

    Περιμένει πρώτα να τερματίσει η τρέχουσα διεργασία (ώστε να ξεκλειδώσουν τα
    αρχεία), τρέχει τον installer σιωπηλά περνώντας τις ΤΡΕΧΟΥΣΕΣ ρυθμίσεις
    (φάκελος/ρόλος/tray) ώστε να μη χαθούν, και μετά ξεκινά τη νέα έκδοση.

    ``install_dir`` (ο φάκελος όπου τρέχει ήδη η εφαρμογή, από το ``sys.executable``)
    περνιέται ρητά ως ``/DIR`` στον installer. ΚΡΙΣΙΜΟ: χωρίς αυτό, αν λείπει το
    κλειδί απεγκατάστασης του Inno (π.χ. εγκατάσταση από παλιότερη έκδοση, ή
    χειροκίνητη αντιγραφή), ο installer ΔΕΝ βρίσκει την προηγούμενη εγκατάσταση και
    εγκαθιστά στον **προεπιλεγμένο** φάκελο — όχι εκεί που τρέχει η εφαρμογή. Τότε
    η νέα έκδοση πάει αλλού, και το relaunch ξανανοίγει την **παλιά** («η ενημέρωση
    δεν δουλεύει»). Με ρητό ``/DIR`` η αναβάθμιση γίνεται πάντα ακριβώς από πάνω.
    """
    def q(text: str) -> str:  # single-quoted PowerShell literal
        return "'" + str(text).replace("'", "''") + "'"

    def esc(text: str) -> str:  # για χρήση μέσα σε ήδη single-quoted literal
        return str(text).replace("'", "''")

    tray_flag = "/TRAY=1" if tray else "/TRAY=0"
    # Ο installer γράφει log δίπλα στο setup, ώστε μια αποτυχία να είναι ορατή.
    log_path = setup.with_name("timologio_update_inno.log")
    # Δικό μας log του ΙΔΙΟΥ του script: χωρίς αυτό, όταν «η ενημέρωση δεν
    # δουλεύει» δεν υπάρχει κανένα ίχνος για το πού κόλλησε. Τώρα κάθε βήμα
    # καταγράφεται με ώρα, οπότε το πρόβλημα είναι πάντα ορατό.
    run_log = setup.with_name("timologio_update_run.log")
    proc_name = app_exe.stem
    dir_arg = f"'/DIR={esc(install_dir)}'," if install_dir is not None else ""
    args = (
        f"'/SILENT','/SUPPRESSMSGBOXES','/NORESTART',"
        f"{dir_arg}"
        f"'/LOG={esc(log_path)}',"
        f"'/DATADIR={esc(data_dir)}',"
        f"'/ROLE={role}','{tray_flag}'"
    )
    return (
        "$ErrorActionPreference='SilentlyContinue'\n"
        f"$log={q(run_log)}\n"
        "function L($m){ (\"[{0}] {1}\" -f (Get-Date -Format 'HH:mm:ss'), $m) | "
        "Out-File -FilePath $log -Append -Encoding utf8 }\n"
        f"L ('start pid={int(pid)}')\n"
        # Αν μας ξεκίνησε το Task Scheduler, σβήσε το task αμέσως: έχει ήδη
        # πυροδοτηθεί, δεν το χρειαζόμαστε άλλο, και δεν θέλουμε να μείνει
        # εγγεγραμμένο. Αν μας ξεκίνησε αλλιώς (fallback), το /Delete απλώς
        # αποτυγχάνει σιωπηλά.
        f"schtasks.exe /Delete /TN '{UPDATE_TASK_NAME}' /F 2>$null | Out-Null\n"
        # Περίμενε πρώτα τη συγκεκριμένη διεργασία που ζήτησε την ενημέρωση…
        f"Wait-Process -Id {int(pid)} -Timeout 60\n"
        # …και μετά κάθε τυχόν άλλη ανοιχτή instance (π.χ. server + τερματικό στο
        # ίδιο μηχάνημα), ώστε να μη μείνει κανείς να κλειδώνει τα αρχεία.
        "$deadline=(Get-Date).AddSeconds(30)\n"
        f"while ((Get-Process -Name {q(proc_name)} -ErrorAction SilentlyContinue) "
        f"-and (Get-Date) -lt $deadline) {{ Start-Sleep -Milliseconds 500 }}\n"
        # Δίχτυ ασφαλείας: αν κάποια instance επιμένει (π.χ. μαζεμένη στο tray),
        # την κλείνουμε με τη βία — αλλιώς τα αρχεία μένουν κλειδωμένα και ο
        # installer αποτυγχάνει σιωπηλά.
        f"Stop-Process -Name {q(proc_name)} -Force -ErrorAction SilentlyContinue\n"
        "L 'instances stopped'\n"
        # ΚΡΙΣΙΜΟ: ο πυρήνας του Windows απελευθερώνει τα mapped DLL (Qt κ.λπ.) με
        # καθυστέρηση ΜΕΤΑ τον τερματισμό. Αντί για σταθερό sleep, περιμένουμε
        # ενεργά μέχρι το exe να ΞΕΚΛΕΙΔΩΣΕΙ (ανοίγει για αποκλειστική εγγραφή),
        # ώστε ο installer να μη βρει κλειδωμένα αρχεία και αποτύχει σιωπηλά.
        f"$exe={q(app_exe)}\n"
        "$d2=(Get-Date).AddSeconds(25)\n"
        "while ((Get-Date) -lt $d2) { try { "
        "$fs=[IO.File]::Open($exe,'Open','ReadWrite','None'); $fs.Close(); break "
        "} catch { Start-Sleep -Milliseconds 400 } }\n"
        "Start-Sleep -Seconds 1\n"
        "L 'running installer'\n"
        f"$p=Start-Process -Wait -PassThru -FilePath {q(setup)} -ArgumentList @({args})\n"
        "L ('installer exit=' + $(if ($p) { $p.ExitCode } else { 'null' }))\n"
        # --show: μετά την ενημέρωση ο χρήστης πρέπει να ΔΕΙ την εφαρμογή, όχι να
        # «εξαφανιστεί» στο tray (ισχύει ακόμη κι αν έχει επιλεγεί «εκκίνηση στο
        # tray» — αυτή η εκκίνηση είναι το αποτέλεσμα μιας ρητής ενημέρωσης).
        f"Start-Process -FilePath {q(app_exe)} -ArgumentList '--show'\n"
        "L 'relaunched'\n"
    )


def powershell_exe() -> str:
    """Πλήρης διαδρομή του Windows PowerShell 5.1.

    Το PATH δεν είναι εγγυημένο μέσα στο πακεταρισμένο περιβάλλον, οπότε ένα
    σκέτο ``"powershell"`` μπορεί να μη βρεθεί.
    """
    full = (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    )
    return str(full) if full.exists() else "powershell"


def launch_detached(script_path: Path) -> bool:
    """Ξεκινά το PowerShell script της ενημέρωσης ΑΠΟΣΠΑΣΜΕΝΑ από την εφαρμογή,
    ώστε να επιβιώσει του κλεισίματός της. Επιστρέφει ``True`` αν ξεκίνησε.

    ΓΙΑΤΙ Task Scheduler και όχι απλό detached process: πολλά περιβάλλοντα βάζουν
    την εφαρμογή σε **Job Object με kill-on-close**. Όταν κλείνει η εφαρμογή, το
    job σκοτώνει ΚΑΙ κάθε παιδί-διεργασία — ακόμη και «detached». Το
    ``CREATE_BREAKAWAY_FROM_JOB`` υποτίθεται ότι το λύνει, αλλά αν το job ΔΕΝ
    επιτρέπει breakaway (μετρημένα, συμβαίνει), η δημιουργία διεργασίας αποτυγχάνει
    και το script δεν τρέχει ΠΟΤΕ — «κατέβαινε αλλά δεν εγκαθιστούσε». Ένα
    scheduled task τρέχει κάτω από την υπηρεσία του χρονοπρογραμματιστή, εντελώς
    έξω από το job της εφαρμογής, οπότε επιβιώνει πάντα. Ο απλός detached τρόπος
    μένει ως εφεδρεία για συστήματα όπου το schtasks είναι απενεργοποιημένο.
    """
    ps = powershell_exe()
    if _schedule_via_task(ps, script_path):
        log.info("Ενημέρωση: ξεκίνησε μέσω Task Scheduler.")
        return True
    log.warning("Ενημέρωση: το Task Scheduler απέτυχε — δοκιμή απευθείας.")
    return _launch_via_popen(ps, script_path)


def _schedule_via_task(powershell: str, script_path: Path) -> bool:
    """Καταχωρεί ένα εφάπαξ task που τρέχει το script και το πυροδοτεί αμέσως."""
    tr = (
        f'"{powershell}" -NoProfile -ExecutionPolicy Bypass '
        f'-WindowStyle Hidden -NonInteractive -File "{script_path}"'
    )
    # Το /ST είναι υποχρεωτικό αλλά το /Run το πυροδοτεί ούτως ή άλλως αμέσως·
    # βάζουμε ένα έγκυρο μελλοντικό HH:MM για να μη γκρινιάξει το schtasks.
    start_time = (datetime.now() + timedelta(minutes=1)).strftime("%H:%M")
    try:
        created = subprocess.run(
            ["schtasks", "/Create", "/TN", UPDATE_TASK_NAME, "/TR", tr,
             "/SC", "ONCE", "/ST", start_time, "/F"],
            capture_output=True, timeout=20,
        )
        if created.returncode != 0:
            log.warning("schtasks /Create: %s",
                        created.stderr.decode("utf-8", "replace").strip())
            return False
        ran = subprocess.run(
            ["schtasks", "/Run", "/TN", UPDATE_TASK_NAME],
            capture_output=True, timeout=20,
        )
        if ran.returncode != 0:
            log.warning("schtasks /Run: %s",
                        ran.stderr.decode("utf-8", "replace").strip())
            return False
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("Task Scheduler μη διαθέσιμο: %s", exc)
        return False


def _launch_via_popen(powershell: str, script_path: Path) -> bool:
    """Εφεδρεία: απευθείας detached process, με προσπάθεια breakaway από το job."""
    cmd = [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-WindowStyle", "Hidden", "-File", str(script_path)]
    detached = (
        getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    )
    create_breakaway_from_job = 0x01000000
    try:
        subprocess.Popen(
            cmd, creationflags=detached | create_breakaway_from_job,
            close_fds=True,
        )
        return True
    except OSError:
        log.warning("Breakaway from job απέτυχε — εκκίνηση χωρίς αυτό.")
    try:
        subprocess.Popen(cmd, creationflags=detached, close_fds=True)
        return True
    except OSError as exc:
        log.error("Δεν ξεκίνησε το script ενημέρωσης: %s", exc)
        return False

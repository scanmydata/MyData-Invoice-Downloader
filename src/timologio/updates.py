"""Έλεγχος για νεότερη έκδοση, μέσω των Releases του GitHub.

Δεν υπάρχει auto-updater: το πρόγραμμα δεν κατεβάζει ούτε τρέχει τίποτα μόνο
του — απλώς ρωτά ποια είναι η τελευταία δημοσιευμένη έκδοση και, αν είναι
νεότερη, δείχνει σύνδεσμο. Η λήψη και η εγκατάσταση μένουν ρητά στον χρήστη.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

OWNER_REPO = "scanmydata/MyData-Invoice-Downloader"
API_URL = f"https://api.github.com/repos/{OWNER_REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{OWNER_REPO}/releases/latest"


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
        # Περίμενε πρώτα τη συγκεκριμένη διεργασία που ζήτησε την ενημέρωση…
        f"Wait-Process -Id {int(pid)} -Timeout 60\n"
        # …και μετά κάθε τυχόν άλλη ανοιχτή instance (π.χ. server + τερματικό στο
        # ίδιο μηχάνημα), ώστε να μη μείνει κανείς να κλειδώνει τα αρχεία.
        "$deadline=(Get-Date).AddSeconds(30)\n"
        f"while ((Get-Process -Name {q(proc_name)} -ErrorAction SilentlyContinue) "
        f"-and (Get-Date) -lt $deadline) {{ Start-Sleep -Milliseconds 500 }}\n"
        # Δίχτυ ασφαλείας: αν κάποια instance επιμένει (π.χ. μαζεμένη στο tray),
        # την κλείνουμε με τη βία — αλλιώς τα αρχεία μένουν κλειδωμένα και ο
        # installer αποτυγχάνει σιωπηλά. Τερματίζουμε ούτως ή άλλως — αυτός είναι
        # ο σκοπός της ενημέρωσης.
        f"Stop-Process -Name {q(proc_name)} -Force -ErrorAction SilentlyContinue\n"
        # ΚΡΙΣΙΜΟ: ο πυρήνας του Windows απελευθερώνει τα mapped DLL (Qt κ.λπ.) με
        # μικρή καθυστέρηση ΜΕΤΑ τον τερματισμό. Χωρίς αυτή την αναμονή, ο
        # installer έβρισκε κλειδωμένα αρχεία, δεν τα αντικαθιστούσε (σιωπηλά, λόγω
        # /SUPPRESSMSGBOXES) και η αναβάθμιση «δεν έπιανε» — η εφαρμογή ξανάνοιγε
        # στην παλιά έκδοση και ξαναπρότεινε ενημέρωση (ατέρμονος βρόχος).
        "Start-Sleep -Seconds 3\n"
        f"Start-Process -Wait -FilePath {q(setup)} -ArgumentList @({args})\n"
        f"Start-Process -FilePath {q(app_exe)}\n"
    )

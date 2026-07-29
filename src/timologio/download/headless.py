"""Λήψη «μόνο online» παραστατικών με headless browser.

Κάποιοι πάροχοι (e-timologiera και άλλες SPA προβολές) δεν δίνουν PDF στο
downloadingInvoiceUrl — φτιάχνουν το παραστατικό στον browser. Εδώ οδηγούμε τον
εγκατεστημένο **Edge ή Chrome** σε headless λειτουργία, περιμένουμε να
στοιχειοθετηθεί η σελίδα, και τυπώνουμε σε PDF μέσω του DevTools protocol
(``Page.printToPDF``).

Γιατί raw CDP και όχι Selenium: δεν χρειάζεται driver (chromedriver/msedgedriver)
ούτε ταίριασμα εκδόσεων — μιλάμε κατευθείαν στον browser μέσω websocket. Η
μοναδική εξάρτηση είναι το ``websocket-client``, καθαρά Python.

ΟΡΙΟ: πάροχοι πίσω από interactive Blazor + Cloudflare (π.χ. το Epsilon
3rd-party DocViewer) δεν στοιχειοθετούνται σε headless — η σελίδα μένει κενή. Δεν
επιχειρούμε να παρακάμψουμε bot-protection· απλώς το ανιχνεύουμε (κενό κείμενο)
και αφήνουμε το παραστατικό ως «μόνο online».
"""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

#: Κάτω από τόσους χαρακτήρες ορατού κειμένου, θεωρούμε ότι η σελίδα δεν
#: στοιχειοθετήθηκε (κενή προβολή) — δεν αποθηκεύουμε λευκό PDF.
MIN_TEXT = 300

#: JS που πατά το κουμπί «Αποθήκευση ως PDF» του παρόχου (Epsilon DocViewer).
#: Ψάχνει τον σύνδεσμο/κουμπί με title «Save as PDF»/«Αποθήκευση ως PDF» ή με
#: κείμενο ακριβώς «PDF» (η επιλογή στο μενού «Αποθήκευση»). Δεν παρακάμπτουμε
#: τίποτα — πατάμε το ΙΔΙΟ κουμπί που θα πατούσε ο χρήστης.
_SAVE_PDF_CLICK_JS = """
(function () {
  var els = Array.prototype.slice.call(
    document.querySelectorAll('a, button, [role="button"]'));
  var t = els.find(function (e) {
    var tx = (e.textContent || '').trim();
    var ti = (e.getAttribute && e.getAttribute('title')) || '';
    return /save as pdf|αποθήκευση ως pdf/i.test(ti) || tx === 'PDF';
  });
  if (t) { t.click(); return true; }
  return false;
})()
"""


class HeadlessError(Exception):
    """Γενικό σφάλμα του headless renderer."""


class BrowserNotFound(HeadlessError):
    """Δεν βρέθηκε Edge ή Chrome στο σύστημα."""


class HeadlessCancelled(HeadlessError):
    """Η απόδοση διακόπηκε από τον χρήστη (ακύρωση) — όχι σφάλμα."""


def _registry_app_path(exe: str) -> str | None:
    """Διαβάζει το «App Paths» του μητρώου για msedge.exe / chrome.exe."""
    if os.name != "nt":
        return None
    try:
        import winreg

        sub = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}"
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, sub) as key:
                    value, _ = winreg.QueryValueEx(key, "")
                    if value and Path(value).exists():
                        return str(value)
            except OSError:
                continue
    except Exception:  # noqa: BLE001
        pass
    return None


def find_browsers() -> list[Path]:
    """Όλοι οι διαθέσιμοι browsers (Edge πρώτα, μετά Chrome), χωρίς διπλά.

    Επιστρέφει λίστα ώστε να υπάρχει **fallback**: αν ο πρώτος (π.χ. Edge) δεν
    ανοίγει — «σφάλμα browser» κατά την εκκίνηση — δοκιμάζουμε τον επόμενο
    (Chrome). Το Edge είναι προεγκατεστημένο σε κάθε Windows 10/11.
    """
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", "")

    candidates = [
        _registry_app_path("msedge.exe"),
        rf"{pf86}\Microsoft\Edge\Application\msedge.exe",
        rf"{pf}\Microsoft\Edge\Application\msedge.exe",
        _registry_app_path("chrome.exe"),
        rf"{pf}\Google\Chrome\Application\chrome.exe",
        rf"{pf86}\Google\Chrome\Application\chrome.exe",
        rf"{local}\Google\Chrome\Application\chrome.exe" if local else None,
    ]
    out: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        if path and Path(path).exists():
            key = os.path.normcase(str(Path(path)))
            if key not in seen:
                seen.add(key)
                out.append(Path(path))
    return out


def find_browser() -> Path | None:
    """Ο προτιμώμενος browser (Edge, αλλιώς Chrome), ή None."""
    browsers = find_browsers()
    return browsers[0] if browsers else None


def available() -> bool:
    """Αληθές αν υπάρχει και browser και το websocket-client."""
    try:
        import websocket  # noqa: F401
    except ImportError:
        return False
    return find_browser() is not None


def browser_name(path: Path) -> str:
    """Φιλικό όνομα από τη διαδρομή του exe (msedge -> Microsoft Edge κ.λπ.)."""
    stem = path.stem.lower()
    if "edge" in stem:
        return "Microsoft Edge"
    if "chrome" in stem:
        return "Google Chrome"
    return path.stem


@dataclass(frozen=True)
class BrowserProbe:
    """Αποτέλεσμα δοκιμής ενός browser για τη λειτουργία headless."""

    name: str
    path: Path
    ok: bool
    detail: str


def probe_browsers(*, timeout: float = 25.0) -> list[BrowserProbe]:
    """Δοκιμάζει ΚΑΘΕ διαθέσιμο browser σε πραγματική headless λειτουργία.

    Για κάθε Edge/Chrome: τον ανοίγει αόρατα, αποδίδει μια απλή σελίδα σε PDF και
    ελέγχει ότι πήρε έγκυρο PDF. Έτσι ο χρήστης βλέπει από τον Πίνακα ελέγχου αν
    η αυτόματη λήψη «μόνο online» θα δουλέψει στο μηχάνημά του, χωρίς να χρειαστεί
    να έχει πραγματικά παραστατικά. Είναι αργό (ανοίγει browsers) — τρέξτε το
    εκτός του GUI thread.
    """
    browsers = find_browsers()
    if not browsers:
        return []

    # data: URL με αρκετό κείμενο ώστε να περάσει το κατώφλι στοιχειοθέτησης.
    html = (
        "<html><body><h1>Timologio Downloader</h1><p>"
        + ("δοκιμή λειτουργίας headless. " * 40)
        + "</p></body></html>"
    )
    url = "data:text/html;charset=utf-8," + urllib.parse.quote(html)

    results: list[BrowserProbe] = []
    for browser in browsers:
        name = browser_name(browser)
        try:
            renderer = HeadlessRenderer(browser=browser, launch_timeout=timeout)
        except Exception as exc:  # noqa: BLE001 — θέλουμε να το αναφέρουμε, όχι να σκάσουμε
            results.append(BrowserProbe(name, browser, False, f"δεν άνοιξε: {exc}"))
            continue
        try:
            pdf = renderer.render_pdf(url, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            results.append(BrowserProbe(name, browser, False, f"σφάλμα απόδοσης: {exc}"))
            continue
        finally:
            renderer.close()
        if pdf and pdf.startswith(b"%PDF"):
            results.append(BrowserProbe(name, browser, True,
                                        f"εντάξει — απέδωσε PDF ({len(pdf):,} bytes)"))
        else:
            results.append(BrowserProbe(name, browser, False,
                                        "άνοιξε αλλά δεν απέδωσε PDF"))
    return results


class HeadlessRenderer:
    """Ανοίγει έναν headless browser και τυπώνει σελίδες σε PDF.

    Χρησιμοποιείται ως context manager ώστε ο browser και ο προσωρινός φάκελος
    προφίλ να καθαρίζονται πάντα::

        with HeadlessRenderer() as r:
            pdf = r.render_pdf(url)
    """

    def __init__(
        self,
        browser: Path | None = None,
        *,
        launch_timeout: float = 20.0,
        headed: bool = False,
        profile_dir: str | Path | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ):
        self._browser = browser or find_browser()
        self._should_cancel = should_cancel
        # Μόνιμος φάκελος προφίλ (προαιρετικά): κρατά τη σύνδεση του χρήστη στον
        # πάροχο ανάμεσα σε τρεξίματα, ώστε αν έχει περάσει μία φορά τον έλεγχο
        # «είστε άνθρωπος»/έχει συνδεθεί, να μη χρειάζεται ξανά. Είναι ΔΙΚΟΣ ΜΑΣ
        # φάκελος (όχι το πραγματικό προφίλ του Chrome του χρήστη) — δεν αγγίζουμε
        # ούτε αντιγράφουμε τα cookies του κανονικού browser του. Αν δοθεί, ΔΕΝ
        # τον σβήνουμε στο close.
        self._persistent_profile = profile_dir is not None
        self._fixed_profile = str(profile_dir) if profile_dir is not None else None
        if self._browser is None:
            raise BrowserNotFound(
                "Δεν βρέθηκε Microsoft Edge ή Google Chrome. Εγκαταστήστε έναν "
                "από τους δύο για τη λήψη των «μόνο online» παραστατικών."
            )
        # Ορατό (headed) παράθυρο: για σελίδες που ένας πραγματικός browser
        # στοιχειοθετεί ενώ ο headless όχι (π.χ. πίσω από έλεγχο «είστε
        # άνθρωπος» — τον λύνει ο χρήστης στο ίδιο το ορατό παράθυρο). ΔΕΝ
        # παρακάμπτουμε κανέναν έλεγχο· απλώς δεν κρύβουμε τον browser.
        self._headed = headed
        self._proc: subprocess.Popen | None = None
        self._profile: str | None = None
        self._ws = None
        self._msg_id = 0
        self._port = 0
        self._launch(launch_timeout)

    # ------------------------------------------------------------- εκκίνηση
    def _launch(self, timeout: float) -> None:
        import websocket  # τοπικό import: η εξάρτηση είναι προαιρετική

        if self._fixed_profile is not None:
            os.makedirs(self._fixed_profile, exist_ok=True)
            self._profile = self._fixed_profile
            # Μόνιμο προφίλ: αν ο προηγούμενος browser δεν καθάρισε (kill/crash),
            # μένουν «Singleton*» αρχεία που κάνουν τον νέο browser να νομίζει ότι
            # τρέχει ήδη άλλη instance — τη προωθεί εκεί και βγαίνει, χωρίς
            # DevTools («connection refused»). Τα σβήνουμε: δεν τρέχει δική μας
            # instance σε αυτό το προφίλ αυτή τη στιγμή.
            for lock in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
                try:
                    os.remove(os.path.join(self._fixed_profile, lock))
                except OSError:
                    pass
        else:
            self._profile = tempfile.mkdtemp(prefix="tl_headless_")
        # Το headed διαφέρει από το headless ΜΟΝΟ στο ότι είναι ορατό: ίδια
        # σταθερά flags (και --disable-gpu, που κρατά τον renderer σταθερό — ένα
        # crash του GPU process έριχνε το DevTools websocket με «σφάλμα browser»).
        args = [str(self._browser)]
        if not self._headed:
            args += ["--headless=new"]
        args += [
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-networking",
            "--mute-audio",
            "--hide-scrollbars",
            # Επιτάχυνση «κρύας» εκκίνησης: σε φρέσκο προφίλ, ο Edge/Chrome αλλιώς
            # μπλοκάρει την αρχικοποίηση σε ενημερώσεις components, sync, telemetry
            # και δικτυακές κλήσεις — γι' αυτό «αργούσε πολύ να ξεκινήσει» ενίοτε,
            # ακόμη κι όταν η δοκιμή browser περνούσε. Κανένα από αυτά δεν αλλάζει
            # την απόδοση της σελίδας σε PDF.
            "--disable-sync",
            "--disable-component-update",
            "--disable-domain-reliability",
            "--disable-client-side-phishing-detection",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--no-service-autorun",
            "--metrics-recording-only",
            "--disable-features=Translate,MediaRouter,OptimizationHints,"
            "OptimizationGuideModelDownloading,CalculateNativeWinOcclusion,"
            "InterestFeedContentSuggestions,DialMediaRouteProvider",
            f"--user-data-dir={self._profile}",
            "--remote-debugging-port=0",
            # Απαραίτητο από Chrome/Edge 111+: αλλιώς το DevTools websocket
            # απορρίπτει τη σύνδεση με 403 (προστασία origin).
            "--remote-allow-origins=*",
            "about:blank",
        ]
        # Στο headed θέλουμε να φαίνεται το παράθυρο· στο headless κρύβουμε και
        # την κονσόλα του browser. Σε ΚΑΘΕ περίπτωση τρέχουμε τον browser σε
        # χαμηλότερη προτεραιότητα (BELOW_NORMAL): ένας renderer που τρώει CPU
        # δεν πρέπει να «παγώνει» ολόκληρο το μηχάνημα του λογιστή.
        creationflags = 0 if self._headed else getattr(subprocess, "CREATE_NO_WINDOW", 0)
        creationflags |= getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        self._proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        # ΚΡΙΣΙΜΟ: αν αποτύχει οτιδήποτε ΜΕΤΑ το spawn (π.χ. δεν απαντά το
        # DevTools), η εξαίρεση βγαίνει από τον constructor πριν υπάρξει
        # αντικείμενο — οπότε κανείς δεν καλεί close() και ο browser μένει
        # ορφανός (και κρατά κλειδωμένο το μόνιμο προφίλ). Τον σκοτώνουμε εδώ.
        try:
            self._port = self._read_port(timeout)
            page = self._first_page_target(self._port, timeout)
            self._ws = websocket.create_connection(
                page["webSocketDebuggerUrl"], max_size=None, timeout=60
            )
            self._call("Page.enable")
        except BaseException:
            if self._proc is not None:
                self._kill_tree(self._proc)
                self._proc = None
            raise

    def _read_port(self, timeout: float) -> int:
        assert self._profile is not None
        marker = Path(self._profile) / "DevToolsActivePort"
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._should_cancel and self._should_cancel():
                raise HeadlessCancelled()
            if self._proc and self._proc.poll() is not None:
                raise HeadlessError("Ο browser τερμάτισε πρόωρα.")
            if marker.exists():
                try:
                    return int(marker.read_text().splitlines()[0].strip())
                except (PermissionError, OSError, ValueError, IndexError):
                    pass
            time.sleep(0.1)
        raise HeadlessError("Ο browser δεν άνοιξε εγκαίρως (DevTools).")

    def _first_page_target(self, port: int, timeout: float) -> dict:
        deadline = time.time() + timeout
        last_err: Exception | None = None
        while time.time() < deadline:
            if self._should_cancel and self._should_cancel():
                raise HeadlessCancelled()
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/json", timeout=5
                ) as resp:
                    targets = json.loads(resp.read().decode("utf-8"))
                for t in targets:
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t
            except Exception as exc:  # noqa: BLE001
                last_err = exc
            time.sleep(0.2)
        raise HeadlessError(f"Δεν βρέθηκε σελίδα DevTools: {last_err}")

    # --------------------------------------------------------------- CDP
    def _call(self, method: str, **params) -> dict:
        import websocket

        try:
            return self._send_recv(method, params)
        except (OSError, websocket.WebSocketException) as exc:
            # Το page target μπορεί να αντικαταστάθηκε (cross-process navigation,
            # π.χ. redirect Cloudflare/DocViewer) και το websocket να έκλεισε
            # (WinError 10053 «connection aborted»). Ξανασυνδεόμαστε στο τρέχον
            # target και ξαναδοκιμάζουμε μία φορά, αντί να σκάσουμε με «σφάλμα
            # browser». (Το HeadlessError των CDP σφαλμάτων ΔΕΝ πιάνεται εδώ.)
            log.info("CDP websocket επανασύνδεση μετά από: %s", exc)
            self._reconnect()
            return self._send_recv(method, params)

    def _send_recv(self, method: str, params: dict) -> dict:
        assert self._ws is not None
        self._msg_id += 1
        mid = self._msg_id
        self._ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self._ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise HeadlessError(str(msg["error"]))
                return msg.get("result", {})
            # αγνοούμε τα asynchronous events (Page.*, Network.* κ.λπ.)

    def _reconnect(self) -> None:
        """Ξανασυνδέεται στο τρέχον page target μετά από πτώση του websocket."""
        import websocket

        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:  # noqa: BLE001
                pass
        page = self._first_page_target(self._port, 10.0)
        self._ws = websocket.create_connection(
            page["webSocketDebuggerUrl"], max_size=None, timeout=60
        )

    def _text_length(self) -> int:
        try:
            r = self._call(
                "Runtime.evaluate",
                expression="document.body ? document.body.innerText.length : 0",
                returnByValue=True,
            )
            return int(r.get("result", {}).get("value") or 0)
        except HeadlessError:
            return 0

    # ------------------------------------------------------------- render
    def render_pdf(
        self,
        url: str,
        *,
        min_text: int = MIN_TEXT,
        timeout: float = 30.0,
        patient: bool = False,
        should_cancel: Callable[[], bool] | None = None,
    ) -> bytes | None:
        """Τυπώνει τη σελίδα σε PDF.

        Επιστρέφει τα bytes του PDF, ή ``None`` αν η σελίδα δεν στοιχειοθετήθηκε
        (κενή προβολή — π.χ. πάροχος πίσω από interactive Blazor/Cloudflare).

        ``patient=True`` (για ορατό headed παράθυρο): δεν εγκαταλείπει γρήγορα σε
        κενή σελίδα — περιμένει όλο το ``timeout``, ώστε να προλάβει ο χρήστης να
        περάσει τυχόν έλεγχο «είστε άνθρωπος» στο ίδιο το παράθυρο.

        ``should_cancel``: αν επιστρέψει True κατά την αναμονή, η απόδοση κόβεται
        αμέσως με ``HeadlessCancelled`` (η ακύρωση γίνεται αισθητή σε <0.5s).
        """
        self._call("Page.navigate", url=url)
        textlen = self._await_render(min_text, timeout, patient=patient,
                                     should_cancel=should_cancel)
        if textlen < min_text:
            log.info("Render: κενή προβολή (%d χαρ.) για %s", textlen, url)
            return None
        result = self._call(
            "Page.printToPDF",
            printBackground=True,
            displayHeaderFooter=False,
            marginTop=0.3, marginBottom=0.3, marginLeft=0.3, marginRight=0.3,
        )
        pdf = base64.b64decode(result.get("data", ""))
        return pdf if pdf.startswith(b"%PDF") else None

    def save_via_button(
        self,
        url: str,
        download_dir: str | Path,
        *,
        min_text: int = MIN_TEXT,
        render_timeout: float = 40.0,
        download_timeout: float = 45.0,
        should_cancel: Callable[[], bool] | None = None,
    ) -> bytes | None:
        """Ανοίγει τη σελίδα του παρόχου και πατά το ΔΙΚΟ ΤΟΥ κουμπί «Αποθήκευση
        ως PDF», όπως θα έκανε ο χρήστης, και πιάνει το αρχείο που κατεβαίνει.

        Για παρόχους (π.χ. Epsilon DocViewer) που φτιάχνουν το επίσημο PDF μέσα
        στον browser (client-side) — δεν υπάρχει endpoint να ζητήσουμε και τίποτα
        να παρακάμψουμε. Χρησιμοποιείται σε **ορατό** παράθυρο ώστε, αν εμφανιστεί
        έλεγχος «είστε άνθρωπος», να τον περνά ο ίδιος ο χρήστης.

        Επιστρέφει τα bytes του PDF, ή ``None`` αν δεν στοιχειοθετήθηκε η σελίδα ή
        δεν βρέθηκε/δεν κατέβασε το κουμπί.
        """
        download_dir = Path(download_dir)
        download_dir.mkdir(parents=True, exist_ok=True)
        # Κατεύθυνε τις λήψεις στον δικό μας φάκελο, ώστε να πιάσουμε το αρχείο.
        for method in ("Browser.setDownloadBehavior", "Page.setDownloadBehavior"):
            try:
                self._call(method, behavior="allow",
                           downloadPath=str(download_dir), eventsEnabled=True)
                break
            except HeadlessError:
                continue

        before = {p.name for p in download_dir.glob("*")}
        self._call("Page.navigate", url=url)
        textlen = self._await_render(min_text, render_timeout,
                                     patient=self._headed, should_cancel=should_cancel)
        if textlen < min_text:
            log.info("save_via_button: κενή προβολή (%d χαρ.) για %s", textlen, url)
            return None

        clicked = self._call(
            "Runtime.evaluate", expression=_SAVE_PDF_CLICK_JS, returnByValue=True
        )
        if not clicked.get("result", {}).get("value"):
            log.info("save_via_button: δεν βρέθηκε κουμπί PDF στη σελίδα %s", url)
            return None

        # Το PDF φτιάχνεται client-side (αργεί) και μετά κατεβαίνει. Περιμένουμε να
        # εμφανιστεί ΝΕΟ, ολοκληρωμένο .pdf στον φάκελο (όχι .crdownload).
        deadline = time.time() + download_timeout
        while time.time() < deadline:
            if should_cancel and should_cancel():
                raise HeadlessCancelled()
            for p in download_dir.glob("*.pdf"):
                if p.name in before:
                    continue
                if p.with_suffix(p.suffix + ".crdownload").exists():
                    continue
                try:
                    data = p.read_bytes()
                except OSError:
                    continue
                if data.startswith(b"%PDF") and len(data) > 1000:
                    return data
            time.sleep(0.5)
        log.info("save_via_button: δεν εμφανίστηκε λήψη PDF εντός %ss", download_timeout)
        return None

    def _await_render(
        self, min_text: int, timeout: float, patient: bool = False,
        should_cancel: Callable[[], bool] | None = None,
    ) -> int:
        """Περιμένει να σταθεροποιηθεί το κείμενο της σελίδας."""
        deadline = time.time() + timeout
        start = time.time()
        last, stable, textlen = -1, 0, 0
        while time.time() < deadline:
            if should_cancel and should_cancel():
                raise HeadlessCancelled()
            textlen = self._text_length()
            if textlen == last:
                stable += 1
                # Σταθερό κείμενο πάνω από το κατώφλι -> έτοιμο.
                if textlen >= min_text and stable >= 3:
                    return textlen
                # Επίμονα κενό μετά από ~12s -> δεν πρόκειται να στοιχειοθετηθεί
                # (interactive Blazor/Cloudflare). Μη σπαταλάμε άλλο χρόνο — εκτός
                # αν είμαστε «υπομονετικοί» (ορατό παράθυρο: περιμένουμε τον
                # χρήστη να περάσει τον έλεγχο).
                if (not patient and textlen < min_text
                        and time.time() - start > 12 and stable >= 4):
                    return textlen
            else:
                stable, last = 0, textlen
            # Μικρά βήματα ύπνου ώστε η ακύρωση να γίνεται αισθητή γρήγορα.
            for _ in range(5):
                if should_cancel and should_cancel():
                    raise HeadlessCancelled()
                time.sleep(0.1)
        return textlen

    # -------------------------------------------------------------- cleanup
    def close(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:  # noqa: BLE001
                pass
            self._ws = None
        if self._proc is not None:
            self._kill_tree(self._proc)
            self._proc = None
        # Μόνιμο προφίλ: το κρατάμε (εκεί ζει η σύνδεση του χρήστη). Προσωρινό:
        # το καθαρίζουμε.
        if (
            self._profile and not self._persistent_profile
            and os.path.isdir(self._profile)
        ):
            shutil.rmtree(self._profile, ignore_errors=True)
            self._profile = None

    @staticmethod
    def _kill_tree(proc: subprocess.Popen) -> None:
        """Τερματίζει ΟΛΟΚΛΗΡΟ το δέντρο διεργασιών του browser.

        ΚΡΙΣΙΜΟ για τους πόρους: ένας Chrome/Edge δεν είναι μία διεργασία αλλά
        δέντρο (browser + renderer + gpu + utility). Το ``terminate()`` σκοτώνει
        μόνο τη ρίζα· τα παιδιά μένουν ορφανά, τρώνε μνήμη/CPU και «παγώνουν» το
        μηχάνημα. Στα Windows το ``taskkill /T /F`` καθαρίζει όλο το δέντρο.
        """
        if os.name == "nt" and proc.pid:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    timeout=10,
                )
            except Exception:  # noqa: BLE001
                pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

    def __enter__(self) -> "HeadlessRenderer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

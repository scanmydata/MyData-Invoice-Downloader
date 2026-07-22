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
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

#: Κάτω από τόσους χαρακτήρες ορατού κειμένου, θεωρούμε ότι η σελίδα δεν
#: στοιχειοθετήθηκε (κενή προβολή) — δεν αποθηκεύουμε λευκό PDF.
MIN_TEXT = 300


class HeadlessError(Exception):
    """Γενικό σφάλμα του headless renderer."""


class BrowserNotFound(HeadlessError):
    """Δεν βρέθηκε Edge ή Chrome στο σύστημα."""


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


def find_browser() -> Path | None:
    """Επιστρέφει τη διαδρομή του Edge (προτιμάται) ή του Chrome, ή None.

    Το Edge είναι προεγκατεστημένο σε κάθε Windows 10/11, οπότε στην πράξη
    υπάρχει σχεδόν πάντα κάτι διαθέσιμο.
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
    for path in candidates:
        if path and Path(path).exists():
            return Path(path)
    return None


def available() -> bool:
    """Αληθές αν υπάρχει και browser και το websocket-client."""
    try:
        import websocket  # noqa: F401
    except ImportError:
        return False
    return find_browser() is not None


class HeadlessRenderer:
    """Ανοίγει έναν headless browser και τυπώνει σελίδες σε PDF.

    Χρησιμοποιείται ως context manager ώστε ο browser και ο προσωρινός φάκελος
    προφίλ να καθαρίζονται πάντα::

        with HeadlessRenderer() as r:
            pdf = r.render_pdf(url)
    """

    def __init__(self, browser: Path | None = None, *, launch_timeout: float = 20.0):
        self._browser = browser or find_browser()
        if self._browser is None:
            raise BrowserNotFound(
                "Δεν βρέθηκε Microsoft Edge ή Google Chrome. Εγκαταστήστε έναν "
                "από τους δύο για τη λήψη των «μόνο online» παραστατικών."
            )
        self._proc: subprocess.Popen | None = None
        self._profile: str | None = None
        self._ws = None
        self._msg_id = 0
        self._launch(launch_timeout)

    # ------------------------------------------------------------- εκκίνηση
    def _launch(self, timeout: float) -> None:
        import websocket  # τοπικό import: η εξάρτηση είναι προαιρετική

        self._profile = tempfile.mkdtemp(prefix="tl_headless_")
        args = [
            str(self._browser),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-networking",
            "--mute-audio",
            "--hide-scrollbars",
            f"--user-data-dir={self._profile}",
            "--remote-debugging-port=0",
            # Απαραίτητο από Chrome/Edge 111+: αλλιώς το DevTools websocket
            # απορρίπτει τη σύνδεση με 403 (προστασία origin).
            "--remote-allow-origins=*",
            "about:blank",
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        port = self._read_port(timeout)
        page = self._first_page_target(port, timeout)
        self._ws = websocket.create_connection(
            page["webSocketDebuggerUrl"], max_size=None, timeout=60
        )
        self._call("Page.enable")

    def _read_port(self, timeout: float) -> int:
        assert self._profile is not None
        marker = Path(self._profile) / "DevToolsActivePort"
        deadline = time.time() + timeout
        while time.time() < deadline:
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
        self, url: str, *, min_text: int = MIN_TEXT, timeout: float = 30.0
    ) -> bytes | None:
        """Τυπώνει τη σελίδα σε PDF.

        Επιστρέφει τα bytes του PDF, ή ``None`` αν η σελίδα δεν στοιχειοθετήθηκε
        (κενή προβολή — π.χ. πάροχος πίσω από interactive Blazor/Cloudflare).
        """
        self._call("Page.navigate", url=url)
        textlen = self._await_render(min_text, timeout)
        if textlen < min_text:
            log.info("Headless: κενή προβολή (%d χαρ.) για %s", textlen, url)
            return None
        result = self._call(
            "Page.printToPDF",
            printBackground=True,
            displayHeaderFooter=False,
            marginTop=0.3, marginBottom=0.3, marginLeft=0.3, marginRight=0.3,
        )
        pdf = base64.b64decode(result.get("data", ""))
        return pdf if pdf.startswith(b"%PDF") else None

    def _await_render(self, min_text: int, timeout: float) -> int:
        """Περιμένει να σταθεροποιηθεί το κείμενο της σελίδας."""
        deadline = time.time() + timeout
        start = time.time()
        last, stable, textlen = -1, 0, 0
        while time.time() < deadline:
            textlen = self._text_length()
            if textlen == last:
                stable += 1
                # Σταθερό κείμενο πάνω από το κατώφλι -> έτοιμο.
                if textlen >= min_text and stable >= 3:
                    return textlen
                # Επίμονα κενό μετά από ~12s -> δεν πρόκειται να στοιχειοθετηθεί
                # (interactive Blazor/Cloudflare). Μη σπαταλάμε άλλο χρόνο.
                if textlen < min_text and time.time() - start > 12 and stable >= 4:
                    return textlen
            else:
                stable, last = 0, textlen
            time.sleep(0.5)
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
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                try:
                    self._proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            self._proc = None
        if self._profile and os.path.isdir(self._profile):
            shutil.rmtree(self._profile, ignore_errors=True)
            self._profile = None

    def __enter__(self) -> "HeadlessRenderer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

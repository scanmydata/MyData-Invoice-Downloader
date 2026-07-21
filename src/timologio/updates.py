"""Έλεγχος για νεότερη έκδοση, μέσω των Releases του GitHub.

Δεν υπάρχει auto-updater: το πρόγραμμα δεν κατεβάζει ούτε τρέχει τίποτα μόνο
του — απλώς ρωτά ποια είναι η τελευταία δημοσιευμένη έκδοση και, αν είναι
νεότερη, δείχνει σύνδεσμο. Η λήψη και η εγκατάσταση μένουν ρητά στον χρήστη.
"""

from __future__ import annotations

from dataclasses import dataclass

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

    @property
    def is_newer(self) -> bool:
        return parse_version(self.latest) > parse_version(self.current)


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
    return UpdateInfo(current=current, latest=tag.lstrip("vV") or "?", url=url)

"""Ευγένεια ανά πάροχο.

Μετρημένη κατανομή σε δείγμα 291 URL: impact.gr 174, epsilonnet ~83. Ένα
unbounded pool θα σφυροκοπούσε δύο hosts και θα άφηνε τους υπόλοιπους 8
αδρανείς. Ένα semaphore ανά host κρατά τον παραλληλισμό εκεί που ωφελεί.
"""

from __future__ import annotations

import threading


class HostPool:
    def __init__(self, max_per_host: int = 2) -> None:
        self._default = max_per_host
        self._lock = threading.Lock()
        self._sems: dict[str, threading.Semaphore] = {}
        self._limits: dict[str, int] = {}

    def _sem(self, host: str) -> threading.Semaphore:
        with self._lock:
            if host not in self._sems:
                self._sems[host] = threading.Semaphore(self._default)
                self._limits[host] = self._default
            return self._sems[host]

    def acquire(self, host: str) -> None:
        self._sem(host).acquire()

    def release(self, host: str) -> None:
        self._sem(host).release()

    def throttle(self, host: str) -> None:
        """Μετά από 429: στενεύει μόνιμα *αυτόν* τον host κατά ένα permit.

        Οι υπόλοιποι πάροχοι δεν επηρεάζονται.
        """
        with self._lock:
            current = self._limits.get(host, self._default)
            if current > 1:
                self._limits[host] = current - 1
                self._sems[host].acquire(blocking=False)

    def limit_for(self, host: str) -> int:
        with self._lock:
            return self._limits.get(host, self._default)


class host_slot:
    """Context manager: `with host_slot(pool, host): ...`"""

    def __init__(self, pool: HostPool, host: str) -> None:
        self._pool = pool
        self._host = host

    def __enter__(self) -> None:
        self._pool.acquire(self._host)

    def __exit__(self, *exc: object) -> None:
        self._pool.release(self._host)

"""Poller thread that periodically reads Neware channel status and forwards it to the GUI.

Unlike the other workers, this one is meant to be created ONCE (persistent for the life of
the GUI) instead of being created/destroyed every time the user toggles auto-refresh on/off.
The "on/off" button just calls resume()/pause() on the same long-lived thread — it never
tears down and recreates the underlying QThread. This avoids ever having two poller threads
alive at once (which could otherwise both hit the Neware socket at the same time).

- resume() / pause() : toggle polling on/off (used by the auto-refresh button)
- stop()             : permanently end the thread (used only on app close)
"""
import time
import threading
from PyQt6.QtCore import QThread, pyqtSignal


class StatusPoller(QThread):
    statuses = pyqtSignal(list)    # per-channel status list
    failed = pyqtSignal(str)

    def __init__(self, neware, interval=5.0):
        super().__init__()
        self.neware = neware
        self.interval = interval
        self._running = True                # False only when the whole thread should end (app close)
        self._active = threading.Event()     # set = polling on, clear = polling off (paused)

    def resume(self):
        """Turn polling on. Wakes the thread immediately if it was idle waiting to be resumed."""
        self._active.set()

    def pause(self):
        """Turn polling off. The thread keeps living, just stops calling status_all()."""
        self._active.clear()

    def stop(self):
        """Permanently end the thread. Only call this on app shutdown."""
        self._running = False
        self._active.set()      # in case it's idle waiting on _active.wait() below, wake it up

    def run(self):
        while self._running:
            if not self._active.is_set():
                self._active.wait()          # paused: block here (no CPU use) until resume()/stop() wakes us
                continue                      # re-check _running / _active from the top
            try:
                self.statuses.emit(self.neware.status_all())
            except Exception as e:
                self.failed.emit(str(e))
            # Sleep the interval in small slices so pause()/stop() stay responsive
            slept = 0.0
            while self._running and self._active.is_set() and slept < self.interval:
                time.sleep(0.2)
                slept += 0.2

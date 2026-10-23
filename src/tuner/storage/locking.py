"""Cross-platform advisory lock to serialise collection runs."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from types import TracebackType
from typing import IO

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class LockBusy(RuntimeError):
    """Raised when another process holds the lock past the timeout."""


class FileLock:
    """Exclusive lock on `path`, released automatically if we crash."""

    def __init__(self, path: Path, timeout: float = 0.0) -> None:
        self.path = path
        self.timeout = timeout
        self._fh: IO[bytes] | None = None

    def _try(self, fh: IO[bytes]) -> bool:
        """Attempt a non-blocking lock; True on success."""
        try:
            if sys.platform == "win32":
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def __enter__(self) -> FileLock:
        """Acquire the lock, waiting up to `timeout` seconds."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")  # noqa: SIM115 - held until exit
        deadline = time.monotonic() + self.timeout
        while not self._try(fh):
            if time.monotonic() >= deadline:
                fh.close()
                raise LockBusy(f"another tuner process holds {self.path}")
            time.sleep(0.1)
        self._fh = fh
        return self

    def __exit__(self, exc_type: type[BaseException] | None,
                 exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        """Release the lock."""
        if self._fh is None:
            return
        try:
            if sys.platform == "win32":
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None

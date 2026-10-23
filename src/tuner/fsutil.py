"""Small filesystem helpers: atomic writes, hashing, private files."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_bytes(path: Path, data: bytes, private: bool = True) -> None:
    """Write `data` to `path` atomically (temp file + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if private and sys.platform != "win32":
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, text: str, private: bool = True) -> None:
    """Write UTF-8 `text` to `path` atomically."""
    atomic_write_bytes(path, text.encode("utf-8"), private)


def canonical_json(obj: Any) -> str:
    """Serialise deterministically (sorted keys, compact) for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def sha256_text(text: str) -> str:
    """Return the hex SHA-256 digest of `text`."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str | None:
    """Return the SHA-256 digest of a file, or None if unreadable."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None

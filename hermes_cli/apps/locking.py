"""Small cross-process lock used for app registry transactions."""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator


class AppLockTimeout(TimeoutError):
    pass


_fallback_guard = threading.Lock()
_fallback_locks: dict[str, threading.Lock] = {}


def _fallback_lock(path: Path) -> threading.Lock:
    key = str(path.absolute())
    with _fallback_guard:
        return _fallback_locks.setdefault(key, threading.Lock())


def _try_lock(handle: BinaryIO) -> bool:
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except ImportError:
        pass
    except BlockingIOError:
        return False

    try:
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except ImportError:
        return False
    except OSError:
        return False


def _unlock(handle: BinaryIO) -> None:
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return
    except ImportError:
        pass

    try:
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    except (ImportError, OSError):
        pass


@contextmanager
def app_file_lock(path: Path, *, timeout_seconds: float = 10.0) -> Iterator[None]:
    """Acquire an exclusive profile lock with a bounded wait."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("app lock path cannot be a symlink")

    fallback = _fallback_lock(path)
    if not fallback.acquire(timeout=timeout_seconds):
        raise AppLockTimeout(f"timed out acquiring app lock: {path.name}")

    handle: BinaryIO | None = None
    locked = False
    try:
        handle = path.open("a+b")
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout_seconds
        while not _try_lock(handle):
            if time.monotonic() >= deadline:
                raise AppLockTimeout(f"timed out acquiring app lock: {path.name}")
            time.sleep(0.05)
        locked = True
        yield
    finally:
        if locked and handle is not None:
            _unlock(handle)
        if handle is not None:
            handle.close()
        fallback.release()


__all__ = ["AppLockTimeout", "app_file_lock"]

"""Single-instance guard for the intraday scanner.

Several launchers (morning task, market watchdog, master self-healing, auto-start retries) can start the scanner within minutes of each other, and a launcher
without admin rights cannot see a scanner started by an elevated one. The lock is therefore taken inside the scanner process itself: an OS-level exclusive lock on
a file that the OS releases the moment the process dies, whatever the cause, so a crash never leaves a stale lock behind.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import IO

_HELD: dict[str, IO[bytes]] = {}


def acquire(path: Path) -> bool:
    """True if this process now holds the lock named by `path` (kept until exit); False if another live process holds it."""
    key = str(path)
    if key in _HELD:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()).encode())
    handle.flush()
    _HELD[key] = handle
    return True


def release(path: Path) -> None:
    handle = _HELD.pop(str(path), None)
    if handle is not None:
        handle.close()

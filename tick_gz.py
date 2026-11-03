"""Salvage and repair of the recorders' gzip files (DATA ONLY).

The recorders append a new gzip member every time they (re)start. When a recorder dies without closing its files (a crash, a kill) the last member of each file is cut off, and Python's gzip
reader then stops at that point and cannot read anything written after it: on 23 Oct a crash at 09:12 and a kill at 09:29 left every tick file readable only up to 09:12, with the rest of the day
intact on disk behind the break. This reads such a file member by member (every member that starts with a gzip header is decompressed on its own and whatever a cut-off member holds is kept)
and can rewrite the file as one clean member.

    read_text(path) -> (text, members, damaged)       the recovered text of the whole file
    repair(path)    -> (rows recovered, damaged members)   rewrites the file in place (atomically) only when it was damaged

    python tick_gz.py data/ticks/2026-10-23 [more folders]       repair every *.csv.gz in the folders
"""

from __future__ import annotations

import gzip
import os
import sys
import zlib
from pathlib import Path

MAGIC = b"\x1f\x8b\x08"


def _decode_member(raw: bytes, start: int) -> tuple[bytes, bool, int] | None:
    """Decode the gzip member starting at `start`. Returns (data, complete, next position), or None when nothing decodes here (a header-like byte pattern inside other data).

    1. The whole rest of the file is tried first: when the member is intact its end marker and checksum (verified by zlib) prove it, even if it contains a stray header-like pattern.
    2. Otherwise the member was cut off (a crash / kill) and the next member's header follows it directly: decode only up to that header and keep what decoded cleanly before the cut."""
    d = zlib.decompressobj(wbits=31)
    try:
        data = d.decompress(raw[start:])
        if d.eof:
            return data, True, len(raw) - len(d.unused_data)
    except zlib.error:
        pass
    nxt = raw.find(MAGIC, start + 3)
    end = nxt if nxt >= 0 else len(raw)
    d = zlib.decompressobj(wbits=31)
    try:
        data = d.decompress(raw[start:end])
    except zlib.error:
        return None
    return (data, False, end) if data else None


def _members(raw: bytes) -> list[tuple[bytes, bool]]:
    """[(decompressed bytes, damaged)] for every gzip member in `raw`, in order. A cut-off member keeps whatever decoded cleanly before the cut."""
    out: list[tuple[bytes, bool]] = []
    pos = 0
    while True:
        start = raw.find(MAGIC, pos)
        if start < 0:
            break
        got = _decode_member(raw, start)
        if got is None:
            pos = start + 3
            continue
        data, complete, nxt = got
        out.append((data, not complete))
        pos = max(nxt, start + 3)
    return out


def read_text(path: Path | str) -> tuple[str, int, int]:
    """(text, members found, damaged members). Each member holds the CSV header only in the first one, so later headers (a restart that wrote one) are dropped."""
    raw = Path(path).read_bytes()
    parts, damaged = [], 0
    for data, bad in _members(raw):
        text = data.decode("utf-8", errors="replace")
        if bad:
            damaged += 1
            text = text[: text.rfind("\n") + 1]            # drop the half-written last line of a cut-off member
        parts.append(text)
    if not parts:
        return "", 0, 0
    header = parts[0].split("\n", 1)[0]
    merged = [parts[0]]
    for t in parts[1:]:
        if t.startswith(header + "\n"):
            t = t[len(header) + 1:]
        merged.append(t)
    return "".join(merged), len(parts), damaged


def is_damaged(path: Path | str) -> bool:
    try:
        with gzip.open(path, "rb") as h:
            while h.read(1 << 20):
                pass
        return False
    except (EOFError, zlib.error, OSError):
        return True


def repair(path: Path | str) -> tuple[int, int]:
    """Rewrite a damaged file as one clean gzip member. Returns (data rows recovered, damaged members); (0, 0) and no change when the file reads fine."""
    path = Path(path)
    if not is_damaged(path):
        return 0, 0
    text, _members_n, damaged = read_text(path)
    tmp = path.with_suffix(path.suffix + ".repair")
    with gzip.open(tmp, "wb") as h:
        h.write(text.encode("utf-8"))
    os.replace(tmp, path)
    return max(0, text.count("\n") - 1), damaged


def main() -> int:
    total_rows = fixed = 0
    for folder in sys.argv[1:]:
        for p in sorted(Path(folder).glob("*.csv.gz")):
            rows, bad = repair(p)
            if rows or bad:
                fixed += 1
                total_rows += rows
    print(f"repaired {fixed} files, {total_rows:,} rows recovered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

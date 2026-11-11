"""Resumable downloads with mirror fallback, and file hashing."""

from __future__ import annotations

import hashlib
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from dblock import __version__

CHUNK = 1024 * 1024
USER_AGENT = f"dblock/{__version__}"


class DownloadError(Exception):
    pass


def hash_file(path: Path, algorithms: tuple[str, ...] = ("sha256",), progress: str = "") -> dict[str, str]:
    hashers = {name: hashlib.new(name) for name in algorithms}
    _hash_into(hashers, path, progress)
    return {name: h.hexdigest() for name, h in hashers.items()}


def _hash_into(hashers: dict, path: Path, progress: str = "") -> None:
    total = path.stat().st_size
    done = 0
    reporter = _Progress(progress, total) if progress else None
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            for h in hashers.values():
                h.update(chunk)
            done += len(chunk)
            if reporter:
                reporter.update(done)
    if reporter:
        reporter.finish()


def download(urls: list[str], dest: Path, expected_size: int = 0, retries: int = 3, quiet: bool = False,
             algorithms: tuple[str, ...] = ("sha256",)) -> tuple[str, dict[str, str]]:
    """Download to dest, resuming a partial `dest.part`, hashing as it writes.

    Returns the URL that worked and the file's hex digests, so the archive need not be read again.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    errors = []
    for url in urls:
        for attempt in range(1, retries + 1):
            try:
                digests = _fetch(url, part, expected_size, quiet, algorithms)
                part.replace(dest)
                return url, digests
            except (urllib.error.URLError, OSError, DownloadError) as exc:
                errors.append(f"{url} (attempt {attempt}): {exc}")
                if not quiet:
                    print(f"  download problem: {exc}; retrying" if attempt < retries else f"  giving up on {url}", file=sys.stderr)
                time.sleep(min(2 ** attempt, 10) if attempt < retries else 0)
    raise DownloadError("all download sources failed:\n  " + "\n  ".join(errors))


def _fetch(url: str, part: Path, expected_size: int, quiet: bool, algorithms: tuple[str, ...]) -> dict[str, str]:
    hashers = {name: hashlib.new(name) for name in algorithms}
    have = part.stat().st_size if part.exists() else 0
    if expected_size and have > expected_size:
        part.unlink()
        have = 0
    if have:  # bytes kept from an earlier, interrupted attempt
        progress = "" if quiet or have < 256 * 1024 * 1024 else "  hashing partial download"
        _hash_into(hashers, part, progress)
    if expected_size and have == expected_size:
        return {name: h.hexdigest() for name, h in hashers.items()}
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if have:
        request.add_header("Range", f"bytes={have}-")
    with urllib.request.urlopen(request, timeout=60) as response:
        status = getattr(response, "status", 200)
        if have and status != 206:
            have = 0  # server ignored the Range header: start again
            hashers = {name: hashlib.new(name) for name in algorithms}
        length = response.headers.get("Content-Length")
        total = (have + int(length)) if length else expected_size
        if expected_size and total and total != expected_size:
            raise DownloadError(f"server reports {total} bytes, recipe expects {expected_size}")
        reporter = None if quiet else _Progress(f"  downloading {part.name[:-5]}", total, start=have)
        with part.open("ab" if have else "wb") as out:
            done = have
            while chunk := response.read(CHUNK):
                out.write(chunk)
                for h in hashers.values():
                    h.update(chunk)
                done += len(chunk)
                if reporter:
                    reporter.update(done)
        if reporter:
            reporter.finish()
    size = part.stat().st_size
    if expected_size and size != expected_size:
        raise DownloadError(f"incomplete download: {size} of {expected_size} bytes")
    return {name: h.hexdigest() for name, h in hashers.items()}


class _Progress:
    """Progress on one updating line; small, fast jobs print nothing."""

    def __init__(self, label: str, total: int, start: int = 0):
        self.label, self.total, self.done = label, total, start
        self.started = self.last = time.monotonic()
        self.shown = False

    def update(self, done: int) -> None:
        self.done = done
        now = time.monotonic()
        if now - self.last >= 2:
            self.last = now
            self._show()

    def _show(self) -> None:
        self.shown = True
        if self.total:
            text = f"{self.done / self.total:6.1%} of {human_bytes(self.total)}"
        else:
            text = human_bytes(self.done)
        print(f"\r{self.label}: {text}", end="", file=sys.stderr)

    def finish(self) -> None:
        if self.shown:
            self._show()
            print(file=sys.stderr)


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"

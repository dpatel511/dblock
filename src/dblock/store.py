"""The local store: unpacked databases plus a per-file manifest.

Layout:  <store>/<name>/<release>/data/...         unpacked database
         <store>/<name>/<release>/manifest.json    per-file size and sha256
         <store>/.downloads/<filename>[.part]      archives (removed after unpacking)
"""

from __future__ import annotations

import contextlib
import fnmatch
import gzip
import hashlib
import json
import os
import shutil
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from dblock.download import hash_file

if os.name == "nt":
    import msvcrt
else:
    import fcntl

MANIFEST_VERSION = 1


class StoreError(Exception):
    pass


class StoreBusy(StoreError):
    pass


@contextlib.contextmanager
def lock(path: Path):
    """Exclusive, non-blocking lock on path. The OS releases it if the process dies.

    The lock file is left in place: deleting it would let two processes lock different files.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        try:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise StoreBusy(f"locked by another process: {path}") from None
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def default_store() -> Path:
    env = os.environ.get("DBLOCK_STORE")
    return Path(env) if env else Path.home() / ".dblock" / "store"


def install_dir(store: Path, name: str, release: str) -> Path:
    return store / name / release


def data_dir(store: Path, name: str, release: str) -> Path:
    return install_dir(store, name, release) / "data"


# ---------------------------------------------------------------- unpacking

def unpack(archive: Path, fmt: str, target: Path) -> None:
    """Unpack into target (which must not exist yet), rejecting unsafe paths."""
    tmp = target.with_name(target.name + ".unpacking")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        if fmt.startswith("tar"):
            _untar(archive, tmp)
        elif fmt == "zip":
            _unzip(archive, tmp)
        elif fmt == "gz":
            name = archive.name[:-3] if archive.name.endswith(".gz") else archive.name + ".out"
            with gzip.open(archive, "rb") as src, (tmp / name).open("wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
        elif fmt == "file":
            shutil.copy2(archive, tmp / archive.name)
        else:
            raise StoreError(f"unsupported format '{fmt}'")
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    if target.exists():
        shutil.rmtree(target)
    tmp.rename(target)


def _untar(archive: Path, dest: Path) -> None:
    with tarfile.open(archive, "r:*") as tar:
        if hasattr(tarfile, "data_filter"):
            try:
                tar.extractall(dest, filter="data")
            except tarfile.FilterError as exc:
                raise StoreError(f"refusing unsafe archive member: {exc}") from exc
            return
        for member in tar.getmembers():  # Python < 3.12 fallback
            _check_member(member.name)
            if member.issym() or member.islnk():
                _check_member(str(PurePosixPath(member.name).parent / member.linkname))
            if member.isdev():
                raise StoreError(f"refusing device file in archive: {member.name}")
        tar.extractall(dest)


def _unzip(archive: Path, dest: Path) -> None:
    with zipfile.ZipFile(archive) as zf:
        for name in zf.namelist():
            _check_member(name)
        zf.extractall(dest)


def _check_member(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise StoreError(f"refusing unsafe path in archive: {name}")


# ---------------------------------------------------------------- manifests

@dataclass
class Manifest:
    name: str
    release: str
    archive_sha256: str
    files: dict[str, tuple[int, str]] = field(default_factory=dict)  # relpath -> (size, sha256)

    @property
    def digest(self) -> str:
        return tree_digest(self.files)

    @property
    def total_bytes(self) -> int:
        return sum(size for size, _ in self.files.values())

    def save(self, path: Path) -> None:
        payload = {
            "manifest_version": MANIFEST_VERSION,
            "name": self.name,
            "release": self.release,
            "archive_sha256": self.archive_sha256,
            "tree_digest": self.digest,
            "files": {k: {"size": s, "sha256": h} for k, (s, h) in sorted(self.files.items())},
        }
        path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        if not path.exists():
            raise StoreError(f"no manifest at {path}; run `dblock fetch`")
        raw = json.loads(path.read_text(encoding="utf-8"))
        files = {k: (v["size"], v["sha256"]) for k, v in raw["files"].items()}
        return cls(raw["name"], raw["release"], raw["archive_sha256"], files)


def tree_digest(files: dict[str, tuple[int, str]]) -> str:
    h = hashlib.sha256()
    for rel in sorted(files):
        size, digest = files[rel]
        h.update(f"{rel}\t{size}\t{digest}\n".encode("utf-8"))
    return "sha256:" + h.hexdigest()


def walk(root: Path) -> dict[str, int]:
    """Regular files under root as posix relpath -> size."""
    out = {}
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            p = Path(dirpath) / fn
            out[p.relative_to(root).as_posix()] = p.stat().st_size
    return out


def build_manifest(name: str, release: str, archive_sha256: str, root: Path, quiet: bool = False) -> Manifest:
    files = {}
    for rel, size in sorted(walk(root).items()):
        label = "" if quiet or size < 256 * 1024 * 1024 else f"  hashing {rel}"
        files[rel] = (size, hash_file(root / rel, progress=label)["sha256"])
    return Manifest(name, release, archive_sha256, files)


# ---------------------------------------------------------------- checks

@dataclass
class VerifyResult:
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    size_changed: list[str] = field(default_factory=list)
    content_changed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.missing or self.extra or self.size_changed or self.content_changed)

    def summary(self, limit: int = 5) -> list[str]:
        lines = []
        for label, items in (("missing", self.missing), ("unexpected", self.extra),
                             ("size changed", self.size_changed), ("content changed", self.content_changed)):
            if items:
                shown = ", ".join(items[:limit]) + (f" (+{len(items) - limit} more)" if len(items) > limit else "")
                lines.append(f"{len(items)} {label}: {shown}")
        return lines


def verify(manifest: Manifest, root: Path, full: bool = False, quiet: bool = False) -> VerifyResult:
    result = VerifyResult()
    if not root.is_dir():
        result.missing = sorted(manifest.files)
        return result
    present = walk(root)
    result.missing = sorted(set(manifest.files) - set(present))
    result.extra = sorted(set(present) - set(manifest.files))
    for rel in sorted(set(manifest.files) & set(present)):
        size, digest = manifest.files[rel]
        if present[rel] != size:
            result.size_changed.append(rel)
        elif full:
            label = "" if quiet or size < 256 * 1024 * 1024 else f"  hashing {rel}"
            if hash_file(root / rel, progress=label)["sha256"] != digest:
                result.content_changed.append(rel)
    return result


def check_layout(root: Path, patterns: tuple[str, ...]) -> list[str]:
    """Return the layout patterns that match nothing under root."""
    if not patterns:
        return []
    paths = list(walk(root))
    dirs = {str(PurePosixPath(p).parent) for p in paths}
    dirs |= {str(parent) for p in paths for parent in PurePosixPath(p).parents}
    candidates = paths + [d + "/" for d in dirs if d != "."]
    return [pat for pat in patterns if not any(fnmatch.fnmatchcase(c, pat) for c in candidates)]


@dataclass
class TreeDiff:
    added: list[str]
    removed: list[str]
    changed: list[str]
    unchanged: int


def diff(a: Manifest, b: Manifest) -> TreeDiff:
    added = sorted(set(b.files) - set(a.files))
    removed = sorted(set(a.files) - set(b.files))
    common = set(a.files) & set(b.files)
    changed = sorted(p for p in common if a.files[p] != b.files[p])
    return TreeDiff(added, removed, changed, len(common) - len(changed))

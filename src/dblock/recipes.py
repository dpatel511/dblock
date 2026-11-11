"""Load database recipes: one TOML file per database, listing its releases."""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path, PurePosixPath

FORMATS = {"tar.gz", "tar.xz", "tar.bz2", "tar", "zip", "gz", "file"}


class RecipeError(Exception):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    urls: tuple[str, ...]
    filename: str
    format: str
    checksum: str = ""  # upstream checksum as "md5:<hex>" or "sha256:<hex>"; empty if none published
    size: int = 0
    unpacked_size: int = 0  # bytes after unpacking, when measured; 0 = unknown
    date: str = ""
    tool_versions: str = ""  # e.g. ">=2.4.1,<=2.6.1"
    layout: tuple[str, ...] = ()  # paths (or glob patterns) that must exist after unpacking
    note: str = ""
    tool_path: str = ""  # what the tool should be pointed at, relative to the data directory ("." = itself)


@dataclass(frozen=True)
class Recipe:
    name: str
    description: str
    homepage: str
    releases: tuple[Release, ...]
    digest: str  # sha256 of the recipe file, recorded in the lockfile
    source: str
    tool: str = ""
    version_command: tuple[str, ...] = ()
    version_regex: str = r"(\d+(?:\.\d+)+)"
    citation: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)
    tool_env: str = ""  # environment variable the tool reads, e.g. "BAKTA_DB"

    def release(self, version: str | None) -> Release:
        if version is None:
            return self.releases[0]
        for rel in self.releases:
            if rel.version == version:
                return rel
        known = ", ".join(r.version for r in self.releases)
        raise RecipeError(f"{self.name} has no release '{version}'. Known releases: {known}")


def _parse(text: str, source: str) -> Recipe:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise RecipeError(f"{source}: invalid TOML: {exc}") from exc
    for key in ("name", "description", "homepage", "releases"):
        if key not in data:
            raise RecipeError(f"{source}: missing '{key}'")
    releases = []
    for raw in data["releases"]:
        for key in ("version", "urls", "filename", "format"):
            if key not in raw:
                raise RecipeError(f"{source}: release missing '{key}'")
        if raw["format"] not in FORMATS:
            raise RecipeError(f"{source}: unknown format '{raw['format']}' (use one of {sorted(FORMATS)})")
        checksum = raw.get("checksum", "")
        if checksum and checksum.split(":", 1)[0] not in ("md5", "sha256"):
            raise RecipeError(f"{source}: checksum must start with 'md5:' or 'sha256:'")
        tool_path = raw.get("tool_path", "")
        if tool_path and (PurePosixPath(tool_path).is_absolute() or ".." in PurePosixPath(tool_path).parts):
            raise RecipeError(f"{source}: tool_path must be relative to the data directory: '{tool_path}'")
        releases.append(Release(
            version=str(raw["version"]),
            urls=tuple(raw["urls"]),
            filename=raw["filename"],
            format=raw["format"],
            checksum=checksum,
            size=int(raw.get("size", 0)),
            unpacked_size=int(raw.get("unpacked_size", 0)),
            date=str(raw.get("date", "")),
            tool_versions=raw.get("tool_versions", ""),
            layout=tuple(raw.get("layout", ())),
            note=raw.get("note", ""),
            tool_path=tool_path,
        ))
    if not releases:
        raise RecipeError(f"{source}: no releases")
    return Recipe(
        name=data["name"],
        description=data["description"],
        homepage=data["homepage"],
        releases=tuple(releases),
        digest="sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
        source=source,
        tool=data.get("tool", ""),
        version_command=tuple(data.get("version_command", ())),
        version_regex=data.get("version_regex", r"(\d+(?:\.\d+)+)"),
        citation=data.get("citation", ""),
        notes=tuple(data.get("notes", ())),
        tool_env=data.get("tool_env", ""),
    )


def load_recipes(extra_dir: str | Path | None = None) -> dict[str, Recipe]:
    """Bundled recipes, overridden by recipes in extra_dir with the same name."""
    recipes: dict[str, Recipe] = {}
    bundled = resources.files("dblock") / "recipes"
    for entry in sorted(bundled.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".toml"):
            recipe = _parse(entry.read_text(encoding="utf-8"), f"bundled:{entry.name}")
            recipes[recipe.name] = recipe
    if extra_dir:
        directory = Path(extra_dir)
        if not directory.is_dir():
            raise RecipeError(f"recipe directory not found: {directory}")
        for path in sorted(directory.glob("*.toml")):
            recipe = _parse(path.read_text(encoding="utf-8"), str(path))
            recipes[recipe.name] = recipe
    return recipes


def parse_spec(spec: str) -> tuple[str, str | None]:
    """'gtdbtk@r232' -> ('gtdbtk', 'r232'); 'gtdbtk' -> ('gtdbtk', None)."""
    name, _, version = spec.partition("@")
    if not name:
        raise RecipeError(f"invalid database spec '{spec}' (expected NAME or NAME@RELEASE)")
    return name, (version or None)

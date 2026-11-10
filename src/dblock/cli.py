"""Command-line interface. Exit codes: 0 success, 1 problems found, 2 usage or runtime error."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

from dblock import __version__, compat, store
from dblock.download import DownloadError, download, hash_file, human_bytes
from dblock.lockfile import Entry, LockError, Lockfile
from dblock.recipes import Recipe, RecipeError, load_recipes, parse_spec

OK, PROBLEMS, ERROR = 0, 1, 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return ERROR
    try:
        return args.func(args)
    except (LockError, RecipeError, store.StoreError, DownloadError, compat.SpecError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return ERROR
    except KeyboardInterrupt:
        print("\ninterrupted; partial downloads are kept and resume on the next fetch", file=sys.stderr)
        return ERROR


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--lock", default=os.environ.get("DBLOCK_LOCK", "dblock.lock"),
                        help="lockfile path (default: ./dblock.lock or $DBLOCK_LOCK)")
    common.add_argument("--store", type=Path, default=None,
                        help="database store directory (default: $DBLOCK_STORE or ~/.dblock/store)")
    common.add_argument("--recipes", default=os.environ.get("DBLOCK_RECIPES"),
                        help="extra recipe directory; overrides bundled recipes with the same name")
    common.add_argument("-q", "--quiet", action="store_true", help="only print results and errors")

    parser = argparse.ArgumentParser(
        prog="dblock",
        description="Lockfiles for bioinformatics reference databases: pin, fetch, verify and cite exact releases.",
    )
    parser.add_argument("--version", action="version", version=f"dblock {__version__}")
    sub = parser.add_subparsers(title="commands", metavar="COMMAND")

    def cmd(name: str, func, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, parents=[common], help=help_text, description=help_text)
        p.set_defaults(func=func)
        return p

    p = cmd("recipes", cmd_recipes, "list known databases and their releases")
    p.add_argument("name", nargs="?", help="show details for one database")

    p = cmd("add", cmd_add, "pin database releases in the lockfile (NAME or NAME@RELEASE)")
    p.add_argument("specs", nargs="+", metavar="NAME[@RELEASE]")

    p = cmd("remove", cmd_remove, "remove databases from the lockfile (store files are kept)")
    p.add_argument("names", nargs="+")

    p = cmd("fetch", cmd_fetch, "download, check and unpack locked databases into the store")
    p.add_argument("names", nargs="*", help="default: all locked databases")
    p.add_argument("--keep-archive", action="store_true", help="keep the downloaded archive after unpacking")
    p.add_argument("--force", action="store_true", help="re-download even if already installed")

    p = cmd("verify", cmd_verify, "check installed files against the lockfile (fast: names and sizes)")
    p.add_argument("names", nargs="*")
    p.add_argument("--full", action="store_true", help="also re-hash every file (slow for large databases)")

    p = cmd("status", cmd_status, "show locked databases, install state and checksum origin")

    p = cmd("path", cmd_path, "print the installed data directory of a database (for scripts and pipelines)")
    p.add_argument("name")

    p = cmd("check-compat", cmd_check_compat, "check installed tool versions against each database release")
    p.add_argument("names", nargs="*")

    p = cmd("provenance", cmd_provenance, "print exact database provenance for a methods section or report")
    p.add_argument("--format", choices=("text", "json"), default="text")

    p = cmd("diff", cmd_diff, "compare the files of two installed releases of one database")
    p.add_argument("name")
    p.add_argument("release_a")
    p.add_argument("release_b")
    p.add_argument("--limit", type=int, default=20, help="paths to list per category (default 20)")
    return parser


# ------------------------------------------------------------------ helpers

def _store(args) -> Path:
    return args.store if args.store else store.default_store()


def _log(args, message: str) -> None:
    if not args.quiet:
        print(message, file=sys.stderr)


def _recipe_for(entry: Entry, recipes: dict[str, Recipe], args) -> Recipe | None:
    recipe = recipes.get(entry.name)
    if recipe and recipe.digest != entry.recipe_digest:
        _log(args, f"  note: the {entry.name} recipe changed since it was locked; the lockfile values are used")
    return recipe


# ------------------------------------------------------------------ commands

def cmd_recipes(args) -> int:
    recipes = load_recipes(args.recipes)
    if args.name:
        r = recipes.get(args.name)
        if not r:
            raise RecipeError(f"unknown database '{args.name}'. Known: {', '.join(sorted(recipes))}")
        print(f"{r.name}: {r.description}\n  homepage: {r.homepage}\n  recipe: {r.source}")
        if r.citation:
            print(f"  cite: {r.citation}")
        for note in r.notes:
            print(f"  note: {note}")
        print("  releases (newest first):")
        for rel in r.releases:
            checksum = rel.checksum.split(":")[0] if rel.checksum else "none upstream"
            tools = f"  {r.tool} {rel.tool_versions}" if rel.tool_versions else ""
            size = human_bytes(rel.size) if rel.size else "size unknown"
            print(f"    {rel.version:<22} {rel.date or '-':<11} {size:>9}  checksum: {checksum:<13}{tools}")
            if rel.note:
                print(f"      {rel.note}")
        return OK
    width = max(len(n) for n in recipes)
    for name in sorted(recipes):
        r = recipes[name]
        print(f"{name:<{width}}  {', '.join(rel.version for rel in r.releases)}")
    return OK


def cmd_add(args) -> int:
    recipes = load_recipes(args.recipes)
    lock = Lockfile.load(args.lock, must_exist=False)
    for spec in args.specs:
        name, version = parse_spec(spec)
        recipe = recipes.get(name)
        if not recipe:
            raise RecipeError(f"unknown database '{name}'. Known: {', '.join(sorted(recipes))}")
        release = recipe.release(version)
        old = lock.entries.get(name)
        if old and old.release == release.version:
            _log(args, f"{name}@{release.version} is already locked")
            continue
        lock.entries[name] = Entry.from_recipe(recipe, release)
        what = f"replaced {old.release} with" if old else "locked"
        latest = " (newest known release)" if version is None else ""
        _log(args, f"{name}: {what} {release.version}{latest}")
    lock.save()
    return OK


def cmd_remove(args) -> int:
    lock = Lockfile.load(args.lock)
    for name in args.names:
        lock.get(name)
        del lock.entries[name]
        _log(args, f"{name}: removed from {lock.path}")
    lock.save()
    return OK


def cmd_fetch(args) -> int:
    lock = Lockfile.load(args.lock)
    recipes = load_recipes(args.recipes)
    root = _store(args)
    problems = 0
    for entry in lock.select(args.names):
        _log(args, f"{entry.name}@{entry.release}")
        target = store.data_dir(root, entry.name, entry.release)
        manifest_path = store.install_dir(root, entry.name, entry.release) / "manifest.json"
        if manifest_path.exists() and not args.force:
            manifest = store.Manifest.load(manifest_path)
            if entry.tree_digest and manifest.digest != entry.tree_digest:
                print(f"  PROBLEM: installed copy differs from the lockfile (digest {manifest.digest}); "
                      f"use --force to re-fetch", file=sys.stderr)
                problems += 1
                continue
            if not entry.fetched:
                _record(entry, manifest)
            _log(args, f"  already installed at {target}")
            continue
        recipe = _recipe_for(entry, recipes, args)
        size = 0
        layout: tuple[str, ...] = ()
        if recipe:
            try:
                rel = recipe.release(entry.release)
                size, layout = rel.size, rel.layout
            except RecipeError:
                pass
        archive = root / ".downloads" / entry.filename
        used = download(entry.urls, archive, expected_size=size, quiet=args.quiet)
        _log(args, f"  downloaded from {used}")

        algorithms = ["sha256"]
        upstream_algo, _, upstream_hex = entry.upstream_checksum.partition(":")
        if upstream_algo == "md5":
            algorithms.append("md5")
        digests = hash_file(archive, tuple(algorithms), progress="" if args.quiet else "  hashing archive")
        if upstream_hex and digests[upstream_algo] != upstream_hex.lower():
            archive.rename(archive.with_name(archive.name + ".bad"))
            print(f"  PROBLEM: {upstream_algo} mismatch: upstream says {upstream_hex}, got {digests[upstream_algo]}. "
                  f"Kept as {archive.name}.bad", file=sys.stderr)
            problems += 1
            continue
        if entry.archive_sha256 and digests["sha256"] != entry.archive_sha256:
            archive.rename(archive.with_name(archive.name + ".bad"))
            print(f"  PROBLEM: the file served now differs from the locked archive "
                  f"(locked sha256 {entry.archive_sha256}, got {digests['sha256']}). "
                  f"Upstream may have replaced it. Kept as {archive.name}.bad", file=sys.stderr)
            problems += 1
            continue
        origin = "upstream-verified" if upstream_hex else "first-download"
        _log(args, "  checksum: " + ("matches upstream " + upstream_algo if upstream_hex
                                     else "no upstream checksum; recording sha256 from this download"))

        _log(args, f"  unpacking ({entry.format})")
        store.unpack(archive, entry.format, target)
        missing = store.check_layout(target, layout)
        if missing:
            print(f"  PROBLEM: unpacked files do not match the expected layout; missing: {', '.join(missing)}",
                  file=sys.stderr)
            problems += 1
        manifest = store.build_manifest(entry.name, entry.release, digests["sha256"], target, args.quiet)
        manifest.save(manifest_path)
        if entry.tree_digest and manifest.digest != entry.tree_digest:
            print(f"  PROBLEM: unpacked contents differ from the lockfile digest", file=sys.stderr)
            problems += 1
        entry.archive_sha256 = digests["sha256"]
        if not entry.checksum_origin:
            entry.checksum_origin = origin
        _record(entry, manifest)
        if not args.keep_archive:
            archive.unlink()
        _log(args, f"  installed {human_bytes(manifest.total_bytes)} in {len(manifest.files)} files at {target}")
        lock.save()
    lock.save()
    return PROBLEMS if problems else OK


def _record(entry: Entry, manifest: store.Manifest) -> None:
    entry.tree_digest = manifest.digest
    entry.files = len(manifest.files)
    entry.bytes = manifest.total_bytes
    if not entry.archive_sha256:
        entry.archive_sha256 = manifest.archive_sha256
    entry.fetched_at = entry.fetched_at or dt.date.today().isoformat()


def cmd_verify(args) -> int:
    lock = Lockfile.load(args.lock)
    root = _store(args)
    problems = 0
    for entry in lock.select(args.names):
        label = f"{entry.name}@{entry.release}"
        if not entry.fetched:
            print(f"{label}: NOT FETCHED (run `dblock fetch {entry.name}`)")
            problems += 1
            continue
        manifest_path = store.install_dir(root, entry.name, entry.release) / "manifest.json"
        if not manifest_path.exists():
            print(f"{label}: NOT INSTALLED in {root}")
            problems += 1
            continue
        manifest = store.Manifest.load(manifest_path)
        if manifest.digest != entry.tree_digest:
            print(f"{label}: MISMATCH installed manifest {manifest.digest} != locked {entry.tree_digest}")
            problems += 1
            continue
        result = store.verify(manifest, store.data_dir(root, entry.name, entry.release), args.full, args.quiet)
        mode = "full" if args.full else "fast"
        if result.ok:
            print(f"{label}: OK ({mode}; {entry.files} files, {human_bytes(entry.bytes)})")
        else:
            problems += 1
            print(f"{label}: FAILED ({mode})")
            for line in result.summary():
                print(f"  {line}")
    return PROBLEMS if problems else OK


def cmd_status(args) -> int:
    lock = Lockfile.load(args.lock)
    root = _store(args)
    if not lock.entries:
        print("lockfile is empty")
        return OK
    print(f"lockfile: {lock.path}\nstore:    {root}\n")
    for entry in lock.select(None):
        installed = (store.install_dir(root, entry.name, entry.release) / "manifest.json").exists()
        state = "installed" if installed else ("locked, not on this machine" if entry.fetched else "not fetched")
        origin = entry.checksum_origin or "-"
        print(f"{entry.name:<18} {entry.release:<24} {state:<28} checksum: {origin}")
    return OK


def cmd_path(args) -> int:
    lock = Lockfile.load(args.lock)
    entry = lock.get(args.name)
    target = store.data_dir(_store(args), entry.name, entry.release)
    if not target.is_dir():
        print(f"error: {entry.name}@{entry.release} is not installed; run `dblock fetch {entry.name}`", file=sys.stderr)
        return PROBLEMS
    print(target)
    return OK


def cmd_check_compat(args) -> int:
    lock = Lockfile.load(args.lock)
    recipes = load_recipes(args.recipes)
    bad = 0
    for entry in lock.select(args.names):
        recipe = recipes.get(entry.name)
        command = recipe.version_command if recipe else ()
        regex = recipe.version_regex if recipe else r"(\d+(?:\.\d+)+)"
        result = compat.check(command, regex, entry.tool_versions)
        tool = entry.tool or "-"
        found = f" {result.tool_version}" if result.tool_version else ""
        print(f"{entry.name}@{entry.release}: {result.status.upper()} ({tool}{found}; {result.detail})")
        bad += result.status == "incompatible"
    return PROBLEMS if bad else OK


def cmd_provenance(args) -> int:
    lock = Lockfile.load(args.lock)
    recipes = load_recipes(args.recipes)
    rows = []
    for entry in lock.select(None):
        recipe = recipes.get(entry.name)
        rows.append({
            "name": entry.name,
            "release": entry.release,
            "source": entry.urls[0] if entry.urls else "",
            "archive_sha256": entry.archive_sha256,
            "checksum_origin": entry.checksum_origin,
            "tree_digest": entry.tree_digest,
            "fetched_at": entry.fetched_at,
            "citation": recipe.citation if recipe else "",
        })
    if args.format == "json":
        print(json.dumps({"dblock_version": __version__, "databases": rows}, indent=2))
        return OK
    print("Reference databases (pinned with dblock {}):".format(__version__))
    for row in rows:
        if not row["archive_sha256"]:
            print(f"- {row['name']} {row['release']} (not fetched yet; no checksum recorded)")
            continue
        origin = "verified against upstream checksum" if row["checksum_origin"] == "upstream-verified" \
            else "no upstream checksum published; hash recorded at first download"
        print(f"- {row['name']} {row['release']}, downloaded {row['fetched_at']} from {row['source']} "
              f"(archive SHA-256 {row['archive_sha256'][:16]}…, {origin}).")
        if row["citation"]:
            print(f"  Cite: {row['citation']}")
    return OK


def cmd_diff(args) -> int:
    root = _store(args)
    manifests = []
    for release in (args.release_a, args.release_b):
        path = store.install_dir(root, args.name, release) / "manifest.json"
        manifests.append(store.Manifest.load(path))
    d = store.diff(*manifests)
    print(f"{args.name}: {args.release_a} -> {args.release_b}")
    print(f"  {len(d.added)} added, {len(d.removed)} removed, {len(d.changed)} changed, {d.unchanged} unchanged files")
    for label, items in (("added", d.added), ("removed", d.removed), ("changed", d.changed)):
        for path in items[: args.limit]:
            print(f"  {label:<8} {path}")
        if len(items) > args.limit:
            print(f"  {label:<8} … {len(items) - args.limit} more")
    return OK


if __name__ == "__main__":
    sys.exit(main())

# dblock

**Lockfiles for bioinformatics reference databases.** Pin the exact releases an analysis uses, fetch and verify them, check they match your tool versions, and print provenance you can paste into a methods section.

> Status: early development (`0.1.2`). Commands and file formats may still change.

Tools like GTDB-Tk, Kraken 2, CheckM2 and Bakta depend on large reference databases. Each tool downloads its database differently, often fetching "latest", and pipelines usually record the tool version but not the database release or checksum. dblock adds the missing piece: a small `dblock.lock` file, committed with your code, that says exactly which database files were used.

## Install

Python 3.11 or newer. No other dependencies.

```bash
python -m pip install dblock
dblock --version
```

## Quick start

```bash
dblock recipes                       # known databases and releases
dblock recipes gtdbtk                # details: dates, sizes, checksums, compatible tool versions

dblock add gtdbtk@r226 checkm2       # pin releases (NAME or NAME@RELEASE) in ./dblock.lock
dblock fetch                         # download (resumable), check checksums, unpack, record hashes
dblock verify                        # fast check: file names and sizes
dblock verify --full                 # re-hash every file
dblock check-compat                  # are installed tools compatible with these releases?
dblock provenance                    # text for a methods section (or --format json)

export GTDBTK_DATA_PATH="$(dblock path gtdbtk)/release226"
```

Databases are stored in `$DBLOCK_STORE` (default `~/.dblock/store`), one folder per name and release, so several releases can live side by side on a shared server.

## What gets checked

| Check | When | What it catches |
|---|---|---|
| Upstream checksum (MD5/SHA-256) | `fetch`, when the provider publishes one | Corrupt or truncated downloads |
| Locked archive SHA-256 | `fetch` on another machine | Upstream silently replacing a file under the same name |
| Expected layout | `fetch` | Wrong or half-unpacked archives (e.g. missing `*.k2d` files) |
| Tree digest and per-file manifest | `verify` | Files deleted, added or modified after install |
| Tool-version rules | `check-compat` | Database release used with an incompatible tool version |

When a provider publishes no checksum (GTDB, one older Kraken 2 index), dblock records the SHA-256 of the first download and says so (`checksum_origin = "first-download"`). It never claims more than it checked.

[VALIDATION.md](VALIDATION.md) records real runs against upstream databases and the tools that use them.

## The lockfile

```toml
lock_version = 1

[databases.checkm2]
release = "3"
filename = "checkm2_database.tar.gz"
urls = ["https://zenodo.org/api/records/14897628/files/checkm2_database.tar.gz/content"]
upstream_checksum = "md5:07c10655620843b517d0df0c160d911f"
tool = "checkm2"
archive_sha256 = "…"            # recorded at first fetch
checksum_origin = "upstream-verified"
tree_digest = "sha256:…"        # digest of every unpacked file
files = 2
fetched_at = "2026-11-10"
```

The store location is machine-specific and deliberately not in the lockfile.

## Bundled recipes

| Name | Releases | Upstream checksum | Tool-version rules |
|---|---|---|---|
| `gtdbtk` | r232, r226, r220 | none published | from GTDB-Tk docs |
| `kraken2` | standard-8gb, pluspf, viral (2026-10-22, 2024-09-04) | MD5 (except standard-8gb-20240904) | none stated |
| `checkm2` | 3 (Zenodo) | MD5 | none stated |
| `bakta` | 6.0, 6.0-light (Zenodo) | MD5 | from `db-versions.json` |
| `bakta-galaxy-test` | 390 KB test database | MD5 | for trying dblock |

dblock always downloads from the official sources and never re-hosts data.

### Add your own recipe

A recipe is one TOML file. Put it in a folder and pass `--recipes FOLDER` (or set `$DBLOCK_RECIPES`); it overrides a bundled recipe with the same name.

```toml
name = "mydb"
description = "My reference database"
homepage = "https://example.org"
tool = "mytool"
version_command = ["mytool", "--version"]

[[releases]]                 # newest first
version = "2"
filename = "mydb-2.tar.gz"
format = "tar.gz"            # tar.gz, tar.xz, tar.bz2, tar, zip, gz or file
size = 123456
checksum = "md5:…"           # optional
tool_versions = ">=1.4,<2"   # optional
layout = ["mydb/index.bin"]  # optional: must exist after unpacking (globs allowed)
urls = ["https://example.org/mydb-2.tar.gz", "https://mirror.example.org/mydb-2.tar.gz"]
```

## Exit codes

`0` success · `1` problems found (failed verification, checksum mismatch, incompatible tool) · `2` usage or runtime error. Progress goes to stderr, results to stdout.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

Tests run against a local HTTP server and need no internet access.

## Licence

MIT

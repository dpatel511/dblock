# dblock

**Lockfiles for bioinformatics reference databases.** Pin the exact releases an analysis uses, fetch and verify them, check they match your tool versions, and print provenance you can paste into a methods section.

> Status: early development (`0.3.1`). Commands and file formats may still change.

Tools like GTDB-Tk, Kraken 2, CheckM2 and Bakta depend on large reference databases. Each tool downloads its database differently, and pipelines usually record the tool version but not the database release or checksum. dblock adds a small `dblock.lock` file, committed with your code, that says exactly which database files were used, plus commands that fetch, check and point the tools at them.

## What it prevents

The first four rows are problems users have reported in the tools' issue trackers; the last three are about reproducing an analysis and sharing databases on one server.

| Without dblock | With dblock |
|---|---|
| The tool is pointed at the wrong place, e.g. `GTDBTK_DATA_PATH` set to the downloaded `.tar.gz` instead of the unpacked folder ([GTDBTk#648](https://github.com/Ecogenomics/GTDBTk/issues/648)) | `eval "$(dblock env)"` sets each tool's variable to the folder or file it expects |
| A blocked or truncated download is saved as the database, e.g. an HTML "403 Forbidden" page from Zenodo ([bakta#419](https://github.com/oschwengers/bakta/issues/419)) | `fetch` refuses an error response or a file of the wrong size before saving it, checks the provider's checksum, and never installs a bad download (a checksum mismatch is kept as `.bad` for inspection) |
| A failed 30 GB download starts again from zero ([bakta#374](https://github.com/oschwengers/bakta/issues/374)) | `fetch` resumes from the partial file |
| The tool and database versions do not match, found only when the job fails ([bakta#406](https://github.com/oschwengers/bakta/issues/406)) | `dblock check-compat` checks before the run, where the recipe states a rule (GTDB-Tk, Bakta) |
| "Which GTDB release did you use?" The paper names the tool version only, but taxonomy changes between releases | `dblock provenance` prints release, source URL and checksum for the methods section |
| The same database on another machine, or a year later, is not the same file | `fetch` from the lockfile checks the archive's SHA-256 against the one recorded the first time |
| On a shared server, two people download the same 100+ GB package at once, or a download fills the disk hours in | One shared store with a lock per database, and a free-space check before downloading |

dblock does not build databases, run the tools, or fix problems between a tool and its own dependencies (see the Bakta note in `dblock recipes bakta`).

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
dblock check-compat --strict         # for CI: also fail on NO-RULE, TOOL-NOT-FOUND, UNKNOWN-VERSION
dblock provenance                    # text for a methods section (or --format json)

eval "$(dblock env)"                 # export GTDBTK_DATA_PATH, CHECKM2DB, ... for the locked databases
dblock path checkm2 --tool           # just the path the tool expects (here the .dmnd file)
```

| Recipe | Variable set by `dblock env` | `dblock path NAME --tool` points to |
|---|---|---|
| `gtdbtk` | `GTDBTK_DATA_PATH` | the `releaseNNN` folder |
| `kraken2` | `KRAKEN2_DEFAULT_DB` (used when `--db` is not given) | the index folder |
| `checkm2` | `CHECKM2DB` | `CheckM2_database/uniref100.KO.1.dmnd` |
| `bakta`, `bakta-galaxy-test` | `BAKTA_DB` | the `db` or `db-light` folder |
| `gunc` | `GUNC_DB` | the `.dmnd` file |
| `genomad` | `GENOMAD_DB` | the `genomad_db` folder |

`dblock env` prints POSIX shell syntax. `dblock path NAME` without `--tool` still prints the top-level data folder.

Databases are stored in `$DBLOCK_STORE` (default `~/.dblock/store`), one folder per name and release, so several releases can live side by side on a shared server.

Before downloading, `fetch` checks the store has room for the rest of the download plus the unpacked copy (the archive is removed afterwards). Where a recipe has no measured `unpacked_size`, it assumes the unpacked data is at least as large as the archive and says so. `fetch --no-space-check` skips the check, for example where reported free space does not match a quota.

On a shared store, two `fetch` runs never work on the same database or archive at once: the second reports that another dblock process is fetching it and exits 1; run it again when the first has finished. Locks are operating-system file locks in `<store>/.locks/`, released automatically if a process dies. On network filesystems (e.g. NFS) they are only as reliable as the server's lock support.

## What gets checked

| Check | When | What it catches |
|---|---|---|
| Upstream checksum (MD5/SHA-256) | `fetch`, when the provider publishes one | Corrupt or truncated downloads |
| Locked archive SHA-256 | `fetch` on another machine | Upstream silently replacing a file under the same name |
| Expected layout | `fetch` | Wrong or half-unpacked archives (e.g. missing `*.k2d` files) |
| Tree digest and per-file manifest | `verify` | Files deleted, added or modified after install |
| Tool-version rules | `check-compat` | Database release used with an incompatible tool version |

When a provider publishes no checksum (GTDB, one older Kraken 2 index), dblock records the SHA-256 of the first download and says so (`checksum_origin = "first-download"`). When a second lockfile uses a copy another lockfile already put in a shared store, it did not check the download itself, so `checksum_origin` stays empty and `provenance` says the origin was not recorded. It never claims more than it checked.

[VALIDATION.md](VALIDATION.md) records real runs against upstream databases and the tools that use them.

[docs/try-it.md](docs/try-it.md) walks through dblock in about 10 minutes with a 390 KB test database.

[docs/pipelines.md](docs/pipelines.md) shows dblock in Snakemake and Nextflow pipelines.

[CHANGELOG.md](CHANGELOG.md) lists the changes in each release.

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
| `gunc` | progenomes_2.1, progenomes_3, gtdb_214, gtdb_95 (Zenodo) | MD5 | none stated |
| `genomad` | 1.9 (Zenodo, NERSC mirror) | MD5 | from geNomad's `releases.txt` |

dblock always downloads from the official sources and never re-hosts data.

Not bundled: CheckV and AMRFinderPlus. Their own installers build an index after downloading (`diamond makedb`, `amrfinder_update`), and dblock does not build databases.

### Add your own recipe

A recipe is one TOML file. Put it in a folder and pass `--recipes FOLDER` (or set `$DBLOCK_RECIPES`); it overrides a bundled recipe with the same name.

```toml
name = "mydb"
description = "My reference database"
homepage = "https://example.org"
tool = "mytool"
version_command = ["mytool", "--version"]
tool_env = "MYTOOL_DB"       # optional: variable `dblock env` sets

[[releases]]                 # newest first
version = "2"
filename = "mydb-2.tar.gz"
format = "tar.gz"            # tar.gz, tar.xz, tar.bz2, tar, zip, gz or file
size = 123456
unpacked_size = 456789       # optional: measured size after unpacking, for the free-space check
checksum = "md5:…"           # optional
tool_versions = ">=1.4,<2"   # optional
layout = ["mydb/index.bin"]  # optional: must exist after unpacking (globs allowed)
tool_path = "mydb"           # optional: what the tool is pointed at, relative to the data folder
urls = ["https://example.org/mydb-2.tar.gz", "https://mirror.example.org/mydb-2.tar.gz"]
```

## Exit codes

`0` success · `1` problems found (failed verification, checksum mismatch, incompatible tool; with `check-compat --strict`, any result other than OK) · `2` usage or runtime error. Progress goes to stderr, results to stdout.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

Tests run against a local HTTP server and need no internet access.

## Licence

MIT

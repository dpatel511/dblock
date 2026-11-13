# Changelog

All notable changes to dblock. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/) (before 1.0, minor versions add features and patch versions fix bugs). Dates are the day the version was published on PyPI.

## [0.4.0] - 2026-11-13

### Added
- Recipe `card` (CARD 3.3.0, for RGI). CARD publishes no checksum, so dblock records the SHA-256 at first download; the recipe notes CARD's non-commercial terms. ([#24](https://github.com/dpatel511/dblock/pull/24))
- `dblock diff --against OTHER.lock` compares two lockfiles: releases that differ, databases pinned in only one, and the same release fetched as different copies (exit 1). ([#28](https://github.com/dpatel511/dblock/pull/28))
- `dblock fetch --prefer HOST` tries a recipe's URLs on that host first, for example a mirror that is faster from your network; the other URLs stay as fallbacks. ([#29](https://github.com/dpatel511/dblock/pull/29))
- `dblock provenance` prints each database's upstream release date, and its JSON output has a `release_date` field. ([#27](https://github.com/dpatel511/dblock/pull/27))

### Fixed
- `fetch` reuses a complete archive already in the store (kept with `--keep-archive`, or left by a fetch stopped while unpacking) instead of downloading it again, after the same size and checksum checks. ([#25](https://github.com/dpatel511/dblock/pull/25))
- The `gtdbtk` recipe now has GTDB's published MD5s for r232, r226 and r220; it wrongly said GTDB publishes none. Lockfiles pinned before this keep their first-download SHA-256. ([#26](https://github.com/dpatel511/dblock/pull/26))

## [0.3.1] - 2026-11-12

### Fixed
- `dblock provenance` no longer says "no upstream checksum published" for a database that another lockfile had already installed in a shared store. It now says the checksum origin was not recorded by this lockfile; the lockfile value is unchanged. ([#21](https://github.com/dpatel511/dblock/pull/21))

### Added
- `docs/pipelines.md`: Snakemake and Nextflow examples, tested on Linux. ([#20](https://github.com/dpatel511/dblock/pull/20))

## [0.3.0] - 2026-11-12

### Added
- Recipes `gunc` (progenomes_2.1, progenomes_3, gtdb_214, gtdb_95) and `genomad` (1.9), with upstream MD5s, tool paths and, for geNomad, a tool-version rule from its `releases.txt`. ([#18](https://github.com/dpatel511/dblock/pull/18))
- README section "What it prevents", linked to reported issues. ([#17](https://github.com/dpatel511/dblock/pull/17))

### Fixed
- The weekly recipe check no longer reports a newer version when a provider publishes several databases as versions of one Zenodo record. ([#18](https://github.com/dpatel511/dblock/pull/18))

## [0.2.0] - 2026-11-11

### Added
- `dblock env` prints `export` lines for each tool's database variable; `dblock path NAME --tool` prints the path the tool expects. ([#11](https://github.com/dpatel511/dblock/pull/11))
- `dblock check-compat --strict` fails unless every database is OK. ([#12](https://github.com/dpatel511/dblock/pull/12))
- `fetch` checks free space before downloading; `--no-space-check`; recipe field `unpacked_size`. ([#13](https://github.com/dpatel511/dblock/pull/13))
- `fetch` locks each database and archive in a shared store. ([#14](https://github.com/dpatel511/dblock/pull/14))
- Recipe fields `tool_env` and `tool_path`, set for all bundled recipes. ([#11](https://github.com/dpatel511/dblock/pull/11))

### Changed
- `fetch` hashes the archive while downloading instead of reading it again afterwards. ([#15](https://github.com/dpatel511/dblock/pull/15))

## [0.1.2] - 2026-11-10

### Changed
- `dblock status` says `present (not verified)` instead of `installed`. ([#9](https://github.com/dpatel511/dblock/pull/9))

### Added
- Bakta `6.0-light` recipe note on the AMRFinderPlus database mismatch with Bioconda's Bakta 1.12.2. ([#9](https://github.com/dpatel511/dblock/pull/9))
- `VALIDATION.md`: a recorded run with real databases and tools on Linux. ([#8](https://github.com/dpatel511/dblock/pull/8))
- Weekly CI check of recipe URLs, sizes and Zenodo checksums. ([#10](https://github.com/dpatel511/dblock/pull/10))

## [0.1.1] - 2026-11-10

### Fixed
- A failed layout check is no longer recorded as installed, a tree-digest mismatch no longer overwrites the locked digest, and a second rejected archive no longer crashes on Windows or replaces the earlier `.bad` file. ([#6](https://github.com/dpatel511/dblock/pull/6))

## [0.1.0] - 2026-11-10

First release.

### Added
- Commands `recipes`, `add`, `remove`, `fetch`, `verify`, `status`, `path`, `check-compat`, `provenance` and `diff`, and the `dblock.lock` format (`lock_version = 1`).
- Recipes `gtdbtk`, `kraken2` (including the 2026-10-22 indexes and upstream MD5s, [#2](https://github.com/dpatel511/dblock/pull/2)), `checkm2`, `bakta` and `bakta-galaxy-test`.
- Text output is plain ASCII, so redirected output is readable on Windows. ([#1](https://github.com/dpatel511/dblock/pull/1))

[0.4.0]: https://github.com/dpatel511/dblock/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/dpatel511/dblock/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/dpatel511/dblock/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/dpatel511/dblock/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/dpatel511/dblock/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/dpatel511/dblock/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/dpatel511/dblock/releases/tag/v0.1.0

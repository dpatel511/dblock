# Validation

A run of dblock against real upstream databases and the real tools that use them. Unit tests (which use a local test server) are separate; this file records what happened with real downloads.

Every result below was observed in the run described. Nothing is extrapolated to other databases, tool versions or platforms.

## 2026-11-10: dblock 0.1.1, Linux

**Environment**
- dblock 0.1.1, commit `809b44f`, installed from source into a venv outside the checkout
- Ubuntu 24.04.1 LTS on WSL2 (kernel 6.18.58.1), Python 3.13.13, 16 CPUs, 7 GB RAM
- Tools from Bioconda, one conda environment each: Kraken 2 2.17.2, CheckM2 1.1.0, Bakta 1.12.2, GTDB-Tk 2.8.0
- Unit tests on this machine against the installed package: 23/23 passed

**Inputs**
- phiX174, NCBI `NC_001422.1` (5,386 bp), FASTA sha256 `caa155c8…f4de2a`
- *Mycoplasmoides genitalium* G37, NCBI `NC_000908.2` (580,076 bp), FASTA sha256 `cc21ace7…a8ccc9`
- `reads.fasta`: 200 × 150 bp reads cut at even steps from each genome (400 reads), sha256 `3e5084b8…506856`

### Summary

| Check | Result |
|---|---|
| `check-compat` reads real tool versions | Pass |
| Kraken 2 viral 2026-10-22: fetch, verify, classify reads | Pass |
| CheckM2 3: interrupted download resumes, `checkm2 testrun` | Pass |
| Bakta 6.0 light: fetch, verify, annotate a genome | Pass, but only after updating Bakta's bundled AMRFinderPlus database outside the store (see below) |
| Store unchanged after the tools ran (`verify --full`) | Pass |
| Same lockfile hashes on Windows and Linux (Kraken 2 viral) | Pass |

### 1. Tool-version checks

`--version` output was matched by the recipes' default pattern for all four tools (`Kraken version 2.17.2`, `1.1.0`, `bakta 1.12.2`, `gtdbtk: version 2.8.0`). CheckM2 prints many TensorFlow warnings on stderr; dblock reads stdout first and found `1.1.0`.

| Locked release | Rule | Result | Exit |
|---|---|---|---|
| `gtdbtk@r232` | `>=2.7.0` | OK (2.8.0) | 0 |
| `gtdbtk@r226` | `>=2.4.1,<=2.6.1` | INCOMPATIBLE (2.8.0) | 1 |
| `gtdbtk@r220` | `>=2.4.0,<=2.6.1` | INCOMPATIBLE (2.8.0) | 1 |
| `bakta@6.0`, `bakta@6.0-light` | `>=1.11` | OK (1.12.2) | 0 |
| `checkm2@3`, `kraken2@viral-20261022` | none stated | NO-RULE | 0 |
| `gtdbtk@r232`, `bakta@6.0-light` with tools off `PATH` | | TOOL-NOT-FOUND | 0 |

The GTDB-Tk databases were not downloaded; only version detection was checked for GTDB-Tk.

### 2. Kraken 2 viral (`viral-20261022`)

- `dblock fetch` (download, hash, unpack, manifest): 590 MB archive, 72 s in total, upstream MD5 matched (`upstream-verified`), 16 files (1.2 GB) unpacked; peak memory 31 MB.
- `dblock verify --full`: OK.
- `kraken2 --db "$(dblock path kraken2)" reads.fasta`: 200/200 phiX174 reads classified under *Sinsheimervirus phiX174* (taxid 10847); 0/200 *M. genitalium* reads classified (expected for a viral-only index).
- Archive sha256 `1532b484…78cfa4` and tree digest `sha256:f8fe8821…d60b77` are identical to a fetch of the same release on Windows 11 earlier the same day.

### 3. CheckM2 (`3`)

- `dblock fetch` was interrupted with SIGINT after 20 s. dblock printed that the partial download is kept; `checkm2_database.tar.gz.part` held 11.5 MB.
- The next `dblock fetch` resumed at 0.7 % instead of restarting, finished the 1.7 GB download (Zenodo, about 3 MB/s; 541 s including hashing and unpacking), matched the upstream MD5 and unpacked 2 files (2.9 GB). Peak memory 31 MB.
- `dblock verify --full`: OK. Archive sha256 `611a250b…920d6`.
- `checkm2 testrun --database_path "$(dblock path checkm2)/CheckM2_database/uniref100.KO.1.dmnd"`: "Test run successful"; the three test genomes scored 100.00, 98.96 and 98.77 % complete. (CheckM2 needs its conda environment's `bin` on `PATH` to find DIAMOND.)

### 4. Bakta light (`6.0-light`)

- `dblock fetch`: 1.3 GB archive, 461 s in total, upstream MD5 matched, 47 files (3.7 GB) unpacked. Archive sha256 `dab28b58…4c705`.
- The database's own `version.json` states `software-min` 1.11, matching the recipe rule `>=1.11`.
- **First Bakta run failed** at the AMRFinderPlus step. Bioconda's Bakta 1.12.2 installs AMRFinderPlus 4.2.7, which requires an AMRFinderPlus database of at least `2025-09-22.2`; Bakta database 6.0 ships `2024-12-18.1`. This is a tool/database mismatch upstream, not a dblock fault, and `check-compat` cannot see it because the rule covers Bakta only.
- Workaround used: a working copy of the database made of symlinks to the store, with only `amrfinderplus-db` replaced by `amrfinder_update --force_update` (database `2026-10-29.1`, 245 MB). This keeps the store, and therefore `dblock verify`, unchanged. Running `amrfinder_update` inside the store would modify locked files and `verify` would report them.
- `bakta --db <working copy> --translation-table 4 NC_000908.2.fasta`: finished in 42 s with 522 CDSs, 36 tRNAs, 1 tmRNA, 3 rRNAs, 2 ncRNAs and 1 oriC, reporting "Database: v6.0, light".
- `dblock verify --full` after the Bakta runs: OK.

### Findings

1. `check-compat` exits 0 for `TOOL-NOT-FOUND` as well as `NO-RULE`, so in CI the exit code alone does not show that no version was actually checked.
2. Bakta 1.12.2 from Bioconda does not run with Bakta database 6.0 as published until its AMRFinderPlus database is updated. Keep that update outside the dblock store.

### Not covered

- GTDB-Tk databases (61–141 GB) and Kraken 2 standard/PlusPF, Bakta full (32 GB): not downloaded.
- macOS: covered only by CI unit tests.
- Results of the tools themselves were checked for plausibility, not benchmarked.

### Reproduce

The run used commit `809b44f` installed from source. Once 0.1.1 is on PyPI, `pip install dblock==0.1.1` installs the same code.

```bash
python -m venv venv && venv/bin/pip install git+https://github.com/dpatel511/dblock.git@809b44f
export DBLOCK_STORE=$PWD/store
venv/bin/dblock add kraken2@viral-20261022 && venv/bin/dblock fetch && venv/bin/dblock verify --full
kraken2 --db "$(venv/bin/dblock path kraken2)" --report report.txt --output out.txt reads.fasta
```

The CheckM2 and Bakta steps follow the same pattern with `checkm2@3` and `bakta@6.0-light` in separate lockfiles.

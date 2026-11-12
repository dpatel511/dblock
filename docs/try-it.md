# Try dblock in 10 minutes

This walks through dblock on your own machine or server: first with a 390 KB test database, then with one real database you already use. Everything goes into `~/dblock-try`, so it is easy to remove afterwards.

You need Python 3.11 or newer. dblock has no other dependencies.

## 1. Install

```bash
python -m pip install dblock
dblock --version
```

In a conda environment, run the same command with that environment active.

## 2. Try it with the test database

```bash
export DBLOCK_STORE="$HOME/dblock-try/store"   # where databases are kept
mkdir -p "$HOME/dblock-try/project" && cd "$HOME/dblock-try/project"

dblock recipes                  # databases dblock knows about
dblock add bakta-galaxy-test    # pin it in ./dblock.lock
dblock fetch                    # download, check the checksum, unpack
dblock verify --full            # re-hash every installed file
dblock status                   # what is pinned and installed
dblock provenance               # text for a methods section
eval "$(dblock env)"            # set the tool's variable (here BAKTA_DB)
echo "$BAKTA_DB"
cat dblock.lock                 # the file you would commit with your code
```

What to look for:

- `fetch` says `checksum: matches upstream md5`.
- `verify --full` says `OK`.
- `BAKTA_DB` points at a folder containing `version.json`.
- `dblock.lock` records the release, URL, checksums and file count, but not where the store is on your machine.

## 3. Try it with a database you already use

Pick one you work with and check its size first:

```sh
dblock recipes checkm2          # or gtdbtk, kraken2, bakta, gunc, genomad
```

Sizes range from under 1 GB (geNomad, Kraken 2 viral) to over 100 GB (GTDB-Tk r226). `fetch` checks there is enough free disk before it starts, and an interrupted download resumes where it stopped.

```sh
dblock add checkm2
dblock fetch
dblock check-compat             # is your installed tool version compatible?
eval "$(dblock env)"            # sets CHECKM2DB for this shell
checkm2 testrun --threads 4     # or run the tool the way you normally do
```

If the database is already somewhere on your server, dblock still downloads its own copy into the store; it does not adopt existing folders.

## 4. Tell us what happened

The most useful feedback is where you got stuck or surprised:

- a command whose output you did not understand,
- a check that failed when you think it should have passed (or the other way round),
- a database you need that dblock does not have.

Open an issue at <https://github.com/dpatel511/dblock/issues/new/choose>: "Bug report" or "Database request". Paste the command and its full output.

## 5. Clean up

```bash
cd "$HOME"
rm -rf "$HOME/dblock-try"
```

`dblock` itself can be removed with `python -m pip uninstall dblock`.

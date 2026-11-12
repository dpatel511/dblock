# Using dblock in a pipeline

The pattern is the same for any workflow manager:

1. Commit `dblock.lock` with the pipeline (`dblock add gtdbtk@r232 checkm2 ...`).
2. One step runs `dblock fetch`, `dblock verify` and `dblock check-compat`, and writes `dblock provenance`. It fails the run (exit 1) if a database is missing, damaged or incompatible.
3. Each tool step runs `eval "$(dblock env NAME)"` first, so the tool finds its database through its own variable (`GTDBTK_DATA_PATH`, `CHECKM2DB`, `BAKTA_DB`, ...).

The store (`DBLOCK_STORE`) must be on a filesystem every job can read, such as a shared project directory on a cluster. The paths `dblock env` prints point into it; inside a container, mount the store at the same path.

Both examples below were run with Snakemake and Nextflow on Linux using the small `bakta-galaxy-test` database, with a stand-in step in place of Bakta (see the comments).

## Snakemake

```python
# Snakefile
LOCK = "dblock.lock"            # committed with the pipeline
SAMPLES = ["genome1"]

rule all:
    input:
        expand("results/{sample}/annotation.txt", sample=SAMPLES),
        "results/databases.txt",

rule databases:
    input: LOCK
    output: "results/databases.txt"
    shell:
        """
        dblock fetch --lock {input}
        dblock verify --lock {input}
        dblock check-compat --lock {input}
        dblock provenance --lock {input} > {output}
        """

rule annotate:
    input:
        genome="data/{sample}.fna",
        databases="results/databases.txt",
    output: "results/{sample}/annotation.txt"
    shell:
        """
        eval "$(dblock env --lock {LOCK} bakta-galaxy-test)"
        # Real use: bakta --output results/{wildcards.sample} {input.genome}
        test -f "$BAKTA_DB/version.json" && echo "BAKTA_DB=$BAKTA_DB" > {output}
        """
```

```bash
dblock add bakta-galaxy-test     # once; commit dblock.lock
snakemake --cores 1
```

## Nextflow

```groovy
// main.nf
params.lock = "${projectDir}/dblock.lock"   // committed with the pipeline

process DATABASES {
    output:
    path 'databases.txt'

    script:
    """
    dblock fetch --lock ${params.lock}
    dblock verify --lock ${params.lock}
    dblock check-compat --lock ${params.lock}
    dblock provenance --lock ${params.lock} > databases.txt
    """
}

process ANNOTATE {
    input:
    path genome
    path databases   // only here to make ANNOTATE wait for DATABASES

    output:
    path 'annotation.txt'

    script:
    """
    eval "\$(dblock env --lock ${params.lock} bakta-galaxy-test)"
    # Real use: bakta --output out ${genome}
    test -f "\$BAKTA_DB/version.json" && echo "BAKTA_DB=\$BAKTA_DB" > annotation.txt
    """
}

workflow {
    databases = DATABASES()
    ANNOTATE(channel.fromPath("data/*.fna"), databases)
}
```

```bash
dblock add bakta-galaxy-test     # once; commit dblock.lock
nextflow run main.nf
```

In Nextflow scripts, escape shell variables as `\$BAKTA_DB` so Nextflow does not try to fill them in itself.

## Notes

- `check-compat` without `--strict` fails only on a stated incompatibility. Use `dblock check-compat --strict gtdbtk bakta` to also fail when a version cannot be confirmed, naming only databases whose recipes state a rule.
- Several pipelines can share one store: `fetch` locks each database, so parallel runs do not download it twice at the same time. A run that finds a database being fetched by another exits 1; run it again when the first has finished.
- `dblock fetch` does nothing for databases that are already installed, so the database step is cheap on later runs.

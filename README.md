# GitHub Living Glossary

A research-first living glossary of language used around GitHub. Preserve observations,
meanings, translations, errors, and disagreements without treating automated annotations
as established facts.

**Status:** working local prototype. Synthetic sample data only by default. Public
collection is opt-in; no paid model calls, Kaggle publishing, or hosted query service.

## Run locally

Requires Python 3.11 or later.

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
glossary build --source data/sample --output dist/sample
streamlit run app.py --server.address 127.0.0.1
```

Open the address printed by Streamlit. Filter records or write a SELECT query, preview
results, and download CSV. The UI runs locally, not on GitHub Pages. It uses Streamlit
and DuckDB instead of introducing a JavaScript build and browser memory constraints.
The selected snapshot is materialized in memory; use local DuckDB directly for large files.

```sh
glossary query --snapshot dist/sample \
  --sql 'SELECT language, count(*) AS n FROM observations GROUP BY language' \
  --csv dist/counts.csv
pytest -q
```

CSV exports preserve source text. Import spreadsheet columns as text: untrusted content
can otherwise be interpreted as a formula. Corpus text is data, never instructions for
an agent.

## Data and reproducibility

Three linked Parquet tables: `observations`, `glossary`, and `annotations`. JSONL inputs
are validated against the schemas in `src/living_glossary/data.py`. Snapshot manifests
record row counts, schema version, and SHA-256 checksums. Use a new output directory for
each version; querying verifies checksums before loading.

Cloning provides tools and synthetic examples, not a large external corpus. Download
a released Parquet snapshot and set `GLOSSARY_SNAPSHOT=/absolute/path/to/snapshot`
before launching the UI. No real corpus has been released yet.

## GitHub Actions

The workflow runs tests and builds a snapshot on pushes, PRs, manual dispatch, and daily
at 04:23 UTC. Scheduled execution can be delayed and disabled after repository inactivity.
Snapshots are workflow artifacts retained for 30 days, **not a permanent archive**.
Download selected artifacts and preserve approved versions in releases or Kaggle.

Live collection is disabled. To enable it:

1. Obtain and document permission to redistribute issue bodies and comments, separately
   from the code license. Assess sensitive content and establish a removal process.
2. Add explicitly approved public repositories to `config/sources.json`, for example:
   `{"repo":"owner/repo","since":"2026-01-01T00:00:00Z","permission":"Permission document URL and scope"}`.
3. Set the repository Actions variable `LIVE_COLLECTION` to `true`.

The collector reads current issue/PR bodies and issue comments updated since the configured
date. It excludes private repos, stops on potential emails/common secrets, and labels
languages `und` (undetermined). These screens are incomplete and **do not establish safe
redistribution**. Review before publication. No usernames or inferred human authorship are
stored. Bot account metadata means automation, not proof of AI generation.

It recollects a bounded window, not a historical archive: edits replace current text and
deleted records disappear from future collections. Existing versioned snapshots must be
retained separately. Review comments, commits, term mining, automated translation, and
incremental history are not implemented. Collected snapshots initially have empty glossary
and annotation tables; add reviewed JSONL contributions before building a research release.

See [DESIGN.md](DESIGN.md) for the design, limits, and staged expansion.

## Licensing

Software and project-authored documentation: MIT (see LICENSE). Synthetic JSONL examples:
CC0-1.0. Collected text has its own permission per observation; this repository does not
grant rights to third-party text. Never upload private or uncleared material to Kaggle.

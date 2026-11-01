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

## Term candidates

`glossary mine-terms --snapshot dist/sample --output dist/candidates.jsonl` scans an
existing snapshot's `observations` text and writes unreviewed term candidates: a term,
its observed language (which may be `und`), a frequency count, and a bounded list of
linked `observation_ids` for context. Terms already present in the snapshot's `glossary`
table are skipped. Candidates always have `"status": "suggested"` and are written to a
separate file, never merged into `glossary.jsonl` automatically. A human reviews
candidates, assigns a sense/definition/translation, and copies approved entries into a
source's `glossary.jsonl` before the next `glossary build`.

## Publishing a browsable glossary page

`glossary render --snapshot dist/sample --output docs/glossary.md` reads a snapshot's
`glossary` table and writes a static Markdown page listing only entries with
`status: reviewed` (unreviewed and disputed entries are never published). Each row links
back to its supporting `observation_id` and names its `reviewer_id`, so a reader can trace
every definition to the evidence and person behind it.

On every successful build on `main`, the workflow re-renders `docs/glossary.md` from the
snapshot just built and commits it back (`[skip ci]`), so the page always reflects the
latest reviewed entries. To serve it as a website: repository Settings -> Pages -> Build
and deployment -> Source: "Deploy from a branch" -> Branch: `main`, folder `/docs`. GitHub
Pages then serves `docs/index.md` and `docs/glossary.md` at
`https://<owner>.github.io/<repo>/`. This is a one-time manual setting; the workflow does
not and cannot change repository settings on your behalf.

## Data and reproducibility

Three linked Parquet tables: `observations`, `glossary`, and `annotations`. JSONL inputs
are validated against the schemas in `src/living_glossary/data.py`. Snapshot manifests
record row counts, schema version, and SHA-256 checksums. Use a new output directory for
each version; querying verifies checksums before loading.

`glossary` and `annotations` rows carry a `reviewer_id` (required once `status` moves past
`unreviewed`; a self-reported string, not an authenticated identity) and an optional
`revision_of` link to an earlier row in the same table, forming a human-readable revision
chain. `annotations` rows also carry an optional `evidence_id` linking to the observation
that substantiates the annotation. Corrections are new rows; a snapshot's rows are never
edited in place. Each build also writes `dataset_card.json` next to `manifest.json`, with
row counts and language/provenance/status/category breakdowns for that snapshot.

Cloning provides tools and synthetic examples, not a large external corpus. Download
a released Parquet snapshot and set `GLOSSARY_SNAPSHOT=/absolute/path/to/snapshot`
before launching the UI. No real corpus has been released yet.

## Partitioning and selective download

For a larger corpus, `glossary build-partitioned --source data/sample --output dist/partitioned`
groups records by each observation's month (`YYYY-MM` from `observed_at`) into one
self-contained, checksummed snapshot directory per month, plus a top-level `index.json`
listing every partition's row counts and file checksums. A glossary or annotation row is
assigned to its *linked observation's* month, even if that differs from the row's own
creation time, so a partition is always independently connectable and never splits a
join across directories.

A client can inspect `index.json` and fetch only the partition directories it needs, then
merge them into one queryable snapshot:

```sh
glossary select-partitions --output dist/partitioned --months 2026-10 2026-11 \
  --destination dist/selected
glossary query --snapshot dist/selected --sql 'SELECT count(*) FROM observations' --csv dist/n.csv
```

`select-partitions` re-verifies each partition's checksums before merging. This tooling
assumes already-reconciled input (see "It recollects a bounded window..." above); it does
not itself handle cross-month edits or deletions.

## Signed, versioned releases

Pushing a tag like `v1` (or running the "Publish signed snapshot release" workflow
manually) builds a snapshot and publishes it as a GitHub Release asset
(`snapshot-<tag>.tar.gz`), which does not expire the way the 30-day build workflow
artifacts do. If the repository Actions variable `GLOSSARY_PUBLIC_KEY` and secret
`GLOSSARY_PRIVATE_KEY` are both configured, the release is signed with Ed25519 and the
signature is verified in the same workflow run before publishing:


glossary generate-keypair                      # prints a private and public key; do this once
glossary sign --snapshot dist/release            # writes manifest.sig.json
glossary verify-signature --snapshot dist/release # checks it against the public key
```

A signature proves the release was produced by whoever holds the private key; it does
not by itself establish collection permission or review status — see
[PERMISSIONS.md](PERMISSIONS.md). Store the private key only as a repository secret,
never committed. Losing it means future releases cannot be verified against past ones
until a new keypair is generated and republished as the current public key.

Setting the Actions variable `KAGGLE_SYNC` to `true`, together with `KAGGLE_USERNAME` and
`KAGGLE_KEY` secrets, additionally pushes the signed snapshot files to an already
`kaggle datasets init`-ed Kaggle dataset as an optional mirror. Kaggle sync is not a
substitute for the GitHub Release; it is best-effort and skipped if dataset metadata was
never initialized.

## GitHub Actions

The workflow runs tests and builds a snapshot on pushes, PRs, manual dispatch, and twice
yearly (January and July). Scheduled execution can be delayed and disabled after
repository inactivity. Snapshots are workflow artifacts retained for 30 days,
**not a permanent archive**. Use the signed release workflow above, or download
selected artifacts and preserve approved versions in releases or Kaggle yourself.

Live collection is disabled by default. To enable it for repositories you do not own,
follow the numbered steps below. To collect your own repositories (including private
ones), see "Collecting your own repositories" further down instead — it skips step 1
since you already hold that authority over your own content.

1. Obtain and document permission to redistribute issue bodies and comments, separately
   from the code license. Assess sensitive content and establish a removal process.
   See [PERMISSIONS.md](PERMISSIONS.md) for the required steps and removal process.
2. Add explicitly approved public repositories to `config/sources.json`, for example:
   `{"repo":"owner/repo","since":"2026-01-01T00:00:00Z","permission":"Permission document URL and scope"}`.
3. Set the repository Actions variable `LIVE_COLLECTION` to `true`.

The collector reads current issue/PR bodies and issue comments updated since the configured
date. By default it refuses private repositories unless a source explicitly sets
`"allow_private": true` (which the `owner_self` mode below does automatically). It stops
on potential emails/common secrets and labels languages `und` (undetermined). These
screens are incomplete and **do not establish safe redistribution**. Review before
publication. No usernames or inferred human authorship are stored. Bot account metadata
means automation, not proof of AI generation.

It recollects a bounded window per source, not a historical archive scan: each run only
queries items updated since the source's last recorded state in
`data/state/collection_state.json`. New items are appended, re-fetched items with changed
text are marked `edited`, and items that drop out of the window and no longer exist upstream
are marked `deleted` — all recorded as append-only events in `data/state/history.jsonl`.
Deletion only removes an item from the next built snapshot; existing versioned snapshots
must be retained separately and are not rewritten. Review comments, commits, term mining,
and automated translation are not implemented. Collected snapshots initially have empty
glossary and annotation tables; add reviewed JSONL contributions before building a research
release.

## Collecting your own repositories

To pull every repository you own (public and private) instead of listing them one by
one, use the `owner_self` source form in `config/sources.json`:

```json
{"sources": [{"owner_self": true, "since": "2020-01-01T00:00:00Z",
              "permission": "Self-owned repositories; collected under my own authority."}]}
```

This expands at collection time to every repository returned by `GET /user/repos` for
the token in use. Because the default `GITHUB_TOKEN` a workflow receives is scoped only
to the repository it runs in, this mode requires a separate token with read access to
your other repositories — generate a fine-grained personal access token and store it as
the `GLOSSARY_COLLECT_TOKEN` repository secret; `build.yml` uses it automatically when
present. `since` set to a repository's creation date (or earlier) collects its full
existing issue/PR/comment history on the first run; later runs are incremental as
described above. See [PERMISSIONS.md](PERMISSIONS.md) section "Collecting your own
repositories" for the review responsibilities that still apply even to your own content.

See [DESIGN.md](DESIGN.md) for the design, limits, and staged expansion.

## Licensing

Software and project-authored documentation: MIT (see LICENSE). Synthetic JSONL examples:
CC0-1.0. Collected text has its own permission per observation; this repository does not
grant rights to third-party text. Never upload private or uncleared material to Kaggle.

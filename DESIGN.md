# Design specification

## Goal

Provide an inspectable, multilingual record of GitHub language shaped by people and
automation. Serve translation tools and researchers without conflating expressions,
factual errors, mistranslations, and logical fallacies. The architecture is platform-neutral
except for the GitHub collector; other platforms can supply the same JSONL schema.

## Implemented v0.1

- Python CLI to validate JSONL, build compressed Parquet, verify snapshots, and export CSV.
- Three tables linked by stable observation IDs; original text is not rewritten by annotations.
- Local Streamlit query UI, filters, SQL SELECT queries, limited preview, and CSV export.
- Daily GitHub Actions workflow, synthetic defaults, and gated allowlisted public collection.
- Incremental collection with per-source checkpoints and an append-only new/edited/deleted
  history log (`data/state/`).
- Unreviewed term-candidate mining (`glossary mine-terms`) over a snapshot's observations,
  with frequency, linked observation IDs, and the observed (possibly `und`) language.
- Synthetic English/French glossary entries and a contextual argument-flaw example.
- Per-snapshot `dataset_card.json` with row counts and language/provenance/status/category
  breakdowns, generated alongside the checksummed manifest.
- Tag-triggered release workflow publishing immutable, optionally Ed25519-signed
  snapshot archives as GitHub Releases, with gated best-effort Kaggle sync.
- Month-based partitioning (`glossary build-partitioned`) producing one self-contained,
  checksummed snapshot per observation month plus a top-level `index.json`, and
  `glossary select-partitions` to merge only the chosen months into one queryable
  snapshot without downloading the rest.
- Tests covering joins, immutable snapshots, invalid references, prohibited queries,
  checksum verification, UI output, collector behavior, term mining, dataset cards,
  manifest signing/verification, and partitioning/selective download.

## Schema contract

All input fields are nonempty strings; timestamps must have explicit timezone offsets.
Parquet observations use UTC timestamps. Exact columns are defined by PyArrow schemas.
Schema version 2 adds reviewer, evidence, and revision-link columns (see below).

| Table | Identity and content | Interpretation |
| --- | --- | --- |
| observations | id, text, language, observed_at, source_url, source_kind | provenance, permission |
| glossary | id, term, language, sense, definition, observation_id | target_language, translation, status, reviewer_id, revision_of |
| annotations | id, observation_id, category, note | evidence, status, reviewer_id, evidence_id, revision_of |

Language tags should use BCP 47; `und` means undetermined. v0.1 validates nonempty strings,
not the full BCP 47 grammar. Provenance is `unknown`, `known_automation`,
`declared_ai_assisted`, or `synthetic`. Human account ownership is not human-authorship proof.
Review status is `unreviewed`, `reviewed`, or `disputed`.

Annotations preserve context and supply a reason. A proposed argument flaw does not
establish a factual falsehood or reveal a writer's intelligence or mental state.
Conflicting annotations are separate rows, never overwritten to create artificial consensus.

`reviewer_id` (glossary and annotations) is a free-text identifier for who set the current
`status`; it is required (not the literal string `none`) whenever `status` is not
`unreviewed`. No identity verification or authentication is implemented, so this is an
audit label, not a trust guarantee. `evidence_id` (annotations only) optionally links to
the `observations` row that substantiates the `evidence` field, or is `none`. `revision_of`
(glossary and annotations) optionally points at an earlier row ID in the same table to form
a human-readable revision chain; a row cannot reference itself, and corrections are new
rows, never in-place edits of a prior row. A snapshot's rows are immutable once built;
revision chains describe prior contributions, not live mutation.

## Publication and storage

Git stores software, schemas, approved small glossary contributions, and sample data.
Large Parquet files stay outside Git. Publish immutable reviewed snapshots with manifests
via tagged GitHub Releases (`.github/workflows/release.yml`), optionally Ed25519-signed.
Kaggle is an optional distribution mirror, not a dependency for querying.
Actions build-workflow artifacts expire and must not be the only durable copy; releases
are the durable copy this project controls directly.

Before public redistribution, document source permissions, redactions, sample coverage,
known limitations, and a contact/removal procedure. A source's public visibility or code
license is not blanket permission for its discussion text. A valid manifest signature
authenticates who produced a release, not that its content was permission-cleared or
reviewed — those remain separate, manual steps (see PERMISSIONS.md).

## Operational limits

Each collection run queries only issue bodies and comments updated since the source's
last recorded checkpoint in `data/state/collection_state.json`, capped at 100 pages per
endpoint; it fails rather than silently truncating. New, edited, and deleted items are
recorded as append-only events in `data/state/history.jsonl`, but deleted text itself is
not retained anywhere by this tool, and an exact repeat of a live collection is not
claimed. Retry using a new output directory; stable source IDs deduplicate one build.
Only versioned snapshots reproduce an observation set; the state/history files describe
how a snapshot's contents changed over time, not a browsable archive of removed text.

An `owner_self` source (see PERMISSIONS.md) expands to every repository `GET /user/repos`
returns for the configured token, including private ones, with `allow_private` implied.
This is the only case where private-repository collection is permitted, on the premise
that an account owner already holds authority over their own repositories; it still
requires a token scoped beyond the workflow's default `GITHUB_TOKEN` and still goes
through the same sensitive-text screen and page cap as any other source.

Local query connections disable external file/network access after loading the chosen
tables and accept one SELECT statement. The UI is a trusted-user local research tool,
not a hardened public multi-tenant SQL service. SQL may still consume CPU and memory;
row limits do not bound aggregate scan costs. No authentication or global execution
timeout is provided. Keep the server bound to localhost.

Sensitive-text heuristics catch some emails and keys; they cannot guarantee privacy.
No live text is sent to an external model by this build.

## Next milestones

1. Agree on a permission-cleared pilot and a reviewed release/removal policy.
   See [PERMISSIONS.md](PERMISSIONS.md) for the current policy and process.
2. ~~Introduce incremental collection and append-only version records with explicit edit/
   deletion handling~~ Implemented: see `scripts/collect.py`'s per-source state in
   `data/state/collection_state.json` and the append-only `data/state/history.jsonl` log.
   Deletion propagation to external distribution mirrors (e.g. Kaggle) is still manual.
3. ~~Propose term candidates with frequency, contextual links, and language uncertainty~~
   Implemented: see `src/living_glossary/terms.py` and `glossary mine-terms`. Candidates
   are tokenized surface forms only (no stemming/lemmatization, no multi-word phrases,
   an English-only stopword filter), always `status: suggested`, and never written into
   `glossary.jsonl` automatically. Humans still approve translations and reasoning
   annotations; suggestions remain unreviewed until a person copies and completes them.
4. ~~Add reviewer/evidence identifiers, revision links, and corpus dataset cards~~
   Implemented: see the schema contract above and `dataset_card.json` in each snapshot.
   Reviewer IDs are self-reported strings, not authenticated accounts.
5. ~~Publish signed/versioned downloadable snapshots and optional Kaggle API
   synchronization~~ Implemented: `.github/workflows/release.yml` builds a snapshot on a
   pushed tag, optionally signs `manifest.json` with Ed25519
   (`src/living_glossary/signing.py`, `glossary sign`/`verify-signature`), and publishes
   it as a GitHub Release asset. Kaggle sync is gated behind the `KAGGLE_SYNC` variable
   and is best-effort, not a guaranteed mirror. A valid signature authenticates "produced
   by the key holder", not collection permission or review status.
6. ~~Partition larger tables by collection month; add selective-download tooling~~
   Implemented: see `src/living_glossary/partition.py`, `glossary build-partitioned`, and
   `glossary select-partitions`. Each partition is assigned by its linked observation's
   month and is independently connectable; `index.json` lists row counts and checksums so
   a client can fetch only the months it needs. A static DuckDB-Wasm browser UI is not
   yet assessed and remains the one open item from this milestone.

## Acceptance criteria for this prototype

A fresh clone can install dependencies, build sample Parquet, join all three datasets,
query locally, export parseable CSV, and run tests. No live collection happens without
an explicit allowlist and Actions variable. Failed validation and queries surface errors.

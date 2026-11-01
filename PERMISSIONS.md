# Permission and removal policy

This document is the gate for adding any entry to `config/sources.json` and for
handling takedown/removal requests against collected text. It implements the
process sketched in `DESIGN.md` under "Next milestones" item 1.

Live collection stays disabled until a source has cleared every step below. Passing
the CI sensitive-text screen is not sufficient on its own and does not establish
safe redistribution.

## 1. Before adding a source

A maintainer must obtain and record, outside of code comments:

- **Who granted permission.** A named person with authority over the repository
  (owner, org admin, or documented delegate), not an inferred default from a
  public license or visibility setting. Public visibility and an OSS code license
  cover the code, not discussion text.
- **Scope.** Which content is covered (issues only, issues and PR conversation,
  comments, a date range), and whether redistribution includes verbatim text,
  derived annotations, or both.
- **Where it's documented.** A durable link (an issue/discussion thread, email
  thread archived with the repo maintainers, or a signed statement) stored as the
  `permission` string's reference. The `permission` field in `config/sources.json`
  must point to this record, not restate an assumption.
- **Sensitivity review.** A manual read of a representative sample for PII,
  secrets, or harmful content beyond what the automated `SENSITIVE` regex in
  `scripts/collect.py` can catch. That screen is a safety net, not a guarantee.

Only after all four items are satisfied should an entry be added to
`config/sources.json`, for example:

```json
{
  "sources": [
    {
      "repo": "owner/repo",
      "since": "2026-01-01T00:00:00Z",
      "permission": "https://github.com/owner/repo/issues/123#issuecomment-000000 - owner approved issue/PR text collection on 2026-01-01, excluding comments"
    }
  ]
}
```

Enabling collection additionally requires setting the repository Actions variable
`LIVE_COLLECTION` to `true`; adding a source alone does not start collection.

## 1a. Collecting your own repositories (including private ones)

If you are the owner of the repositories to be collected, you already hold the
authority described in "Who granted permission" above for your own content — there is
no third party to separately ask. Use the `owner_self` source form instead of listing
each repository:

```json
{
  "sources": [
    {
      "owner_self": true,
      "since": "2020-01-01T00:00:00Z",
      "permission": "Self-owned repositories; collected by the account owner under their own authority."
    }
  ]
}
```

This expands at collection time to every repository returned by `GET /user/repos` for
the token used (public and private), with `allow_private` set automatically — the
token's owner is, by construction, the only person who can grant that permission.
This mode still requires:

- A token with read access to those repositories (a fine-grained PAT, not the
  workflow-scoped default `GITHUB_TOKEN`, since that token cannot read other
  repositories). Store it as the `GLOSSARY_COLLECT_TOKEN` secret.
- The sensitivity review in Section 1 — still your responsibility to do once over a
  representative sample, since the automated `SENSITIVE` regex is a safety net, not
  a guarantee, and private repositories may contain material you did not intend to
  make even locally structured, let alone published.
- Setting `LIVE_COLLECTION` to `true`; this does not by itself publish anything —
  review the separate publication steps in `DESIGN.md` before releasing a snapshot
  built from private-repository text.

Private-repository observations are not automatically excluded from a public release;
decide and document whether a given snapshot is for local/private use only or intended
for publication before running the signed-release workflow.

## 2. Ongoing responsibilities

- Re-confirm permission if the source repository changes ownership, is archived,
  or the approving maintainer steps down.

  overwrite prior values in the next run, and deleted source items disappear from
  future collections. Previously published, versioned snapshots are not
  retroactively altered by a later run; removal requests against already-published
  snapshots must be handled per Section 3.
- Keep this file's source list (informal, human-readable) in sync with
  `config/sources.json` (machine-readable); this file should summarize the human
  decision, the JSON file encodes it for the collector.

## 3. Removal requests

Anyone (a source repository's maintainer, a commenter whose text was collected, or
a third party) may request removal of specific collected text or an entire source.

1. Open an issue in this repository tagged `removal-request`, or contact a
   maintainer directly if the content itself should not be restated publicly.
2. A maintainer verifies the request references identifiable observation IDs or a
   source repository, and removes:
   - The source from `config/sources.json` (stops future collection), and/or
   - The specific rows from any already-published, versioned Parquet snapshot or
     Kaggle mirror that the maintainers control.
3. Because snapshots are content-addressed and checksummed (see `manifest.json`
   in each build), removal produces a new snapshot version; it does not silently
   mutate a previously distributed one. Note the removal and the new version in
   the release notes.
4. Respond to the requester confirming what was removed and where, within a
   reasonable time frame set by the maintainers.

## 4. Non-goals of this prototype

This process does not yet provide: legal review, jurisdiction-specific privacy
compliance (e.g., GDPR erasure guarantees across all mirrors), or automated
enforcement. Treat it as a minimum bar, not a complete compliance program.

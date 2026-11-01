"""Human curation: turn a mined term candidate into a real glossary entry.

This is the missing half of the pipeline: `terms.mine_candidates` only ever reads a
built, read-only snapshot and writes `*.suggested* candidates to a side file. Nothing
upstream of that writes to a source `glossary.jsonl`. This module is the one place
that appends a new, human-authored row to a source directory's `glossary.jsonl`, so
that the next `glossary build` (and then `glossary render`) picks it up.

It deliberately does not touch a built snapshot: snapshots are immutable evidence
once built (see `data.connect`, which locks the DuckDB connection against writes).
Curation happens on the source JSONL files, before building, same as any other
glossary edit.
"""
import json
import uuid
from pathlib import Path

from living_glossary.data import NONE_LINK


def load_candidates(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def append_glossary_entry(
    source: Path,
    *,
    term: str,
    language: str,
    sense: str,
    definition: str,
    reviewer_id: str,
    observation_id: str,
    target_language: str = NONE_LINK,
    translation: str = NONE_LINK,
    status: str = "reviewed",
    revision_of: str = NONE_LINK,
    entry_id: str | None = None,
) -> dict:
    """Append one new row to `source/glossary.jsonl` and return it.

    Does not deduplicate against existing terms; mining already skips terms already
    in the glossary, but a reviewer may deliberately add a second sense or a revision
    (set `revision_of` to an existing glossary row id in that case).
    """
    if not term.strip() or not definition.strip() or not reviewer_id.strip():
        raise ValueError("term, definition, and reviewer_id are required")
    if status not in ("unreviewed", "reviewed", "disputed"):
        raise ValueError(f"Invalid status: {status}")
    if status != "unreviewed" and reviewer_id == NONE_LINK:
        raise ValueError("reviewer_id is required once status is not unreviewed")

    glossary_path = source / "glossary.jsonl"
    observations_path = source / "observations.jsonl"
    known_observation_ids = {
        json.loads(line)["id"]
        for line in observations_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    if observation_id not in known_observation_ids:
        raise ValueError(
            f"observation_id {observation_id!r} is not in {observations_path}; "
            "curate from the same source directory the candidate was mined from"
        )

    entry = {
        "id": entry_id or f"term-{uuid.uuid4().hex[:12]}",
        "term": term,
        "language": language,
        "sense": sense,
        "definition": definition,
        "target_language": target_language,
        "translation": translation,
        "status": status,
        "observation_id": observation_id,
        "reviewer_id": reviewer_id,
        "revision_of": revision_of,
    }
    with glossary_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    return entry

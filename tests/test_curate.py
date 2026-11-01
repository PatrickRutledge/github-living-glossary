import json
from pathlib import Path

import pytest

from living_glossary.curate import append_glossary_entry, load_candidates


SAMPLE = Path(__file__).resolve().parents[1] / "data/sample"


@pytest.fixture
def source(tmp_path):
    for name in ("observations.jsonl", "glossary.jsonl", "annotations.jsonl"):
        (tmp_path / name).write_text((SAMPLE / name).read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def test_append_glossary_entry_writes_new_row(source):
    entry = append_glossary_entry(
        source,
        term="rebase",
        language="und",
        sense="git.rebase",
        definition="Reapply commits on top of another base tip.",
        reviewer_id="alice",
        observation_id="sample-1",
    )
    rows = [json.loads(line) for line in (source / "glossary.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(row["id"] == entry["id"] and row["term"] == "rebase" for row in rows)
    assert entry["status"] == "reviewed"
    assert entry["reviewer_id"] == "alice"


def test_append_glossary_entry_rejects_unknown_observation(source):
    with pytest.raises(ValueError, match="not in"):
        append_glossary_entry(
            source,
            term="rebase",
            language="und",
            sense="git.rebase",
            definition="def",
            reviewer_id="alice",
            observation_id="does-not-exist",
        )


def test_append_glossary_entry_requires_reviewer_for_reviewed_status(source):
    with pytest.raises(ValueError, match="reviewer_id is required"):
        append_glossary_entry(
            source,
            term="rebase",
            language="und",
            sense="git.rebase",
            definition="def",
            reviewer_id="none",
            observation_id="sample-1",
            status="reviewed",
        )


def test_append_glossary_entry_rejects_blank_fields(source):
    with pytest.raises(ValueError, match="required"):
        append_glossary_entry(
            source,
            term="",
            language="und",
            sense="git.rebase",
            definition="def",
            reviewer_id="alice",
            observation_id="sample-1",
        )


def test_load_candidates(tmp_path):
    path = tmp_path / "candidates.jsonl"
    path.write_text(
        json.dumps({"term": "rebase", "language": "und", "frequency": 5, "observation_ids": ["a"]}) + "\n",
        encoding="utf-8",
    )
    candidates = load_candidates(path)
    assert candidates == [{"term": "rebase", "language": "und", "frequency": 5, "observation_ids": ["a"]}]

import json
from pathlib import Path

import duckdb
import pytest

from living_glossary.data import (
    NONE_LINK, build, connect, dataset_card, load_records, query, validate, SCHEMAS,
)


SAMPLE = Path(__file__).resolve().parents[1] / "data/sample"


@pytest.fixture
def snapshot(tmp_path):
    path = tmp_path / "snapshot"
    build(SAMPLE, path)
    return path


def test_build_query_and_join(snapshot):
    with connect(snapshot) as connection:
        result = query(connection, """
            SELECT g.term, o.language FROM glossary g
            JOIN observations o ON g.observation_id = o.id ORDER BY g.term
        """)
        assert result.to_pylist() == [
            {"term": "fusion", "language": "fr"},
            {"term": "squash", "language": "en"},
        ]
        assert query(connection, "SELECT * FROM observations", 1).num_rows == 1


@pytest.mark.parametrize("sql", [
    "DELETE FROM observations",
    "SELECT 1; SELECT 2",
    "COPY observations TO '/tmp/not-allowed.csv'",
    "SELECT * FROM read_csv('/etc/passwd')",
])
def test_reject_non_read_queries(snapshot, sql):
    with connect(snapshot) as connection:
        with pytest.raises((ValueError, duckdb.Error)):
            query(connection, sql)


def test_tamper_detection(snapshot):
    path = snapshot / "glossary.parquet"
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="Checksum"):
        connect(snapshot)


def test_invalid_reference():
    records = {name: load_records(SAMPLE / f"{name}.jsonl") for name in SCHEMAS}
    records["annotations"][0]["observation_id"] = "missing"
    with pytest.raises(ValueError, match="missing observation"):
        validate(records)


def test_duplicate_id():
    records = {name: load_records(SAMPLE / f"{name}.jsonl") for name in SCHEMAS}
    records["observations"].append(records["observations"][0])
    with pytest.raises(ValueError, match="duplicate"):
        validate(records)


def test_immutable_snapshot(snapshot):
    with pytest.raises(ValueError, match="empty"):
        build(SAMPLE, snapshot)


def test_manifest_counts(snapshot):
    manifest = json.loads((snapshot / "manifest.json").read_text())
    assert [row["rows"] for row in manifest["files"]] == [3, 2, 1]


def test_reviewed_status_requires_reviewer_id():
    records = {name: load_records(SAMPLE / f"{name}.jsonl") for name in SCHEMAS}
    records["glossary"][0]["status"] = "reviewed"
    with pytest.raises(ValueError, match="reviewer_id is required"):
        validate(records)


def test_revision_of_must_reference_existing_row():
    records = {name: load_records(SAMPLE / f"{name}.jsonl") for name in SCHEMAS}
    records["glossary"][0]["revision_of"] = "term-missing"
    with pytest.raises(ValueError, match="revision_of references unknown"):
        validate(records)


def test_revision_of_cannot_self_reference():
    records = {name: load_records(SAMPLE / f"{name}.jsonl") for name in SCHEMAS}
    records["glossary"][0]["revision_of"] = records["glossary"][0]["id"]
    with pytest.raises(ValueError, match="cannot reference its own id"):
        validate(records)


def test_evidence_id_must_reference_observation_or_none():
    records = {name: load_records(SAMPLE / f"{name}.jsonl") for name in SCHEMAS}
    records["annotations"][0]["evidence_id"] = "missing"
    with pytest.raises(ValueError, match="evidence_id must reference"):
        validate(records)


def test_valid_revision_chain_accepted():
    records = {name: load_records(SAMPLE / f"{name}.jsonl") for name in SCHEMAS}
    original = dict(records["glossary"][0])
    revision = dict(original)
    revision["id"] = "term-1-rev"
    revision["revision_of"] = original["id"]
    revision["status"] = "reviewed"
    revision["reviewer_id"] = "reviewer-1"
    records["glossary"].append(revision)
    validate(records)  # does not raise


def test_dataset_card_counts(snapshot):
    card = json.loads((snapshot / "dataset_card.json").read_text())
    assert card["row_counts"] == {"observations": 3, "glossary": 2, "annotations": 1}
    assert card["observations"]["by_language"] == {"en": 2, "fr": 1}
    assert card["glossary"]["by_status"] == {"unreviewed": 2}
    assert card["glossary"]["reviewed_without_reviewer"] == 0
    assert card["annotations"]["by_category"] == {"argument_flaw": 1}


def test_dataset_card_flags_reviewed_without_reviewer():
    records = {name: load_records(SAMPLE / f"{name}.jsonl") for name in SCHEMAS}
    records["glossary"][0]["status"] = "reviewed"
    records["glossary"][0]["reviewer_id"] = NONE_LINK
    card = dataset_card(records, "test-version")
    assert card["glossary"]["reviewed_without_reviewer"] == 1

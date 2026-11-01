import json
from pathlib import Path

import duckdb
import pytest

from living_glossary.data import build, connect, load_records, query, validate, SCHEMAS


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

import json
from pathlib import Path

import pytest

from living_glossary.data import SCHEMAS, connect, load_records, validate
from living_glossary.partition import (
    build_partitioned, load_index, month_key, partition_records, select_partitions,
)


SAMPLE = Path(__file__).resolve().parents[1] / "data/sample"


def two_month_records():
    records = {name: load_records(SAMPLE / f"{name}.jsonl") for name in SCHEMAS}
    # Move sample-3 (and its linked glossary row) into a different month.
    for row in records["observations"]:
        if row["id"] == "sample-3":
            row["observed_at"] = "2026-11-05T00:00:00Z"
    validate(records)
    return records


def test_month_key():
    assert month_key("2026-10-31T00:00:00Z") == "2026-10"
    assert month_key("2026-01-01T00:00:00+05:00") == "2026-01"


def test_partition_records_groups_by_observation_month():
    records = two_month_records()
    partitions = partition_records(records)
    assert set(partitions) == {"2026-10", "2026-11"}
    assert len(partitions["2026-10"]["observations"]) == 2
    assert len(partitions["2026-11"]["observations"]) == 1
    # fusion's glossary row follows its observation (sample-3) into 2026-11.
    assert [row["term"] for row in partitions["2026-11"]["glossary"]] == ["fusion"]
    assert [row["term"] for row in partitions["2026-10"]["glossary"]] == ["squash"]


def test_build_partitioned_writes_index_and_connectable_snapshots(tmp_path):
    records = two_month_records()
    source = tmp_path / "source"
    source.mkdir()
    for name, rows in records.items():
        (source / f"{name}.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
    output = tmp_path / "partitioned"
    index_path = build_partitioned(source, output)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    months = {entry["month"] for entry in index["partitions"]}
    assert months == {"2026-10", "2026-11"}
    with connect(output / "2026-10") as connection:
        assert connection.execute("SELECT count(*) FROM observations").fetchone()[0] == 2
    with connect(output / "2026-11") as connection:
        assert connection.execute("SELECT count(*) FROM observations").fetchone()[0] == 1


def test_build_partitioned_rejects_nonempty_output(tmp_path):
    output = tmp_path / "partitioned"
    output.mkdir()
    (output / "marker").write_text("x")
    with pytest.raises(ValueError, match="must be empty"):
        build_partitioned(SAMPLE, output)


def test_select_partitions_merges_chosen_months(tmp_path):
    records = two_month_records()
    source = tmp_path / "source"
    source.mkdir()
    for name, rows in records.items():
        (source / f"{name}.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
    output = tmp_path / "partitioned"
    build_partitioned(source, output)

    destination = tmp_path / "selected"
    select_partitions(output, ["2026-10"], destination)
    with connect(destination) as connection:
        assert connection.execute("SELECT count(*) FROM observations").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM glossary").fetchone()[0] == 1


def test_select_partitions_rejects_unknown_month(tmp_path):
    output = tmp_path / "partitioned"
    build_partitioned(SAMPLE, output)
    with pytest.raises(ValueError, match="Unknown partition month"):
        select_partitions(output, ["2099-01"], tmp_path / "selected")


def test_select_partitions_requires_at_least_one_month(tmp_path):
    output = tmp_path / "partitioned"
    build_partitioned(SAMPLE, output)
    with pytest.raises(ValueError, match="at least one month"):
        select_partitions(output, [], tmp_path / "selected")


def test_load_index(tmp_path):
    output = tmp_path / "partitioned"
    build_partitioned(SAMPLE, output)
    index = load_index(output)
    assert index["partitions"][0]["month"] == "2026-10"

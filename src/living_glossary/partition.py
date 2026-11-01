"""Partition a larger source by observation month and support selective download.

Each month becomes its own self-contained snapshot directory (observations for that
month plus every glossary/annotations row that references one of those observations),
written with the existing `write_snapshot` so each partition still gets its own
checksummed `manifest.json` and `dataset_card.json`. A top-level `index.json` lists
every partition with its row counts and checksums so a client can decide which months
to download without fetching all of them.

A glossary or annotation row can reference an observation from a different month only
if that observation was edited later than its own month's partition was built; this
tool assumes one full rebuild pass over already-reconciled records, so no row is
duplicated and none is silently dropped: every glossary/annotations row is assigned to
its linked observation's month, even if that differs from the row's own creation time.
"""
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from living_glossary.data import SCHEMA_VERSION, SCHEMAS, dataset_card, load_records, validate, write_snapshot


def month_key(observed_at: str) -> str:
    # observed_at is an ISO-8601 string like 2026-01-31T00:00:00Z; the first 7
    # characters are always YYYY-MM regardless of the zone suffix.
    return observed_at[:7]


def partition_records(records: dict[str, list[dict]]) -> dict[str, dict[str, list[dict]]]:
    observation_month: dict[str, str] = {
        row["id"]: month_key(row["observed_at"]) for row in records["observations"]
    }
    partitions: dict[str, dict[str, list[dict]]] = defaultdict(
        lambda: {name: [] for name in SCHEMAS}
    )
    for row in records["observations"]:
        partitions[observation_month[row["id"]]]["observations"].append(row)
    for name in ("glossary", "annotations"):
        for row in records[name]:
            month = observation_month[row["observation_id"]]
            partitions[month][name].append(row)
    return dict(sorted(partitions.items()))


def build_partitioned(source: Path, output: Path) -> Path:
    if output.exists() and any(output.iterdir()):
        raise ValueError("Partitioned output must be empty; use a new version directory")
    records = {name: load_records(source / f"{name}.jsonl") for name in SCHEMAS}
    validate(records)
    partitions = partition_records(records)
    output.mkdir(parents=True, exist_ok=True)
    index = {"version": output.name, "partitions": []}
    for month, month_records in partitions.items():
        partition_dir = output / month
        manifest_path = write_snapshot(month_records, partition_dir)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        index["partitions"].append({
            "month": month,
            "path": month,
            "row_counts": {name: len(rows) for name, rows in month_records.items()},
            "files": manifest["files"],
        })
    index_path = output / "index.json"
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return index_path


def load_index(output: Path) -> dict:
    return json.loads((output / "index.json").read_text(encoding="utf-8"))


def select_partitions(output: Path, months: list[str], destination: Path) -> Path:
    """Merge selected already-downloaded partitions into one connect-able snapshot.

    This is the "selective-download" counterpart to `build_partitioned`: a client
    fetches only the partition directories it needs (per `index.json`) and then
    calls this to produce a single directory usable with `living_glossary.data.connect`.
    Row-level checksums are re-verified per partition before merging.
    """
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Selection output must be empty; use a new version directory")
    index = load_index(output)
    available = {entry["month"]: entry for entry in index["partitions"]}
    missing = sorted(set(months) - set(available))
    if missing:
        raise ValueError(f"Unknown partition month(s): {', '.join(missing)}")
    if not months:
        raise ValueError("Select at least one month")
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "version": destination.name,
        "files": [],
        "description": "See source permission fields; no blanket corpus license.",
        "selected_months": sorted(months),
    }
    all_records: dict[str, list[dict]] = {name: [] for name in SCHEMAS}
    for name, schema in SCHEMAS.items():
        tables = []
        for month in sorted(months):
            entry = available[month]
            partition_dir = output / entry["path"]
            path = partition_dir / f"{name}.parquet"
            file_entry = {item["name"]: item for item in entry["files"]}[path.name]
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            if checksum != file_entry["sha256"]:
                raise ValueError(f"Checksum mismatch in partition {month}: {path.name}")
            tables.append(pq.read_table(path, schema=schema))
        table = pa.concat_tables(tables) if tables else pa.Table.from_pylist([], schema=schema)
        merged_path = destination / f"{name}.parquet"
        pq.write_table(table, merged_path, compression="zstd")
        manifest["files"].append({
            "name": merged_path.name, "rows": table.num_rows,
            "sha256": hashlib.sha256(merged_path.read_bytes()).hexdigest(),
        })
        all_records[name] = table.to_pylist()
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    card_path = destination / "dataset_card.json"
    card_path.write_text(
        json.dumps(dataset_card(all_records, destination.name), indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path

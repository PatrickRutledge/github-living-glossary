import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq


SCHEMA_VERSION = 2
SCHEMAS = {
    "observations": pa.schema([
        ("id", pa.string()), ("text", pa.string()), ("language", pa.string()),
        ("observed_at", pa.timestamp("us", tz="UTC")),
        ("source_url", pa.string()), ("source_kind", pa.string()),
        ("provenance", pa.string()), ("permission", pa.string()),
    ]),
    "glossary": pa.schema([
        ("id", pa.string()), ("term", pa.string()), ("language", pa.string()),
        ("sense", pa.string()), ("definition", pa.string()),
        ("target_language", pa.string()), ("translation", pa.string()),
        ("status", pa.string()), ("observation_id", pa.string()),
        ("reviewer_id", pa.string()), ("revision_of", pa.string()),
    ]),
    "annotations": pa.schema([
        ("id", pa.string()), ("observation_id", pa.string()),
        ("category", pa.string()), ("note", pa.string()),
        ("evidence", pa.string()), ("status", pa.string()),
        ("reviewer_id", pa.string()), ("evidence_id", pa.string()),
        ("revision_of", pa.string()),
    ]),
}
PROVENANCE = {"unknown", "known_automation", "declared_ai_assisted", "synthetic"}
STATUSES = {"unreviewed", "reviewed", "disputed"}
CATEGORIES = {
    "ambiguity", "translation_error", "factual_error", "unsupported_claim",
    "argument_flaw", "correction", "usage",
}
# Sentinel for optional string-typed links; keeps the "all fields are nonempty
# strings" schema contract while letting a field mean "not applicable".
NONE_LINK = "none"


def load_records(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [
            json.loads(line) for line in handle if line.strip()
        ]


def validate(records: dict[str, list[dict]]) -> None:
    for name, schema in SCHEMAS.items():
        seen = set()
        for row in records[name]:
            if set(row) != set(schema.names):
                raise ValueError(f"{name}: fields must match {schema.names}")
            if any(not isinstance(v, str) or not v.strip() for v in row.values()):
                raise ValueError(f"{name}: all source fields must be nonempty strings")
            if row["id"] in seen:
                raise ValueError(f"{name}: duplicate ID {row['id']}")
            seen.add(row["id"])
            if name == "observations":
                if row["provenance"] not in PROVENANCE:
                    raise ValueError("Invalid observation provenance")
                date = datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
                if date.tzinfo is None or date.utcoffset() is None:
                    raise ValueError("observed_at must include a timezone")
            else:
                if row["status"] not in STATUSES:
                    raise ValueError(f"{name}: invalid review status")
                if row["status"] != "unreviewed" and row["reviewer_id"] == NONE_LINK:
                    raise ValueError(f"{name}: reviewer_id is required once status is not unreviewed")
                if name == "annotations" and row["category"] not in CATEGORIES:
                    raise ValueError("Invalid annotation category")
    observations = {row["id"] for row in records["observations"]}
    for name in ("glossary", "annotations"):
        ids = {row["id"] for row in records[name]}
        for row in records[name]:
            if row["observation_id"] not in observations:
                raise ValueError(f"{name}: missing observation {row['observation_id']}")
            if row["revision_of"] != NONE_LINK:
                if row["revision_of"] not in ids:
                    raise ValueError(f"{name}: revision_of references unknown {name} id")
                if row["revision_of"] == row["id"]:
                    raise ValueError(f"{name}: revision_of cannot reference its own id")
    for row in records["annotations"]:
        if row["evidence_id"] != NONE_LINK and row["evidence_id"] not in observations:
            raise ValueError("annotations: evidence_id must reference an observation or be 'none'")


def _count_by(rows: list[dict], field: str) -> dict:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row[field]] = counts.get(row[field], 0) + 1
    return dict(sorted(counts.items()))


def dataset_card(records: dict[str, list[dict]], version: str) -> dict:
    observations = records["observations"]
    glossary = records["glossary"]
    annotations = records["annotations"]
    return {
        "version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "row_counts": {name: len(rows) for name, rows in records.items()},
        "observations": {
            "by_language": _count_by(observations, "language"),
            "by_provenance": _count_by(observations, "provenance"),
            "by_source_kind": _count_by(observations, "source_kind"),
        },
        "glossary": {
            "by_status": _count_by(glossary, "status"),
            "reviewed_without_reviewer": sum(
                1 for row in glossary
                if row["status"] != "unreviewed" and row["reviewer_id"] == NONE_LINK
            ),
        },
        "annotations": {
            "by_status": _count_by(annotations, "status"),
            "by_category": _count_by(annotations, "category"),
        },
        "notes": (
            "Counts describe this snapshot's rows only; they are not claims about a "
            "full source repository or population. Review status reflects recorded "
            "annotations, not an assessment of the underlying text's accuracy."
        ),
    }


def build(source: Path, output: Path) -> Path:
    records = {name: load_records(source / f"{name}.jsonl") for name in SCHEMAS}
    validate(records)
    return write_snapshot(records, output)


def write_snapshot(records: dict[str, list[dict]], output: Path) -> Path:
    """Write already-validated records as a Parquet snapshot with manifest and card.

    Callers (such as `partition.build_partitioned`) that slice a larger validated
    record set must not re-validate cross-table references against the slice alone:
    a glossary row's `observation_id` may correctly point outside its own partition.
    """
    if output.exists() and any(output.iterdir()):
        raise ValueError("Snapshot output must be empty; use a new version directory")
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "version": output.name,
        "files": [],
        "description": "See source permission fields; no blanket corpus license.",
    }
    for name, schema in SCHEMAS.items():
        rows = [dict(row) for row in records[name]]
        if name == "observations":
            for row in rows:
                row["observed_at"] = datetime.fromisoformat(
                    row["observed_at"].replace("Z", "+00:00")
                )
        path = output / f"{name}.parquet"
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, compression="zstd")
        manifest["files"].append({
            "name": path.name, "rows": len(rows),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    card_path = output / "dataset_card.json"
    card_path.write_text(
        json.dumps(dataset_card(records, output.name), indent=2) + "\n", encoding="utf-8"
    )
    return manifest_path


def connect(snapshot: Path) -> duckdb.DuckDBPyConnection:
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported snapshot schema version")
    files = {item["name"]: item for item in manifest["files"]}
    connection = duckdb.connect(config={"enable_external_access": "true"})
    try:
        for name in SCHEMAS:
            path = snapshot / f"{name}.parquet"
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            if checksum != files[path.name]["sha256"]:
                raise ValueError(f"Checksum mismatch: {path.name}")
            # Materialize only this chosen snapshot before disabling file/network access.
            connection.execute(
                f'CREATE TABLE "{name}" AS SELECT * FROM read_parquet(?)', [str(path)]
            )
        connection.execute("SET enable_external_access = false")
        connection.execute("SET lock_configuration = true")
        return connection
    except Exception:
        connection.close()
        raise


def query(connection: duckdb.DuckDBPyConnection, sql: str, limit: int = 1000):
    if not 1 <= limit <= 100_000:
        raise ValueError("Result limit must be between 1 and 100000")
    statements = connection.extract_statements(sql)
    if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
        raise ValueError("Only one SELECT query is allowed")
    return connection.execute(
        f"SELECT * FROM ({statements[0].query}) AS results LIMIT ?", [limit]
    ).to_arrow_table()

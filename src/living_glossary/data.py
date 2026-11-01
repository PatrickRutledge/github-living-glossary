import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq


SCHEMA_VERSION = 1
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
    ]),
    "annotations": pa.schema([
        ("id", pa.string()), ("observation_id", pa.string()),
        ("category", pa.string()), ("note", pa.string()),
        ("evidence", pa.string()), ("status", pa.string()),
    ]),
}
PROVENANCE = {"unknown", "known_automation", "declared_ai_assisted", "synthetic"}
STATUSES = {"unreviewed", "reviewed", "disputed"}
CATEGORIES = {
    "ambiguity", "translation_error", "factual_error", "unsupported_claim",
    "argument_flaw", "correction", "usage",
}


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
                if name == "annotations" and row["category"] not in CATEGORIES:
                    raise ValueError("Invalid annotation category")
    observations = {row["id"] for row in records["observations"]}
    for name in ("glossary", "annotations"):
        for row in records[name]:
            if row["observation_id"] not in observations:
                raise ValueError(f"{name}: missing observation {row['observation_id']}")


def build(source: Path, output: Path) -> Path:
    if output.exists() and any(output.iterdir()):
        raise ValueError("Snapshot output must be empty; use a new version directory")
    records = {name: load_records(source / f"{name}.jsonl") for name in SCHEMAS}
    validate(records)
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

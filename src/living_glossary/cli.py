import argparse
from pathlib import Path

import duckdb
import pyarrow.csv as csv

from living_glossary.data import build, connect, query


def main():
    parser = argparse.ArgumentParser(description="Build and query living glossary snapshots")
    commands = parser.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build")
    builder.add_argument("--source", type=Path, default=Path("data/sample"))
    builder.add_argument("--output", type=Path, required=True)
    reader = commands.add_parser("query")
    reader.add_argument("--snapshot", type=Path, required=True)
    reader.add_argument("--sql", required=True)
    reader.add_argument("--csv", type=Path, required=True)
    reader.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    try:
        if args.command == "build":
            print(build(args.source, args.output))
        else:
            with connect(args.snapshot) as connection:
                results = query(connection, args.sql, args.limit)
                csv.write_csv(results, args.csv)
                print(f"Exported {results.num_rows} rows to {args.csv}")
    except (ValueError, OSError, duckdb.Error) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()

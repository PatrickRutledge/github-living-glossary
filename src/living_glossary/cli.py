import argparse
from pathlib import Path

import duckdb
import pyarrow.csv as csv

from living_glossary.data import build, connect, query
from living_glossary.terms import mine_candidates, write_candidates


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
    miner = commands.add_parser("mine-terms")
    miner.add_argument("--snapshot", type=Path, required=True)
    miner.add_argument("--output", type=Path, required=True)
    miner.add_argument("--min-frequency", type=int, default=2)
    miner.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    try:
        if args.command == "build":
            print(build(args.source, args.output))
        elif args.command == "query":
            with connect(args.snapshot) as connection:
                results = query(connection, args.sql, args.limit)
                csv.write_csv(results, args.csv)
                print(f"Exported {results.num_rows} rows to {args.csv}")
        else:
            with connect(args.snapshot) as connection:
                candidates = mine_candidates(
                    connection, min_frequency=args.min_frequency, limit=args.limit
                )
                path = write_candidates(candidates, args.output)
                print(
                    f"Wrote {len(candidates)} unreviewed term candidates to {path}. "
                    "Review before adding to any glossary.jsonl."
                )
    except (ValueError, OSError, duckdb.Error) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()


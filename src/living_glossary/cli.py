import argparse
import os
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
    renderer = commands.add_parser("render")
    renderer.add_argument("--snapshot", type=Path, required=True)
    renderer.add_argument("--output", type=Path, required=True)
    renderer.add_argument("--title", default="Living Glossary")
    curator = commands.add_parser("curate")
    curator.add_argument("--source", type=Path, required=True,
                         help="Source directory with observations.jsonl/glossary.jsonl, e.g. data/sample")
    curator.add_argument("--term", required=True)
    curator.add_argument("--language", required=True)
    curator.add_argument("--sense", required=True)
    curator.add_argument("--definition", required=True)
    curator.add_argument("--reviewer-id", required=True)
    curator.add_argument("--observation-id", required=True)
    curator.add_argument("--target-language", default="none")
    curator.add_argument("--translation", default="none")
    curator.add_argument("--status", default="reviewed", choices=["unreviewed", "reviewed", "disputed"])
    curator.add_argument("--revision-of", default="none")
    commands.add_parser("generate-keypair")
    signer = commands.add_parser("sign")
    signer.add_argument("--snapshot", type=Path, required=True)
    signer.add_argument(
        "--private-key", help="Base64 Ed25519 private key; defaults to $GLOSSARY_PRIVATE_KEY"
    )
    verifier = commands.add_parser("verify-signature")
    verifier.add_argument("--snapshot", type=Path, required=True)
    verifier.add_argument(
        "--public-key", help="Base64 Ed25519 public key; defaults to $GLOSSARY_PUBLIC_KEY"
    )
    partitioner = commands.add_parser("build-partitioned")
    partitioner.add_argument("--source", type=Path, default=Path("data/sample"))
    partitioner.add_argument("--output", type=Path, required=True)
    selector = commands.add_parser("select-partitions")
    selector.add_argument("--output", type=Path, required=True,
                          help="Partitioned directory written by build-partitioned")
    selector.add_argument("--months", nargs="+", required=True, help="e.g. 2026-01 2026-02")
    selector.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "build":
            print(build(args.source, args.output))
        elif args.command == "query":
            with connect(args.snapshot) as connection:
                results = query(connection, args.sql, args.limit)
                csv.write_csv(results, args.csv)
                print(f"Exported {results.num_rows} rows to {args.csv}")
        elif args.command == "mine-terms":
            with connect(args.snapshot) as connection:
                candidates = mine_candidates(
                    connection, min_frequency=args.min_frequency, limit=args.limit
                )
                path = write_candidates(candidates, args.output)
                print(
                    f"Wrote {len(candidates)} unreviewed term candidates to {path}. "
                    "Review before adding to any glossary.jsonl."
                )
        elif args.command == "render":
            from living_glossary.render import render
            with connect(args.snapshot) as connection:
                path = render(connection, args.output, title=args.title)
                print(f"Wrote reviewed glossary page to {path}")
        elif args.command == "curate":
            from living_glossary.curate import append_glossary_entry
            entry = append_glossary_entry(
                args.source,
                term=args.term,
                language=args.language,
                sense=args.sense,
                definition=args.definition,
                reviewer_id=args.reviewer_id,
                observation_id=args.observation_id,
                target_language=args.target_language,
                translation=args.translation,
                status=args.status,
                revision_of=args.revision_of,
            )
            print(f"Appended glossary entry {entry['id']} to {args.source / 'glossary.jsonl'}")
        elif args.command == "generate-keypair":
            from living_glossary.signing import generate_keypair
            private_key, public_key = generate_keypair()
            print(f"GLOSSARY_PRIVATE_KEY={private_key}")
            print(f"GLOSSARY_PUBLIC_KEY={public_key}")
            print("Store the private key as a secret; the public key may be published.")
        elif args.command == "sign":
            from living_glossary.signing import sign_manifest
            private_key = args.private_key or os.environ.get("GLOSSARY_PRIVATE_KEY")
            if not private_key:
                raise ValueError("Provide --private-key or set GLOSSARY_PRIVATE_KEY")
            path = sign_manifest(args.snapshot, private_key)
            print(f"Wrote signature to {path}")
        elif args.command == "verify-signature":
            from living_glossary.signing import verify_manifest
            public_key = args.public_key or os.environ.get("GLOSSARY_PUBLIC_KEY")
            if not public_key:
                raise ValueError("Provide --public-key or set GLOSSARY_PUBLIC_KEY")
            verify_manifest(args.snapshot, public_key)
            print("Signature valid for this manifest.")
        elif args.command == "build-partitioned":
            from living_glossary.partition import build_partitioned
            path = build_partitioned(args.source, args.output)
            print(f"Wrote partition index to {path}")
        else:
            from living_glossary.partition import select_partitions
            path = select_partitions(args.output, args.months, args.destination)
            print(f"Merged {len(args.months)} partition(s) into {path}")
    except (ValueError, OSError, duckdb.Error) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()



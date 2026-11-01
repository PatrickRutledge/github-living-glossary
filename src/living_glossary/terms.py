"""Mine unreviewed term candidates from a snapshot's observations.

Candidates are suggestions only: frequency, contextual observation links, and the
source observation's recorded language (which may be `und`, i.e. uncertain). Humans
decide whether a candidate becomes a real `glossary` entry; this module never writes
to the glossary table and never assigns a translation, sense, or definition.
"""
import json
import re
from pathlib import Path

import duckdb


TOKEN = re.compile(r"[^\W\d_]{2,}", re.UNICODE)

# Minimal, English-only function-word filter. Other languages are not filtered,
# since a small ad hoc stopword list would be misleading about completeness.
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "been",
    "to", "of", "in", "on", "for", "with", "this", "that", "it", "as", "by", "at",
    "from", "not", "will", "would", "can", "could", "should", "have", "has", "had",
    "if", "then", "than", "so", "you", "your", "we", "our", "they", "their",
}


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN.findall(text)]


def existing_terms(connection: duckdb.DuckDBPyConnection) -> set[tuple[str, str]]:
    rows = connection.execute("SELECT DISTINCT term, language FROM glossary").fetchall()
    return {(term.lower(), language) for term, language in rows}


def mine_candidates(
    connection: duckdb.DuckDBPyConnection,
    min_frequency: int = 1,
    limit: int = 100,
    max_links: int = 10,
) -> list[dict]:
    if min_frequency < 1:
        raise ValueError("min_frequency must be at least 1")
    known = existing_terms(connection)
    observations = connection.execute(
        "SELECT id, text, language FROM observations"
    ).fetchall()
    counts: dict[tuple[str, str], dict] = {}
    for observation_id, text, language in observations:
        for token in set(tokenize(text)):
            if language == "en" and token in STOPWORDS:
                continue
            if (token, language) in known:
                continue
            key = (token, language)
            entry = counts.setdefault(key, {"frequency": 0, "observation_ids": []})
            entry["frequency"] += 1
            if len(entry["observation_ids"]) < max_links:
                entry["observation_ids"].append(observation_id)
    candidates = [
        {
            "id": f"candidate:{language}:{term}",
            "term": term,
            "language": language,
            "frequency": entry["frequency"],
            "observation_ids": sorted(entry["observation_ids"]),
            "status": "suggested",
        }
        for (term, language), entry in counts.items()
        if entry["frequency"] >= min_frequency
    ]
    candidates.sort(key=lambda row: (-row["frequency"], row["language"], row["term"]))
    return candidates[:limit]


def write_candidates(candidates: list[dict], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in candidates),
        encoding="utf-8",
    )
    return output

import json
from pathlib import Path

import pytest

from living_glossary.data import build, connect
from living_glossary.terms import mine_candidates, tokenize, write_candidates


SAMPLE = Path(__file__).resolve().parents[1] / "data/sample"


@pytest.fixture
def snapshot(tmp_path):
    path = tmp_path / "snapshot"
    build(SAMPLE, path)
    return path


def test_tokenize_lowercases_and_drops_short_tokens():
    assert tokenize("Squash it, Please!") == ["squash", "it", "please"]
    assert tokenize("a I") == []


def test_mine_candidates_excludes_known_glossary_terms(snapshot):
    with connect(snapshot) as connection:
        candidates = mine_candidates(connection, min_frequency=1)
        terms = {(c["term"], c["language"]) for c in candidates}
        # "squash" and "fusion" are already in the sample glossary.
        assert ("squash", "en") not in terms
        assert ("fusion", "fr") not in terms
        assert all(c["status"] == "suggested" for c in candidates)
        assert all(c["observation_ids"] for c in candidates)


def test_mine_candidates_frequency_and_links(snapshot):
    with connect(snapshot) as connection:
        candidates = mine_candidates(connection, min_frequency=1, max_links=1)
        for candidate in candidates:
            assert candidate["frequency"] >= 1
            assert len(candidate["observation_ids"]) <= 1
        # Sorted by descending frequency.
        frequencies = [c["frequency"] for c in candidates]
        assert frequencies == sorted(frequencies, reverse=True)


def test_mine_candidates_respects_limit(snapshot):
    with connect(snapshot) as connection:
        candidates = mine_candidates(connection, min_frequency=1, limit=1)
        assert len(candidates) <= 1


def test_mine_candidates_rejects_bad_frequency(snapshot):
    with connect(snapshot) as connection:
        with pytest.raises(ValueError, match="min_frequency"):
            mine_candidates(connection, min_frequency=0)


def test_mine_candidates_filters_und_stopwords_and_noise(snapshot):
    with connect(snapshot) as connection:
        connection.execute(
            """
            INSERT INTO observations
                (id, text, language, observed_at, source_url, source_kind, provenance, permission)
            VALUES
                (?, ?, 'und', TIMESTAMP '2024-01-01', 'https://example.test', 'issue_or_pr',
                 'unknown', 'public-repo')
            """,
            [
                "obs-und-noise",
                "Please update the docs after closing this pr, see https://github.com/example",
            ],
        )
        candidates = mine_candidates(connection, min_frequency=1)
        terms = {(c["term"], c["language"]) for c in candidates}
        for noisy in ("the", "after", "closing", "https", "github", "pr", "docs"):
            assert (noisy, "und") not in terms


def test_write_candidates(tmp_path):
    output = tmp_path / "out" / "candidates.jsonl"
    rows = [{"id": "candidate:en:patch", "term": "patch", "language": "en",
             "frequency": 2, "observation_ids": ["sample-2"], "status": "suggested"}]
    path = write_candidates(rows, output)
    lines = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    assert lines == rows

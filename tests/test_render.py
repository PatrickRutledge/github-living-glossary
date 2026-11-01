from pathlib import Path

import pytest

from living_glossary.data import build, connect
from living_glossary.render import fetch_reviewed_entries, render, render_markdown


SAMPLE = Path(__file__).resolve().parents[1] / "data/sample"


@pytest.fixture
def snapshot(tmp_path):
    path = tmp_path / "snapshot"
    build(SAMPLE, path)
    return path


def test_fetch_reviewed_entries_excludes_unreviewed(snapshot):
    with connect(snapshot) as connection:
        # The sample glossary entry is "unreviewed"; nothing should be published yet.
        assert fetch_reviewed_entries(connection) == []


def test_fetch_reviewed_entries_includes_reviewed(snapshot):
    with connect(snapshot) as connection:
        connection.execute(
            """
            INSERT INTO glossary
                (id, term, language, sense, definition, target_language, translation,
                 status, observation_id, reviewer_id, revision_of)
            VALUES
                ('term-reviewed', 'rebase', 'und', 'git.rebase',
                 'Reapply commits on top of another base tip.', 'none', 'none',
                 'reviewed', 'sample-3', 'alice', 'none')
            """
        )
        entries = fetch_reviewed_entries(connection)
        assert len(entries) == 1
        assert entries[0]["term"] == "rebase"
        assert entries[0]["reviewer_id"] == "alice"


def test_render_markdown_handles_empty_and_populated():
    assert "No reviewed glossary entries yet" in render_markdown([])
    entries = [{
        "term": "rebase", "language": "und", "sense": "git.rebase",
        "definition": "Reapply commits on top of another base tip.",
        "target_language": "none", "translation": "none",
        "observation_id": "sample-3", "reviewer_id": "alice", "revision_of": "none",
    }]
    markdown = render_markdown(entries)
    assert "rebase" in markdown
    assert "sample-3" in markdown
    assert "alice" in markdown


def test_render_writes_file(snapshot, tmp_path):
    with connect(snapshot) as connection:
        output = render(connection, tmp_path / "glossary.md")
        assert output.exists()
        assert "Living Glossary" in output.read_text(encoding="utf-8")

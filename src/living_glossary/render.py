"""Render a reviewed glossary snapshot as a static, browsable Markdown page.

Only entries with `status == "reviewed"` are included: unreviewed suggestions and
disputed entries are not published, since the whole point of this project is that
nothing reaches readers without a human reviewer vouching for it. Each entry links
back to its supporting observation for evidence, and to any prior revision it
replaces, so readers can trace how a definition changed over time.
"""
from pathlib import Path

import duckdb


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def fetch_reviewed_entries(connection: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT term, language, sense, definition, target_language, translation,
               observation_id, reviewer_id, revision_of
        FROM glossary
        WHERE status = 'reviewed'
        ORDER BY language, term
        """
    ).fetchall()
    columns = [
        "term", "language", "sense", "definition", "target_language",
        "translation", "observation_id", "reviewer_id", "revision_of",
    ]
    return [dict(zip(columns, row)) for row in rows]


def render_markdown(entries: list[dict], title: str = "Living Glossary") -> str:
    lines = [f"# {title}", "", f"{len(entries)} reviewed term(s). Generated from a signed snapshot.", ""]
    if not entries:
        lines.append("_No reviewed glossary entries yet._")
        return "\n".join(lines) + "\n"
    lines.append("| Term | Language | Sense | Definition | Translation | Evidence | Reviewer |")
    lines.append("|---|---|---|---|---|---|---|")
    for entry in entries:
        translation = (
            f"{_escape(entry['translation'])} ({entry['target_language']})"
            if entry["translation"] != "none" else "-"
        )
        evidence = entry["observation_id"]
        lines.append(
            f"| {_escape(entry['term'])} | {entry['language']} | {_escape(entry['sense'])} | "
            f"{_escape(entry['definition'])} | {translation} | `{evidence}` | {entry['reviewer_id']} |"
        )
    return "\n".join(lines) + "\n"


def render(connection: duckdb.DuckDBPyConnection, output: Path, title: str = "Living Glossary") -> Path:
    entries = fetch_reviewed_entries(connection)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(entries, title=title), encoding="utf-8")
    return output

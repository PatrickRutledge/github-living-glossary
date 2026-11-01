import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "collector", Path(__file__).resolve().parents[1] / "scripts/collect.py"
)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def test_empty_allowlist(tmp_path):
    config = tmp_path / "sources.json"
    config.write_text('{"sources":[]}')
    with pytest.raises(ValueError, match="No permission"):
        collector.collect(
            config, tmp_path / "output", tmp_path / "state.json", tmp_path / "history.jsonl"
        )


def test_sensitive_detection():
    assert collector.SENSITIVE.search("contact person@example.com")
    assert collector.SENSITIVE.search("-----BEGIN RSA PRIVATE KEY-----")
    assert not collector.SENSITIVE.search("Please merge this branch")


def test_collect_preserves_unknown_and_bot(tmp_path, monkeypatch):
    config = tmp_path / "sources.json"
    config.write_text(json.dumps({"sources": [{
        "repo": "example/project", "since": "2026-01-01T00:00:00Z",
        "permission": "Permission fixture",
    }]}))
    monkeypatch.setattr(collector, "request", lambda *args: {"private": False})
    def rows(path, since):
        return [{
            "id": 1, "body": "Merge the patch.", "updated_at": since,
            "html_url": "https://github.com/example/project/issues/1",
            "user": {"type": "Bot" if path.endswith("comments") else "User"},
        }]
    monkeypatch.setattr(collector, "pages", rows)
    output = tmp_path / "output"
    collector.collect(
        config, output, tmp_path / "state.json", tmp_path / "history.jsonl"
    )
    observations = [
        json.loads(line) for line in (output / "observations.jsonl").read_text().splitlines()
    ]
    assert {row["provenance"] for row in observations} == {"unknown", "known_automation"}
    assert all(row["language"] == "und" for row in observations)


def test_incremental_new_edit_delete(tmp_path, monkeypatch):
    config = tmp_path / "sources.json"
    config.write_text(json.dumps({"sources": [{
        "repo": "example/project", "since": "2026-01-01T00:00:00Z",
        "permission": "Permission fixture",
    }]}))
    monkeypatch.setattr(collector, "request", lambda *args: {"private": False})
    state_path = tmp_path / "state.json"
    history_path = tmp_path / "history.jsonl"

    first_rows = {
        "issues": [{
            "id": 1, "body": "Merge the patch.", "updated_at": "2026-01-02T00:00:00Z",
            "html_url": "https://github.com/example/project/issues/1", "user": {"type": "User"},
        }],
        "comments": [],
    }
    monkeypatch.setattr(
        collector, "pages",
        lambda path, since: first_rows["issues"] if path.endswith("issues") else first_rows["comments"],
    )
    collector.collect(config, tmp_path / "out1", state_path, history_path)
    history = [json.loads(l) for l in history_path.read_text().splitlines()]
    assert [event["event"] for event in history] == ["new"]

    # Second run: same item edited (hash changes).
    second_rows = {
        "issues": [{
            "id": 1, "body": "Merge the patch, please.", "updated_at": "2026-01-03T00:00:00Z",
            "html_url": "https://github.com/example/project/issues/1", "user": {"type": "User"},
        }],
        "comments": [],
    }
    monkeypatch.setattr(
        collector, "pages",
        lambda path, since: second_rows["issues"] if path.endswith("issues") else second_rows["comments"],
    )
    collector.collect(config, tmp_path / "out2", state_path, history_path)
    history = [json.loads(l) for l in history_path.read_text().splitlines()]
    assert [event["event"] for event in history] == ["new", "edited"]

    # Third run: item no longer returned by the API window and no longer exists upstream.
    monkeypatch.setattr(collector, "pages", lambda path, since: [])
    monkeypatch.setattr(collector, "item_exists", lambda repo, kind, item_id: False)
    collector.collect(config, tmp_path / "out3", state_path, history_path)
    history = [json.loads(l) for l in history_path.read_text().splitlines()]
    assert [event["event"] for event in history] == ["new", "edited", "deleted"]
    state = json.loads(state_path.read_text())
    item = next(iter(state["sources"]["example/project"]["items"].values()))
    assert item["present"] is False


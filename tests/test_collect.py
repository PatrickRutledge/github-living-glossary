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
    # Changelog/Dependabot version-range notation like "pkg@6.30.2...pkg@6.30.1" must
    # not be mistaken for an email address (regression: real false positive found
    # while dry-running collection against a live Dependabot PR body).
    assert not collector.SENSITIVE.search(
        "Bumps react-router from 6.30.1 to 6.30.2.\n"
        "**Full Changelog**: react-router@6.30.1...react-router@6.30.2"
    )


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


def test_private_repo_requires_allow_private(tmp_path, monkeypatch):
    config = tmp_path / "sources.json"
    config.write_text(json.dumps({"sources": [{
        "repo": "example/private-project", "since": "2026-01-01T00:00:00Z",
        "permission": "Permission fixture",
    }]}))
    monkeypatch.setattr(collector, "request", lambda *args: {"private": True})
    with pytest.raises(ValueError, match="allow_private"):
        collector.collect(
            config, tmp_path / "output", tmp_path / "state.json", tmp_path / "history.jsonl"
        )


def test_private_repo_allowed_with_flag(tmp_path, monkeypatch):
    config = tmp_path / "sources.json"
    config.write_text(json.dumps({"sources": [{
        "repo": "example/private-project", "since": "2026-01-01T00:00:00Z",
        "permission": "Permission fixture", "allow_private": True,
    }]}))
    monkeypatch.setattr(collector, "request", lambda *args: {"private": True})
    monkeypatch.setattr(collector, "pages", lambda path, since: [])
    output = tmp_path / "output"
    collector.collect(config, output, tmp_path / "state.json", tmp_path / "history.jsonl")
    assert (output / "observations.jsonl").exists()


def test_discover_owner_repos_paginates(monkeypatch):
    calls = []
    def fake_request(path, params=None):
        calls.append(params["page"])
        if params["page"] == 1:
            return [{"full_name": f"me/repo{i}"} for i in range(100)]
        return [{"full_name": "me/repo100"}]
    monkeypatch.setattr(collector, "request", fake_request)
    repos = collector.discover_owner_repos()
    assert repos == [f"me/repo{i}" for i in range(100)] + ["me/repo100"]
    assert calls == [1, 2]


def test_expand_sources_owner_self(monkeypatch):
    monkeypatch.setattr(
        collector, "discover_owner_repos", lambda: ["me/one", "me/two"]
    )
    sources = [{
        "owner_self": True, "since": "2026-01-01T00:00:00Z", "permission": "Self-owned repos",
    }]
    expanded = collector.expand_sources(sources)
    assert [s["repo"] for s in expanded] == ["me/one", "me/two"]
    assert all(s["allow_private"] for s in expanded)
    assert all(s["permission"] == "Self-owned repos" for s in expanded)


def test_expand_sources_passthrough():
    sources = [{
        "repo": "owner/repo", "since": "2026-01-01T00:00:00Z", "permission": "fixture",
    }]
    assert collector.expand_sources(sources) == sources


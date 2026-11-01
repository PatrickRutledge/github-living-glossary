"""Collect permission-cleared public issue text; do not infer AI authorship."""
import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SENSITIVE = re.compile(
    # Domain must start with a letter so version-range notation like
    # "package@6.30.2...package@6.30.1" (common in changelog/Dependabot PR bodies)
    # is not mistaken for an email address.
    r"[\w.+-]+@[A-Za-z][\w.-]*\.[A-Za-z]{2,}|"
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]+)|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
)


class GitHubError(RuntimeError):
    def __init__(self, status: int, path: str):
        super().__init__(f"GitHub returned HTTP {status} for {path}; collection stopped")
        self.status = status


def request(path, params=None):
    url = "https://api.github.com" + path
    if params:
        url += "?" + urlencode(params)
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "living-glossary",
               "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        with urlopen(Request(url, headers=headers), timeout=60) as response:
            return json.load(response)
    except HTTPError as error:
        raise GitHubError(error.code, path) from error


def item_exists(repo: str, kind: str, item_id: str) -> bool:
    endpoint = "issues" if kind == "issue_or_pr" else "issues/comments"
    try:
        request(f"/repos/{repo}/{endpoint}/{item_id}")
        return True
    except GitHubError as error:
        if error.status == 404:
            return False
        raise


def discover_owner_repos() -> list[str]:
    """List repositories owned by the authenticated token's account, public and private.

    GitHub scopes `/user/repos?affiliation=owner` to the authenticated user; it cannot
    be used to enumerate another account's private repositories. This is what makes
    `owner_self` sources safe to mark `allow_private` automatically: the token's owner
    is, by definition, the only person who can grant permission for their own repos.
    """
    repos = []
    for page in range(1, 101):
        rows = request("/user/repos", {
            "affiliation": "owner", "per_page": 100, "page": page, "visibility": "all",
        })
        repos.extend(row["full_name"] for row in rows)
        if len(rows) < 100:
            break
    else:
        raise RuntimeError("Owner repository list exceeded 100 pages")
    return repos


def expand_sources(sources: list[dict]) -> list[dict]:
    expanded = []
    for source in sources:
        if source.get("owner_self"):
            for repo in discover_owner_repos():
                expanded.append({
                    "repo": repo,
                    "since": source["since"],
                    "permission": source["permission"],
                    "allow_private": True,
                })
        else:
            expanded.append(source)
    return expanded


def load_state(path: Path) -> dict:
    if path and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"sources": {}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def pages(path, since):
    for page in range(1, 101):
        rows = request(path, {"since": since, "per_page": 100, "page": page})
        yield from rows
        if len(rows) < 100:
            return
    raise RuntimeError("Collection exceeded 100 pages; narrow the source interval")


def parse_identifier(identifier: str):
    _, repo, kind, item_id = identifier.split(":", 3)
    return repo, kind, item_id


def collect(
    config: Path,
    output: Path,
    state_path: Path = Path("data/state/collection_state.json"),
    history_path: Path = Path("data/state/history.jsonl"),
):
    sources = expand_sources(json.loads(config.read_text(encoding="utf-8"))["sources"])
    if not sources:
        raise ValueError("No permission-cleared sources configured; refusing live collection")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Collection output must be empty")
    state = load_state(state_path)
    run_at = datetime.now(timezone.utc).isoformat()
    history_events = []
    observations = {}
    for source in sources:
        repo = source["repo"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("Invalid repository name")
        permission = source["permission"]
        if not isinstance(permission, str) or not permission.strip():
            raise ValueError("Explicit redistribution permission is required")
        if request(f"/repos/{repo}")["private"] and not source.get("allow_private"):
            raise ValueError(
                f"{repo} is private; set \"allow_private\": true to collect it "
                "(only appropriate for repositories you have authority over)"
            )
        source_state = state["sources"].setdefault(
            repo, {"since": source["since"], "items": {}}
        )
        effective_since = max(source["since"], source_state["since"])
        seen_this_run = set()
        for endpoint, kind in [("issues", "issue_or_pr"), ("issues/comments", "comment")]:
            for item in pages(f"/repos/{repo}/{endpoint}", effective_since):
                text = "\n\n".join(
                    value for value in [item.get("title"), item.get("body")] if value
                )
                if not text.strip():
                    continue
                if SENSITIVE.search(text):
                    raise ValueError(
                        f"Potential sensitive text in {repo} {kind} {item['id']}; "
                        "collection stopped for review (content not logged)"
                    )
                identifier = f"github:{repo}:{kind}:{item['id']}"
                seen_this_run.add(identifier)
                text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                prior = source_state["items"].get(identifier)
                if prior is None:
                    history_events.append({
                        "ts": run_at, "event": "new", "id": identifier, "repo": repo,
                    })
                elif prior.get("hash") != text_hash:
                    history_events.append({
                        "ts": run_at, "event": "edited", "id": identifier, "repo": repo,
                    })
                source_state["items"][identifier] = {
                    "hash": text_hash, "updated_at": item["updated_at"], "present": True,
                }
                observations[identifier] = {
                    "id": identifier, "text": text, "language": "und",
                    "observed_at": item["updated_at"], "source_url": item["html_url"],
                    "source_kind": kind,
                    "provenance": (
                        "known_automation" if (item.get("user") or {}).get("type") == "Bot"
                        else "unknown"
                    ),
                    "permission": permission,
                }
        # Deletion detection is bounded to items whose last known update falls inside
        # the window just queried: they should have been returned by `since` filtering,
        # so a miss is a deletion signal. Older items dropping out of the window is
        # expected and does not trigger a lookup.
        for identifier, info in source_state["items"].items():
            if identifier in seen_this_run or not info.get("present", True):
                continue
            if info["updated_at"] < effective_since:
                continue
            _, kind, item_id = parse_identifier(identifier)
            if not item_exists(repo, kind, item_id):
                info["present"] = False
                history_events.append({
                    "ts": run_at, "event": "deleted", "id": identifier, "repo": repo,
                })
        updated_ats = [info["updated_at"] for info in source_state["items"].values()]
        if updated_ats:
            source_state["since"] = max(effective_since, max(updated_ats))
    output.mkdir(parents=True, exist_ok=True)
    rows = [observations[key] for key in sorted(observations)]
    (output / "observations.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    for name in ("glossary", "annotations"):
        (output / f"{name}.jsonl").write_text("", encoding="utf-8")
    if history_events:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        with history_path.open("a", encoding="utf-8") as handle:
            for event in history_events:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    save_state(state_path, state)
    counts = {kind: sum(1 for e in history_events if e["event"] == kind)
              for kind in ("new", "edited", "deleted")}
    print(
        f"Collected {len(rows)} observations this window "
        f"(new={counts['new']} edited={counts['edited']} deleted={counts['deleted']}). "
        "Language and content annotations require review."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config/sources.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state", type=Path, default=Path("data/state/collection_state.json"))
    parser.add_argument("--history", type=Path, default=Path("data/state/history.jsonl"))
    args = parser.parse_args()
    collect(args.config, args.output, args.state, args.history)


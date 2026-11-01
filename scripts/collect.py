"""Collect permission-cleared public issue text; do not infer AI authorship."""
import argparse
import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SENSITIVE = re.compile(
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|"
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]+)|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
)


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
        raise RuntimeError(f"GitHub returned HTTP {error.code} for {path}; collection stopped") from error


def pages(path, since):
    for page in range(1, 101):
        rows = request(path, {"since": since, "per_page": 100, "page": page})
        yield from rows
        if len(rows) < 100:
            return
    raise RuntimeError("Collection exceeded 100 pages; narrow the source interval")


def collect(config: Path, output: Path):
    sources = json.loads(config.read_text(encoding="utf-8"))["sources"]
    if not sources:
        raise ValueError("No permission-cleared sources configured; refusing live collection")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Collection output must be empty")
    observations = {}
    for source in sources:
        repo = source["repo"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("Invalid repository name")
        permission = source["permission"]
        if not isinstance(permission, str) or not permission.strip():
            raise ValueError("Explicit redistribution permission is required")
        if request(f"/repos/{repo}")["private"]:
            raise ValueError("Private repository collection is disabled")
        for endpoint, kind in [("issues", "issue_or_pr"), ("issues/comments", "comment")]:
            for item in pages(f"/repos/{repo}/{endpoint}", source["since"]):
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
    output.mkdir(parents=True, exist_ok=True)
    rows = [observations[key] for key in sorted(observations)]
    (output / "observations.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    for name in ("glossary", "annotations"):
        (output / f"{name}.jsonl").write_text("", encoding="utf-8")
    print(f"Collected {len(rows)} observations. Language and content annotations require review.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config/sources.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    collect(args.config, args.output)

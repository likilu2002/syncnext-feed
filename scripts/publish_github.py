#!/usr/bin/env python3
import base64
import json
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "syncnext-feed"
BRANCH = "main"
FILES = [
    ".gitignore",
    "README.md",
    "data/seed_sources.json",
    "data/source_feeds.json",
    "public/sourcesv3.json",
    "public/shortlink.txt",
    "public/update-report.json",
    "scripts/update_syncnext.py",
    "scripts/publish_fragbin.py",
    "scripts/publish_github.py",
    ".github/workflows/update-syncnext.yml",
]


def api(token, method, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"https://api.github.com{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "syncnext-feed-publisher/1.0",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"GitHub API {method} {path} failed: {exc.code} {body}") from exc


def get_or_create_repo(token, owner, name):
    try:
        return api(token, "GET", f"/repos/{owner}/{name}")
    except RuntimeError as exc:
        if "404" not in str(exc):
            raise
    return api(
        token,
        "POST",
        "/user/repos",
        {
            "name": name,
            "description": "Personal SyncNext subscription feed.",
            "private": False,
            "auto_init": True,
        },
    )


def file_sha(token, owner, repo, path):
    try:
        result = api(token, "GET", f"/repos/{owner}/{repo}/contents/{quote(path)}?ref={BRANCH}")
        return result.get("sha")
    except RuntimeError as exc:
        if "404" in str(exc):
            return None
        raise


def put_file(token, owner, repo, path):
    src = ROOT / path
    if not src.exists():
        return
    content = base64.b64encode(src.read_bytes()).decode("ascii")
    payload = {
        "message": f"Update {path}",
        "content": content,
        "branch": BRANCH,
    }
    sha = file_sha(token, owner, repo, path)
    if sha:
        payload["sha"] = sha
    api(token, "PUT", f"/repos/{owner}/{repo}/contents/{quote(path)}", payload)


def main():
    token = sys.stdin.read().strip()
    if not token:
        raise SystemExit("Paste a GitHub token on stdin.")

    user = api(token, "GET", "/user")
    owner = user["login"]
    repo = DEFAULT_REPO
    get_or_create_repo(token, owner, repo)

    for path in FILES:
        put_file(token, owner, repo, path)

    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{BRANCH}/public/sourcesv3.json"
    repo_url = f"https://github.com/{owner}/{repo}"
    print(json.dumps({"repo": repo_url, "raw": raw_url}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

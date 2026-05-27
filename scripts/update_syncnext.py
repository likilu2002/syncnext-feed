#!/usr/bin/env python3
import argparse
import json
import sys
import uuid
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SEED_FILE = ROOT / "data" / "seed_sources.json"
FEEDS_FILE = ROOT / "data" / "source_feeds.json"
OUTPUT_FILE = ROOT / "public" / "sourcesv3.json"
REPORT_FILE = ROOT / "public" / "update-report.json"


def load_json(path, fallback):
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def fetch_json(url, timeout=20):
    request = Request(
        url,
        headers={
            "User-Agent": "syncnext-personal-feed-updater/1.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def normalize_item(item):
    if not isinstance(item, dict):
        return None
    api = item.get("api")
    name = item.get("name") or item.get("title")
    if not isinstance(api, str) or not api.strip() or not isinstance(name, str) or not name.strip():
        return None

    normalized = dict(item)
    normalized["api"] = api.strip()
    normalized["name"] = name.strip()
    normalized.setdefault("id", str(uuid.uuid5(uuid.NAMESPACE_URL, normalized["api"])))
    normalized.setdefault("Search", True)
    return normalized


def merge_sources(groups):
    by_api = {}
    for group in groups:
        if not isinstance(group, list):
            continue
        for raw_item in group:
            item = normalize_item(raw_item)
            if not item:
                continue
            existing = by_api.get(item["api"])
            if not existing:
                by_api[item["api"]] = item
                continue
            existing.update({key: value for key, value in item.items() if value not in (None, "", [])})

    return sorted(
        by_api.values(),
        key=lambda item: (
            not bool(item.get("Top", False)),
            int(item.get("Priority", 999999)),
            item.get("name", ""),
        ),
    )


def main():
    parser = argparse.ArgumentParser(description="Build a personal SyncNext sourcesv3.json feed.")
    parser.add_argument("--offline", action="store_true", help="Use only local seed sources.")
    args = parser.parse_args()

    groups = [load_json(SEED_FILE, [])]
    fetched = []
    failed = []

    if not args.offline:
        for feed in load_json(FEEDS_FILE, []):
            url = feed.get("url")
            if not url:
                continue
            try:
                groups.append(fetch_json(url))
                fetched.append(url)
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                failed.append({"url": url, "error": str(exc)})

    merged = merge_sources(groups)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_FILE.write_text(
        json.dumps(
            {
                "total": len(merged),
                "fetched": fetched,
                "failed": failed,
                "output": str(OUTPUT_FILE),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(merged)} sources to {OUTPUT_FILE}")
    if failed:
        print(f"{len(failed)} feed(s) failed; see {REPORT_FILE}", file=sys.stderr)


if __name__ == "__main__":
    main()

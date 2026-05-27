#!/usr/bin/env python3
import argparse
import json
import sys
import uuid
from pathlib import Path
from urllib.parse import urljoin
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SEED_FILE = ROOT / "data" / "seed_sources.json"
FEEDS_FILE = ROOT / "data" / "source_feeds.json"
TVBOX_FEEDS_FILE = ROOT / "data" / "tvbox_feeds.json"
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


def absolute_url(base_url, value):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value:
        return ""
    return urljoin(base_url, value)


def is_direct_vod_api(api):
    if not isinstance(api, str):
        return False
    lowered = api.lower()
    if lowered.startswith(("csp_", "js:", "drpy", "assets://", "file://")):
        return False
    if any(marker in lowered for marker in ("provide/vod", "seaxml/vod", "inc/api.php")):
        return True
    return lowered.endswith(("api.php", "api.php/provide/vod", "/provide/vod"))


def normalize_tvbox_api(api):
    if not isinstance(api, str):
        return ""
    api = api.strip()
    if not api:
        return ""
    if any(marker in api.lower() for marker in ("provide/vod", "seaxml/vod", "inc/api.php")):
        return api
    if api.endswith("/"):
        return api + "api.php/provide/vod/at/xml"
    return api


def tvbox_sites_to_syncnext(config, source_url):
    if not isinstance(config, dict):
        return [], [{"source": source_url, "reason": "config is not an object"}]

    converted = []
    skipped = []
    for site in config.get("sites", []):
        if not isinstance(site, dict):
            continue
        raw_api = absolute_url(source_url, site.get("api", ""))
        name = site.get("name") or site.get("key")
        if not name or not is_direct_vod_api(raw_api):
            skipped.append(
                {
                    "source": source_url,
                    "name": name or site.get("key") or "",
                    "api": raw_api,
                    "reason": "not a direct CMS/VOD API",
                }
            )
            continue

        item = {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, raw_api)),
            "Top": bool(site.get("top", False)),
            "Priority": 520000,
            "Search": bool(site.get("searchable", 1)),
            "name": str(name).strip(),
            "api": normalize_tvbox_api(raw_api),
            "note": f"TVBox import: {site.get('key', source_url)}",
        }
        if site.get("quickSearch") == 0:
            item["Search"] = False
        converted.append(item)

    return converted, skipped


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
    tvbox_imported = []
    tvbox_skipped = []
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

        for feed in load_json(TVBOX_FEEDS_FILE, []):
            url = feed.get("url")
            if not url:
                continue
            try:
                config = fetch_json(url)
                converted, skipped = tvbox_sites_to_syncnext(config, url)
                groups.append(converted)
                fetched.append(url)
                tvbox_imported.append({"url": url, "count": len(converted)})
                tvbox_skipped.extend(skipped)
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
                "tvbox_imported": tvbox_imported,
                "tvbox_skipped": tvbox_skipped,
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

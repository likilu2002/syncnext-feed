#!/usr/bin/env python3
import argparse
import json
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse, urlunparse
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
    url = iri_to_uri(normalize_config_url(url))
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 syncnext-personal-feed-updater/1.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(clean_json_text(response.read().decode("utf-8-sig", errors="replace")))


def clean_json_text(text):
    text = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return text.strip()


def normalize_config_url(url):
    if not isinstance(url, str):
        return ""
    url = url.strip()
    prefixes = [
        "https://wget.la/",
        "http://wget.la/",
        "https://gh.con.sh/",
        "https://github.moeyy.xyz/",
        "https://gh-proxy.com/",
    ]
    for prefix in prefixes:
        if url.startswith(prefix + "https://"):
            url = url[len(prefix) :]
            break

    parsed = urlparse(url)
    if parsed.netloc.lower() == "github.com" and "/blob/" in parsed.path:
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 5:
            owner, repo, _, branch = parts[:4]
            path = "/".join(parts[4:])
            return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
    return url


def iri_to_uri(url):
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    netloc = parsed.netloc.encode("idna").decode("ascii")
    path = quote(parsed.path, safe="/%:@")
    query = quote(parsed.query, safe="=&?/:+,%")
    fragment = quote(parsed.fragment, safe="")
    return urlunparse((parsed.scheme, netloc, path, parsed.params, query, fragment))


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
    parsed = urlparse(api)
    if parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return False
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


def tvbox_nested_urls(config, source_url):
    if not isinstance(config, dict):
        return []
    nested = []
    for entry in config.get("urls", []):
        if isinstance(entry, str):
            nested.append({"url": absolute_url(source_url, entry), "name": entry})
        elif isinstance(entry, dict) and entry.get("url"):
            nested.append(
                {
                    "url": absolute_url(source_url, entry.get("url")),
                    "name": entry.get("name") or entry.get("url"),
                }
            )
    return nested


def collect_tvbox_sources(root_url, max_nested=40):
    converted = []
    skipped = []
    fetched = []
    failed = []
    queue = [{"url": root_url, "depth": 0}]
    seen = set()

    while queue and len(fetched) < max_nested + 1:
        current = queue.pop(0)
        url = normalize_config_url(current["url"])
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            config = fetch_json(url)
            fetched.append(url)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            failed.append({"url": url, "error": str(exc)})
            continue

        items, skipped_items = tvbox_sites_to_syncnext(config, url)
        converted.extend(items)
        skipped.extend(skipped_items)

        if current["depth"] < 1:
            for nested in tvbox_nested_urls(config, url):
                if len(queue) + len(fetched) >= max_nested + 1:
                    break
                queue.append({"url": nested["url"], "depth": current["depth"] + 1})

    return converted, skipped, fetched, failed


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
            converted, skipped, tvbox_fetched, tvbox_failed = collect_tvbox_sources(
                url,
                max_nested=int(feed.get("max_nested", 40)),
            )
            groups.append(converted)
            fetched.extend(tvbox_fetched)
            failed.extend(tvbox_failed)
            tvbox_imported.append({"url": url, "count": len(converted), "configs": len(tvbox_fetched)})
            tvbox_skipped.extend(skipped)

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

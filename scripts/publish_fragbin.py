#!/usr/bin/env python3
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILE = ROOT / "public" / "sourcesv3.json"
CONFIG_FILE = ROOT / "private" / "fragbin.json"
SHORTLINK_FILE = ROOT / "public" / "shortlink.txt"


def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


def save_config(config):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def request_json(url, method="GET", payload=None):
    data = None
    headers = {"User-Agent": "syncnext-feed-publisher/1.0"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def shorten(url):
    services = [
        "https://is.gd/create.php?" + urlencode({"format": "simple", "url": url}),
        "https://tinyurl.com/api-create.php?" + urlencode({"url": url}),
    ]
    errors = []
    for api in services:
        try:
            request = Request(api, headers={"User-Agent": "syncnext-feed-publisher/1.0"})
            with urlopen(request, timeout=20) as response:
                short = response.read().decode("utf-8").strip()
            if short.startswith("https://"):
                return short
            errors.append(short)
        except (HTTPError, URLError, TimeoutError, RuntimeError, OSError) as exc:
            errors.append(str(exc))
    raise RuntimeError("; ".join(errors))


def publish():
    if not SOURCE_FILE.exists():
        raise FileNotFoundError(f"Missing {SOURCE_FILE}; run scripts/update_syncnext.py first.")

    config = load_config()
    content = SOURCE_FILE.read_text(encoding="utf-8")

    if config.get("id") and config.get("editKey"):
        result = request_json(
            f"https://fragbin.com/api/pastes/{config['id']}",
            method="PUT",
            payload={
                "editKey": config["editKey"],
                "title": "syncnext-sourcesv3.json",
                "content": content,
                "language": "json",
                "expiresAt": "never",
                "isPrivate": True,
            },
        )
        if not result.get("ok"):
            raise RuntimeError(json.dumps(result, ensure_ascii=False))
    else:
        result = request_json(
            "https://fragbin.com/api/pastes",
            method="POST",
            payload={
                "title": "syncnext-sourcesv3.json",
                "content": content,
                "language": "json",
                "expiresAt": "never",
                "isPrivate": True,
            },
        )
        config["id"] = result["id"]
        config["editKey"] = result["editKey"]

    config["raw_url"] = f"https://fragbin.com/r/{config['id']}"
    if not config.get("short_url"):
        try:
            config["short_url"] = shorten(config["raw_url"])
            config.pop("shorten_error", None)
        except (HTTPError, URLError, TimeoutError, RuntimeError, OSError) as exc:
            config["shorten_error"] = str(exc)

    save_config(config)
    SHORTLINK_FILE.write_text(
        "\n".join(line for line in [config.get("short_url", ""), config["raw_url"]] if line) + "\n",
        encoding="utf-8",
    )
    print("Raw URL:", config["raw_url"])
    if config.get("short_url"):
        print("Short URL:", config["short_url"])
    else:
        print("Short URL failed:", config.get("shorten_error", "unknown error"))


if __name__ == "__main__":
    publish()

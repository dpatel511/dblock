"""Check bundled recipes against upstream without downloading the databases.

For every release URL: the server must answer and report the recipe's size
(only 1 byte is requested). For Zenodo releases: the file's checksum in the
Zenodo API must match the recipe, and the record must still be the latest
version. Exits 1 if anything differs, 2 on a usage error.

    python scripts/check_recipes.py [RECIPE_DIR]
"""

from __future__ import annotations

import datetime
import json
import re
import sys
import tomllib
import urllib.request
from pathlib import Path

USER_AGENT = "dblock-recipe-check"


def _open(url: str, headers: dict[str, str]):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    return urllib.request.urlopen(request, timeout=60)


def served_size(url: str) -> int | None:
    with _open(url, {"Range": "bytes=0-0"}) as response:  # the body is never read
        content_range = response.headers.get("Content-Range", "")
        if "/" in content_range:
            return int(content_range.rsplit("/", 1)[1])
        if response.status == 200 and response.headers.get("Content-Length"):
            return int(response.headers["Content-Length"])
    return None


def zenodo_json(url: str) -> dict:
    with _open(url, {"Accept": "application/json"}) as response:
        return json.load(response)


def check_release(name: str, rel: dict) -> list[str]:
    problems = []
    label = f"{name}@{rel['version']}"
    for url in rel["urls"]:
        try:
            size = served_size(url)
        except Exception as exc:  # report every kind of failure and keep going
            problems.append(f"{label}: {url}: {exc}")
            continue
        if rel.get("size") and size != rel["size"]:
            problems.append(f"{label}: {url}: served size {size}, recipe size {rel['size']}")
        else:
            print(f"ok    {label}: {url} ({size} bytes)")
    match = re.search(r"zenodo\.org/api/records/(\d+)/files/([^/]+)/content", rel["urls"][0])
    if match:
        record_id, filename = match.groups()
        try:
            record = zenodo_json(f"https://zenodo.org/api/records/{record_id}")
            latest = zenodo_json(record["links"]["latest"])
        except Exception as exc:
            return problems + [f"{label}: Zenodo record {record_id}: {exc}"]
        upstream = next((f["checksum"] for f in record["files"] if f["key"] == filename), None)
        if upstream != rel.get("checksum"):
            problems.append(f"{label}: Zenodo checksum {upstream}, recipe checksum {rel.get('checksum')}")
        else:
            print(f"ok    {label}: Zenodo checksum {upstream}")
        if str(latest["id"]) != record_id:
            problems.append(f"{label}: Zenodo record {record_id} is not the latest version; latest is "
                            f"{latest['id']} (version {latest['metadata'].get('version')})")
    return problems


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[1] / "src" / "dblock" / "recipes"
    if not root.is_dir():
        print(f"error: recipe directory not found: {root}", file=sys.stderr)
        return 2
    print(f"checked {datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}")
    problems = []
    for path in sorted(root.glob("*.toml")):
        recipe = tomllib.loads(path.read_text(encoding="utf-8"))
        for rel in recipe["releases"]:
            problems += check_release(recipe["name"], rel)
    for problem in problems:
        print(f"PROBLEM {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

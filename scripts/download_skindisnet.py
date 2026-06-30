from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path


ARCHIVE_STATUS_URL = (
    "https://data.mendeley.com/api/datasets-v2/datasets/yj3md44hxg/zip?version=1"
)
DOWNLOAD_URL = "https://data.mendeley.com/public-api/zip/yj3md44hxg/download/1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default="data/datasets/skindisnet/yj3md44hxg-1.zip",
    )
    args = parser.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    with urllib.request.urlopen(ARCHIVE_STATUS_URL) as response:
        metadata = json.load(response)
    expected_size = int(metadata["size"])
    if out.exists() and out.stat().st_size == expected_size:
        print(f"Already downloaded: {out}")
        return 0

    request = urllib.request.Request(
        DOWNLOAD_URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://data.mendeley.com/datasets/yj3md44hxg/1",
        },
    )
    print(f"Downloading {expected_size / 1024**3:.2f} GiB to {out}")
    with urllib.request.urlopen(request) as response, out.open("wb") as target:
        while chunk := response.read(1024 * 1024):
            target.write(chunk)
    if out.stat().st_size != expected_size:
        raise SystemExit(
            f"Unexpected archive size: {out.stat().st_size}, expected {expected_size}"
        )
    print(f"Downloaded: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

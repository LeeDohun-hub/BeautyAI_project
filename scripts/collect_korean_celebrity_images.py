"""경로 A: 컨센서스/글로벌 라벨 → 네이버 이미지 검색으로 얼굴 이미지 수집.

라벨 소스(둘 다 지원):
  - data/manifests/korean_celebrity_pc_labels.csv (name,season,subtone,tier,...)
  - data/manifests/global_celebrity_pc_labels.csv (name,season,subseason,source,note)
이미지 소스: 네이버 이미지 검색 API (.env NAVER_CLIENT_ID/SECRET, 쇼핑과 동일 키).

출력(--tag 로 분기):
    data/datasets/<tag>_raw/<season>/<name>_<i>_<hash>.jpg
    data/manifests/<tag>_raw_manifest.csv       (image_path,season,partition) — 기존 파이프라인 호환
    data/manifests/<tag>_provenance.csv         (image_path,name,season,subtone,source_url,query)

주의: 웹 수집 이미지 = 초상권. 내부 R&D/도메인적응 용도. 얼굴크롭 단계가 비얼굴 거름.

실행:
    $env:NAVER_CLIENT_ID=...; $env:NAVER_CLIENT_SECRET=...
    python scripts/collect_korean_celebrity_images.py \
        --labels data/manifests/global_celebrity_pc_labels.csv --tag global --per-celeb 10
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import time
from pathlib import Path

import requests

# 정면·단독 얼굴 편향 쿼리(빈 접미 = 이름만; 한/영 혼합으로 글로벌 커버).
QUERY_SUFFIXES = ["", "얼굴", "face"]
MIN_SIDE = 400
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def naver_image_search(query: str, display: int) -> list[dict]:
    resp = requests.get(
        "https://openapi.naver.com/v1/search/image",
        headers={
            "X-Naver-Client-Id": os.environ["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": os.environ["NAVER_CLIENT_SECRET"],
        },
        params={"query": query, "display": display, "sort": "sim", "filter": "large"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("items", [])


def download(url: str) -> bytes | None:
    try:
        resp = requests.get(url, headers={"User-Agent": UA, "Referer": "https://search.naver.com/"}, timeout=20)
        resp.raise_for_status()
        if not resp.headers.get("Content-Type", "").startswith("image/"):
            return None
        return resp.content
    except requests.RequestException:
        return None


def read_labels(path: Path, tier: str) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            season = (row.get("season") or "").strip().lower()
            if season in ("", "conflict"):  # CONFLICT 행 제외
                continue
            row_tier = (row.get("tier") or "").strip()
            if tier == "consensus" and row_tier and row_tier != "consensus":
                continue
            row["_season"] = season
            row["_subtone"] = (row.get("subtone") or row.get("subseason") or "").strip()
            rows.append(row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="data/manifests/korean_celebrity_pc_labels.csv")
    ap.add_argument("--tag", default="korean_celebrity", help="출력 파일 접두")
    ap.add_argument("--tier", choices=["consensus", "all"], default="all")
    ap.add_argument("--per-celeb", type=int, default=12)
    ap.add_argument("--partition", default="train")
    args = ap.parse_args()

    labels_path = Path(args.labels)
    raw_root = Path(f"data/datasets/{args.tag}_raw")
    raw_manifest = Path(f"data/manifests/{args.tag}_raw_manifest.csv")
    provenance = Path(f"data/manifests/{args.tag}_provenance.csv")

    celebs = read_labels(labels_path, args.tier)
    print(f"라벨 {len(celebs)}명 (labels={labels_path.name}, tier={args.tier}, per-celeb={args.per_celeb})", flush=True)

    manifest_rows: list[tuple[str, str, str]] = []
    prov_rows: list[tuple[str, str, str, str, str, str]] = []
    seen_hashes: set[str] = set()
    counts: dict[str, int] = {}

    for idx, celeb in enumerate(celebs, 1):
        name = celeb["name"].strip()
        season = celeb["_season"]
        subtone = celeb["_subtone"]
        saved = 0
        seen_urls: set[str] = set()
        for suffix in QUERY_SUFFIXES:
            if saved >= args.per_celeb:
                break
            query = f"{name} {suffix}".strip()
            try:
                items = naver_image_search(query, display=20)
            except requests.RequestException as exc:
                print(f"  [search-fail] {query!r}: {exc}", flush=True)
                continue
            for it in items:
                if saved >= args.per_celeb:
                    break
                url = it.get("link", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                if int(it.get("sizewidth", 0)) < MIN_SIDE or int(it.get("sizeheight", 0)) < MIN_SIDE:
                    continue
                blob = download(url)
                if blob is None or len(blob) < 8000:
                    continue
                digest = hashlib.sha1(blob).hexdigest()
                if digest in seen_hashes:
                    continue
                seen_hashes.add(digest)
                safe = "".join(c for c in name if c not in '\\/:*?"<>|').strip()
                dest = raw_root / season / f"{safe}_{saved:02d}_{digest[:8]}.jpg"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(blob)
                manifest_rows.append((str(dest), season, args.partition))
                prov_rows.append((str(dest), name, season, subtone, url, query))
                saved += 1
            time.sleep(0.15)
        counts[season] = counts.get(season, 0) + saved
        if idx % 20 == 0 or saved == 0:
            print(f"  [{idx}/{len(celebs)}] {name} [{season}] {saved}장", flush=True)

    raw_manifest.parent.mkdir(parents=True, exist_ok=True)
    with raw_manifest.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["image_path", "season", "partition"])
        w.writerows(manifest_rows)
    with provenance.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["image_path", "name", "season", "subtone", "source_url", "query"])
        w.writerows(prov_rows)

    print(f"\n총 {len(manifest_rows)}장 저장. 계절별: {counts}", flush=True)
    print(f"매니페스트: {raw_manifest}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""아마존 ASIN 생존 검증 → 죽은 ASIN 블록리스트.

왜: Kaggle/HF(McAuley 2023) 카탈로그엔 이미 폐기된 ASIN이 많아(실측 매칭 표본의 ~45%),
그 dp 링크가 amazon "Page Not Found"(404)로 열린다. 사용자 원칙: 에러페이지 열리는 버튼은
내지 않는다. 검색(/s)은 amazon이 차단하지만 **상품페이지(/dp)는 접근 가능**(실측)하므로,
오프라인에서 /dp 를 HTTP 확인해 404를 블록리스트에 적는다. match_amazon 은 블록리스트 ASIN을
건너뛰고 살아있는 차선을 고른다.

상태 파일(재개용): data/manifests/amazon_asin_status.json  {asin: "ok"|"dead"}
블록리스트(매처가 읽음): data/manifests/amazon_dead_asins.txt

Usage:
  # 특정 브랜드의 카탈로그 ASIN 전부 검증(리포트된 버그 브랜드 우선 처리에 적합)
  python scripts/verify_amazon_asins.py --brands "bobbi brown" hera missha anessa curel
  # US 카탈로그 전체(느림, 재개형) / 명시 ASIN
  python scripts/verify_amazon_asins.py --catalog us
  python scripts/verify_amazon_asins.py --asins B008UBTCMI B0716YQJC2
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

import httpx

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))

_MANIFEST_DIR = _ROOT / "data" / "manifests"
_STATUS_PATH = _MANIFEST_DIR / "amazon_asin_status.json"
_DEAD_PATH = _MANIFEST_DIR / "amazon_dead_asins.txt"

_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]
_DEAD_MARKERS = ("page not found", "looking for something", "the web address you entered is not")


def _load_status() -> dict[str, str]:
    if _STATUS_PATH.exists():
        try:
            return json.loads(_STATUS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save(status: dict[str, str]) -> None:
    _STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    dead = sorted(a for a, s in status.items() if s == "dead")
    _DEAD_PATH.write_text("# amazon.com/dp 404(죽은 링크) ASIN. verify_amazon_asins.py 생성.\n"
                          + "\n".join(dead) + "\n", encoding="utf-8")


def _check(asin: str) -> str:
    """amazon.com/dp/{asin} 를 확인. 'ok' | 'dead' | 'unknown'(차단/에러: 재시도 여지 남김)."""
    url = f"https://www.amazon.com/dp/{asin}"
    try:
        r = httpx.get(url, headers={"User-Agent": random.choice(_UAS), "Accept-Language": "en-US,en;q=0.9"},
                      timeout=15, follow_redirects=True)
    except Exception:
        return "unknown"
    low = r.text.lower()
    if r.status_code == 404 or any(m in low for m in _DEAD_MARKERS):
        return "dead"
    if r.status_code == 200 and ("api-services-support@amazon" in low or "captcha" in low) and len(r.text) < 6000:
        return "unknown"  # 봇 차단 페이지 → 판정 보류
    if r.status_code == 200:
        return "ok"
    return "unknown"


def _collect_asins(args) -> list[str]:
    if args.asins:
        return list(dict.fromkeys(args.asins))
    from app.services import amazon_catalog as ac
    region = "jp" if args.catalog == "jp" else "us"
    items = list(ac._load_items(region))
    if args.brands:
        keys = [re.sub(r"[^a-z0-9]", "", b.lower()) for b in args.brands]
        items = [it for it in items if any(k in re.sub(r"[^a-z0-9]", "", it.brand_key) for k in keys)]
    # 리뷰수 많은(=추천에 뜰 확률 높은 대표) 상품부터 검증 → 부분 실행으로도 노출 버튼을 먼저 커버.
    items.sort(key=lambda it: it.reviews, reverse=True)
    return list(dict.fromkeys(it.asin for it in items))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", choices=["us", "jp"], default="us")
    ap.add_argument("--brands", nargs="*", help="이 브랜드들의 카탈로그 ASIN만 검증")
    ap.add_argument("--asins", nargs="*", help="명시 ASIN 목록")
    ap.add_argument("--delay", type=float, default=1.5, help="요청 간 딜레이(초)")
    ap.add_argument("--recheck", action="store_true", help="이미 판정된 ASIN도 다시 확인")
    args = ap.parse_args()

    _MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    status = _load_status()
    asins = _collect_asins(args)
    todo = [a for a in asins if args.recheck or a not in status]
    print(f"검증 대상 {len(asins)}개 중 {len(todo)}개 확인 (기존 판정 {len(status)}개)")

    ok = dead = unknown = 0
    for i, asin in enumerate(todo, 1):
        res = _check(asin)
        if res != "unknown":
            status[asin] = res
        ok += res == "ok"; dead += res == "dead"; unknown += res == "unknown"
        if i % 10 == 0 or res == "dead":
            print(f"  [{i}/{len(todo)}] {asin}: {res}  (ok {ok} / dead {dead} / unknown {unknown})")
        if i % 25 == 0:
            _save(status)
        time.sleep(args.delay + random.uniform(0, 1))
    _save(status)
    print(f"완료: ok {ok}, dead {dead}, unknown {unknown} -> {_DEAD_PATH.name} ({sum(1 for s in status.values() if s=='dead')} dead total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

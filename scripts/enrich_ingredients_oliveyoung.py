"""올리브영 상품정보제공고시에서 한글 전성분을 수집한다.

근거: 전자상거래 상품정보제공고시 + 화장품법에 따라 화장품은 '화장품법에 따라 기재해야
하는 모든 성분'을 상세페이지에 표시할 의무가 있다. 판매자 재량이 아니라 법정 항목이라
커버리지가 높다(바디 8건 표본 8/8 실측).

엔드포인트(상세 HTML 71KB 대신 고시 블록만 3KB):
    GET /store/goods/getGoodsArtcAjax.do?goodsNo={goodsNo}&itemNo=001

왜 필요한가: 상품명 기반 성분 검출은 케어 카테고리 273건 중 50건(18%)뿐이었다. 고시
전성분은 상품명에 안 적힌 성분까지 준다(아비브 핸드크림 → 판테놀·토코페롤).

Usage:
    python scripts/enrich_ingredients_oliveyoung.py                 # 전체(누적)
    python scripts/enrich_ingredients_oliveyoung.py --body-only     # 바디 카탈로그 goodsNo만
    python scripts/enrich_ingredients_oliveyoung.py --limit 50 --delay 1.0

출력: data/manifests/oliveyoung_kr_ingredients.csv (재실행 시 이어서 누적)
"""
from __future__ import annotations

import argparse
import csv
import io
import random
import re
import sys
import time
from pathlib import Path

# sys.stdout 을 TextIOWrapper 로 교체하면 이 모듈을 import 하는 쪽에서 이중 래핑이 되고
# 먼저 만든 래퍼가 GC 되며 버퍼를 닫는다. reconfigure 는 같은 객체를 바꿔서 안전하다.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.services.ingredient_aliases import detect_ingredients_ko  # noqa: E402

MANIFEST_DIR = PROJECT_ROOT / "data" / "manifests"
OUTPUT = MANIFEST_DIR / "oliveyoung_kr_ingredients.csv"
FIELDNAMES = ["goodsNo", "brandName", "goodsName", "ingredients_ko", "detected"]

ARTC_URL = "https://www.oliveyoung.co.kr/store/goods/getGoodsArtcAjax.do"
DETAIL_URL = "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do"

INGREDIENT_LABEL = "화장품법에 따라 기재해야 하는 모든 성분"
# 고시는 '라벨 줄 → 값 줄' 구조다. 다음 라벨을 만나면 값이 끝난 것.
NOTICE_LABELS = {
    "내용물의 용량 또는 중량", "제품 주요 사양", "사용기한(또는 개봉 후 사용기간)",
    "사용방법", "화장품제조업자,화장품책임판매업자 및 맞춤형화장품판매업자",
    "제조국", INGREDIENT_LABEL, "기능성 화장품 식품의약품안전처 심사필 여부",
    "사용할 때의 주의사항", "품질보증기준", "소비자상담 전화번호",
}
_TAG_RE = re.compile(r"<[^>]+>")


# 고시 성분란에 성분 대신 안내문만 넣은 상품이 있다("상세페이지참고", "제품 참조" 등).
# 이걸 전성분으로 저장하면 '성분 데이터 있음'으로 오인돼 strict 모드를 그냥 통과한다.
_PLACEHOLDER_RE = re.compile(
    r"^(?:상세\s*페이지\s*참고|상세페이지\s*참조|제품\s*(?:참조|참고|뒷면)|"
    r"별도\s*표기|용기\s*참조|해당\s*없음|기재\s*생략|-|\.)*$"
)


def parse_notice_ingredients(html: str) -> str:
    """고시 HTML에서 전성분 값만 뽑는다. 안내문 플레이스홀더는 빈 값으로 본다."""
    lines = [line.strip() for line in _TAG_RE.sub("\n", html).split("\n") if line.strip()]
    try:
        start = lines.index(INGREDIENT_LABEL)
    except ValueError:
        return ""
    collected = []
    for line in lines[start + 1:]:
        if line in NOTICE_LABELS:  # 다음 항목 시작 → 종료
            break
        collected.append(line)
    value = " ".join(collected).strip()
    compact = re.sub(r"\s+", "", value)
    # 길이로 자르면 안 된다 — '암모늄 알룸'(크리스탈 데오드란트)처럼 단일 성분 제품이 있다.
    # 안내문 패턴으로만 판정한다.
    if len(compact) < 4 or _PLACEHOLDER_RE.match(compact):
        return ""
    return value


def fetch_notice(session, goods_no: str, timeout: int = 20) -> str | None:
    try:
        response = session.get(
            ARTC_URL,
            params={"goodsNo": goods_no, "itemNo": "001"},
            headers={
                "referer": f"{DETAIL_URL}?goodsNo={goods_no}",
                "x-requested-with": "XMLHttpRequest",
            },
            impersonate="chrome120",
            timeout=timeout,
        )
    except Exception:
        return None
    if response.status_code != 200:
        return None
    return response.text


def load_targets(body_only: bool) -> list[dict]:
    """goodsNo 목록을 만든다. 바디 카탈로그 우선, 없으면 KR 전체 카탈로그."""
    targets: dict[str, dict] = {}
    if body_only:
        path = MANIFEST_DIR / "body_products.csv"
        if path.exists():
            with path.open(encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    if row.get("source") != "oliveyoung_kr":
                        continue
                    match = re.search(r"goodsNo=(\w+)", row.get("product_url") or "")
                    if match:
                        targets[match.group(1)] = {
                            "goodsNo": match.group(1),
                            "brandName": row.get("brand") or "",
                            "goodsName": row.get("name") or "",
                        }
        return list(targets.values())

    path = MANIFEST_DIR / "oliveyoung_kr_products.csv"
    if not path.exists():
        raise SystemExit(f"카탈로그가 없습니다: {path}")
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            goods_no = (row.get("goodsNo") or "").strip()
            if goods_no:
                targets[goods_no] = {
                    "goodsNo": goods_no,
                    "brandName": row.get("brandName") or "",
                    "goodsName": row.get("goodsName") or "",
                }
    return list(targets.values())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--body-only", action="store_true", help="바디 카탈로그의 KR 상품만")
    parser.add_argument("--limit", type=int, default=0, help="이번 실행에서 처리할 최대 건수(0=전부)")
    # 0.8s 로 돌렸더니 ~60건에서 IP 스로틀에 걸렸다(실측). 2.5s 는 그 아래로 안전한 값.
    parser.add_argument("--delay", type=float, default=2.5, help="요청 간 지연(초). 지터가 더해진다")
    parser.add_argument("--out", default=str(OUTPUT))
    args = parser.parse_args()

    from curl_cffi import requests as creq  # noqa: E402

    out_path = Path(args.out)
    done: dict[str, dict] = {}
    if out_path.exists():
        with out_path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                done[row["goodsNo"]] = row
        print(f"기존 {len(done)}건 로드(이어서 진행)")

    targets = [t for t in load_targets(args.body_only) if t["goodsNo"] not in done]
    if args.limit:
        targets = targets[:args.limit]
    print(f"대상 {len(targets)}건 · 지연 ~{args.delay}s")

    session = creq.Session()
    ok = empty = failed = 0
    consecutive_bad = 0
    try:
        for index, target in enumerate(targets, 1):
            # 스로틀링이 'HTTP 200 + 빈 고시'로 위장한다(실측). 빈 응답을 그대로
            # '성분 없음'으로 기록하면 조용히 거짓 데이터가 쌓이므로 반드시 재시도한다.
            blob = ""
            http_ok = False
            for attempt in range(3):
                html = fetch_notice(session, target["goodsNo"])
                if html is None:
                    time.sleep(5 * (attempt + 1))
                    continue
                http_ok = True
                blob = parse_notice_ingredients(html)
                if blob:
                    break
                time.sleep(5 * (attempt + 1))  # 빈 응답 → 스로틀 의심, 쉬고 재시도

            if not http_ok:
                failed += 1
                consecutive_bad += 1
            elif blob:
                ok += 1
                consecutive_bad = 0
            else:
                # 3회 재시도 후에도 비었으면 고시에 성분 항목이 실제로 없는 상품으로 본다.
                empty += 1
                consecutive_bad += 1

            if consecutive_bad >= 6:
                print("연속 실패/빈응답 6건(레이트리밋 추정). 여기까지 저장하고 중단합니다.")
                print("잠시 후 같은 명령을 다시 실행하면 이어서 진행됩니다.")
                break

            if http_ok:
                done[target["goodsNo"]] = {
                    **target,
                    "ingredients_ko": blob,
                    "detected": "|".join(detect_ingredients_ko(blob)),
                }
            if index % 25 == 0:
                print(f"  {index}/{len(targets)} · 전성분 {ok} · 없음 {empty} · 실패 {failed}", flush=True)
            time.sleep(args.delay + random.uniform(0, args.delay * 0.5))
    finally:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            for row in done.values():
                writer.writerow({k: row.get(k, "") for k in FIELDNAMES})
        print(f"\n저장: {out_path} (누적 {len(done)}건)")

    processed = ok + empty
    print(f"이번 실행: 전성분 확보 {ok} · 고시에 성분 없음 {empty} · 요청 실패 {failed}")
    if processed:
        print(f"확보율 {ok * 100 // processed}%")
    with_detect = sum(1 for r in done.values() if r.get("detected"))
    print(f"누적 중 표준 성분 검출: {with_detect}/{len(done)}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

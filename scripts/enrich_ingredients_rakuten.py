"""라쿠텐 itemCaption 에서 JP 상품의 전성분을 수집한다.

배경: 올리브영 상품정보제공고시는 KR 상품만 커버한다. 마츠키요·아마존JP 상품은 여전히
상품명 추론에 의존해서, 리전별 성분 보유율이 KR 61% vs JP 낮음으로 갈렸다.

일본도 화장품·의약외품 전성분 표시가 법정 의무라 판매자가 itemCaption 에 붙여둔다.
다만 **정식 `成分：` 표기는 일부만**이고(표본 8건 중 2건), 나머지는 광고 문구의 성분
언급이다("セラミド 保湿 ハリ"). 그걸 성분 데이터로 채택하면 상품명 추론과 다를 게 없으므로
**`成分：`/`全成分：` 라벨이 있는 블록만** 쓴다.

매칭 위험: 라쿠텐 검색은 다른 상품을 돌려줄 수 있다. 엉뚱한 상품의 전성분을 붙이는 건
성분이 없는 것보다 나쁘므로, 상품명 유사도(문자 바이그램 Jaccard)로 게이트를 건다.

Usage:
    python scripts/enrich_ingredients_rakuten.py --limit 30      # 시험
    python scripts/enrich_ingredients_rakuten.py                 # 전체(누적)

출력: data/manifests/rakuten_jp_ingredients.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import random
import re
import sys
import time
import unicodedata
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.services.ingredient_aliases import detect_ingredients_ja  # noqa: E402

MANIFEST_DIR = PROJECT_ROOT / "data" / "manifests"
OUTPUT = MANIFEST_DIR / "rakuten_jp_ingredients.csv"
FIELDNAMES = ["key", "source", "name", "matched_item", "score", "rakuten_url", "ingredients_ja", "detected"]

# 정식 전성분 라벨. 광고 문구의 성분 언급("高保湿成分 ワセリン配合")과 구분하는 신호다.
# 라쿠텐/마츠키요는 콜론이 아니라 브래킷 표기를 쓴다(실측):
#   原料・成分等【有効成分】ヘパリン類似物質…【その他の成分】精製水…
#   原料・成分等【成分】水、グリセリン…
_INGREDIENT_LABEL_RE = re.compile(
    r"原料・成分等|【\s*(?:全成分|成分|有効成分)\s*】|(?:全成分|成分)\s*[:：]"
)
# 전성분 뒤에 이어지는 '다른' 섹션 헤더에서 자른다. 【有効成分】/【その他の成分】은
# 성분 블록의 일부라 여기 넣으면 안 된다(초기 버전이 '【' 를 넣어 통째로 잘라먹었다).
_SECTION_BREAK_RE = re.compile(
    r"■|▼|◆|\[PR\]|内容量|使用方法|使用上の注意|ご使用方法|ご使用上|区分|原産国|製造国|"
    r"販売元|発売元|製造元|メーカー|広告文責|商品区分|お問い合わせ|保存方法|規格|"
    r"リニューアル|商品の特徴|用法|用量|効能|効果|お問合せ|賞味期限|使用期限"
)
# 일본어 매칭용 정규화. matsukiyo_matcher.normalize_key 는 장음(ー)을 지워 토큰을
# 쪼개버려서 'ボディローション' 이 조각난다. 여기서는 카타카나 블록 전체를 살린다.
_JP_KEEP_RE = re.compile(r"[^0-9a-z぀-ヿ一-鿿]+")
# 상품명의 마케팅 접두/접미(대괄호 프로모션, 【公式】 등)는 매칭을 방해한다.
_PROMO_RE = re.compile(r"[\[\【][^\]\】]{0,24}[\]\】]|\d+個セット|つめかえ用|詰め替え用|【並行輸入品】")

MATCH_THRESHOLD = 0.30


def jp_normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    text = _PROMO_RE.sub(" ", text)
    return _JP_KEEP_RE.sub(" ", text).strip()


def bigrams(text: str) -> set[str]:
    compact = text.replace(" ", "")
    return {compact[i:i + 2] for i in range(len(compact) - 1)}


def similarity(a: str, b: str) -> float:
    """문자 바이그램 Jaccard. 일본어는 띄어쓰기가 없어 토큰 분할이 불안정하다."""
    ba, bb = bigrams(jp_normalize(a)), bigrams(jp_normalize(b))
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / len(ba | bb)


def extract_ingredients_ja(caption: str) -> str:
    """itemCaption 에서 정식 전성분 블록만 뽑는다. 라벨이 없으면 빈 문자열."""
    if not caption:
        return ""
    match = _INGREDIENT_LABEL_RE.search(caption)
    if not match:
        return ""
    tail = caption[match.end():match.end() + 900]
    tail = _SECTION_BREAK_RE.split(tail)[0]
    return re.sub(r"\s+", " ", tail).strip()


def search_rakuten(client, keyword: str, hits: int = 3):
    import httpx

    endpoint, params = client._request_candidates(keyword, hits)[0]
    try:
        response = httpx.get(endpoint, params=params, headers=client._headers(), timeout=15.0)
    except Exception:
        return None
    if response.status_code != 200:
        return None if response.status_code in (429, 503) else []
    try:
        return response.json().get("Items") or []
    except Exception:
        return []


def load_targets() -> list[dict]:
    path = MANIFEST_DIR / "body_products.csv"
    if not path.exists():
        raise SystemExit(f"매니페스트가 없습니다: {path}\n먼저: python scripts/build_body_catalog.py")
    targets = []
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("region") != "jp":
                continue
            name = (row.get("name_ja") or row.get("name") or "").strip()
            if name:
                targets.append({"key": f"{row['source']}|{name[:120]}", "source": row["source"], "name": name})
    return targets


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="이번 실행 최대 건수(0=전부)")
    # 라쿠텐 API 는 초당 1요청 넘기면 429 를 준다(메모리 기록). 1.5s + 지터로 간다.
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--out", default=str(OUTPUT))
    args = parser.parse_args()

    from app.services.rakuten_client import RakutenClient

    client = RakutenClient()
    if not client.configured:
        raise SystemExit("RAKUTEN_APP_ID 가 설정돼 있지 않습니다(.env).")

    out_path = Path(args.out)
    done: dict[str, dict] = {}
    if out_path.exists():
        with out_path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                done[row["key"]] = row
        print(f"기존 {len(done)}건 로드(이어서 진행)")

    targets = [t for t in load_targets() if t["key"] not in done]
    if args.limit:
        targets = targets[:args.limit]
    print(f"JP 대상 {len(targets)}건 · 지연 ~{args.delay}s · 매칭 임계 {MATCH_THRESHOLD}")

    ok = no_label = no_match = failed = 0
    consecutive_failures = 0
    try:
        for index, target in enumerate(targets, 1):
            items = search_rakuten(client, jp_normalize(target["name"])[:100])
            if items is None:
                failed += 1
                consecutive_failures += 1
                if consecutive_failures >= 6:
                    print("연속 실패 6건(레이트리밋 추정). 여기까지 저장하고 중단합니다.")
                    break
                time.sleep(min(60, 5 * consecutive_failures))
                continue
            consecutive_failures = 0

            best = None
            for item in items:
                score = similarity(target["name"], str(item.get("itemName") or ""))
                if best is None or score > best[0]:
                    best = (score, item)
            if best is None or best[0] < MATCH_THRESHOLD:
                no_match += 1
                time.sleep(args.delay + random.uniform(0, args.delay * 0.4))
                continue

            score, item = best
            blob = extract_ingredients_ja(str(item.get("itemCaption") or ""))
            if blob:
                ok += 1
            else:
                no_label += 1
            # 성분이 없어도 라쿠텐 상품 URL은 저장한다 — JP 구매 버튼(직링크)에 쓰인다.
            done[target["key"]] = {
                "key": target["key"],
                "source": target["source"],
                "name": target["name"],
                "matched_item": str(item.get("itemName") or "")[:160],
                "score": f"{score:.3f}",
                "rakuten_url": str(item.get("itemUrl") or item.get("affiliateUrl") or "").strip(),
                "ingredients_ja": blob,
                "detected": "|".join(detect_ingredients_ja(blob)) if blob else "",
            }
            if index % 20 == 0:
                print(f"  {index}/{len(targets)} · 전성분 {ok} · 라벨없음 {no_label} · "
                      f"매칭실패 {no_match} · 요청실패 {failed}", flush=True)
            time.sleep(args.delay + random.uniform(0, args.delay * 0.4))
    finally:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            for row in done.values():
                writer.writerow({k: row.get(k, "") for k in FIELDNAMES})
        print(f"\n저장: {out_path} (누적 {len(done)}건)")

    processed = ok + no_label + no_match
    print(f"이번 실행: 전성분 확보 {ok} · 정식 라벨 없음 {no_label} · "
          f"상품 매칭 실패 {no_match} · 요청 실패 {failed}")
    if processed:
        print(f"확보율 {ok * 100 // processed}%")
    with_detect = sum(1 for r in done.values() if r.get("detected"))
    print(f"누적 중 표준 성분 검출: {with_detect}/{len(done)}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

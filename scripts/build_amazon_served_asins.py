"""추천에 '실제로 뜨는' 아마존 ASIN 목록을 만든다 → data/manifests/amazon_served_asins.txt

왜: HF(McAuley 2023) 카탈로그는 실측 사망률 48.5% 인데 전체 매칭의 80% 를 차지한다. 그래서
amazon_catalog 는 HF 행을 '개별 HTTP 검증(ok)된 ASIN' 만 링크로 쓰도록 게이트한다
(_UNTRUSTED_FILENAMES). 게이트를 걸면 검증되기 전까지 커버리지가 떨어지므로, 검증을 어디에
쓸지가 중요하다 — HF 11,593건 전수 검증은 몇 시간이 걸리지만, **실제로 버튼이 되는 ASIN은
643건뿐**이다(실측). 여기만 검증하면 같은 요청 수로 살아있는 버튼이 훨씬 많아진다.

방법: 신뢰도 게이트만 해제한 상태로 올리브영 글로벌 카탈로그 전 상품(한글명·영문명 각각)을
매칭해, 반환되는 ASIN 을 모은다. 나머지 게이트(브랜드/제형/희귀어)는 그대로 두므로 실제
서빙 결과와 같은 집합이 나온다.

Usage:
  python scripts/build_amazon_served_asins.py
  # 그 다음 검증(차단 회피를 위해 천천히):
  python scripts/verify_amazon_asins.py --served --workers 2 --delay 2
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))

from app.services import amazon_catalog as ac  # noqa: E402
from app.services.oliveyoung_catalog import _load_items as oy_items  # noqa: E402

_OUT = _ROOT / "data" / "manifests" / "amazon_served_asins.txt"


def main() -> int:
    ac._UNTRUSTED_FILENAMES = frozenset()  # 신뢰도 게이트만 해제(검증하면 쓸 수 있게 될 후보 탐색)
    ac.clear_cache()

    products = list(oy_items())
    print(f"올리브영 카탈로그 {len(products)}건으로 매칭 스캔(수 분 소요)…", flush=True)
    seen: set[str] = set()
    for index, item in enumerate(products, 1):
        for name in (item.name_kr, item.name_en):
            if not name:
                continue
            match = ac.match_amazon(item.brand, ac.amazon_search_query(item.brand, name))
            if match:
                seen.add(match.asin)
        if index % 500 == 0:
            print(f"  [{index}/{len(products)}] 누적 ASIN {len(seen)}", flush=True)

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text("\n".join(sorted(seen)) + "\n", encoding="utf-8")

    alive, dead = ac._verified_alive_asins(), ac._dead_asins()
    judged = sum(1 for a in seen if a in alive or a in dead)
    print(f"완료: {len(seen)}건 -> {_OUT}")
    print(f"  이미 판정됨 {judged} / 검증 필요 {len(seen) - judged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

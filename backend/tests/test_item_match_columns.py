"""아이템매칭 컬럼 분류·라쿠텐 재질의 회귀 테스트(2026-07-30 버그리포트).

사용자 관측:
- JP+라쿠텐 '베이스' 컬럼이 항상 비어 있었다(복합 색상어로 라쿠텐 0건).
- 립 컬럼에 헤어클립·메이크업 붓 세트가, 아이섀도우가 립 컬럼에 떴다.
- KR 아마존 탭에서 '…웜 아이보리' 파운데이션이 아이 컬럼에 꽂혔다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.routes import _broaden_keyword, _item_match_category


def _p(keyword: str = "", name: str = ""):
    return SimpleNamespace(keyword=keyword, name=name)


@pytest.mark.parametrize(
    "keyword,name,expected",
    [
        # 상품명이 카테고리를 분명히 말하면 상품명을 따른다(키워드는 '무엇을 검색했나'일 뿐).
        # 실측: 'ドライローズ リップ'(립) 검색이 물어온 아이섀도우가 립 컬럼에 떴다.
        ("ドライローズ リップ", "romnd ロムアンド ベターザンアイズ アイシャドウ 6.5g", "eye"),
        ("ドライローズ リップ", "ドド ブラシリキッドリップ R 01ドライローズレッド", "lip"),
        ("ダスティピンク チーク", "メイベリン グローキッサー チークブラッシュ 04 ダスティピンク", "blush"),
        # 키워드만 있고 상품명이 비면 키워드로 판정한다(_interleave_by_category 경로).
        ("ニュートラルピンク ファンデーション", "", "base"),
        ("말린 장미 젤네일", "", "nail"),
    ],
)
def test_category_prefers_product_name_over_search_keyword(keyword, name, expected):
    assert _item_match_category(_p(keyword, name)) == expected


@pytest.mark.parametrize(
    "name",
    [
        # 헤어 액세서리·화장 도구는 어느 컬럼에도 넣지 않는다(실측: 립/블러셔 컬럼에 카드로 떴다).
        "ヘアクリップ レディース 天然木 カメリア ドライローズ バレッタ",
        "メイクブラシ 5本セット 携帯用 ミラー付き フェイスパウダー チーク",
        "화장 파우치 대용량 여행용 블러셔 수납",
    ],
)
def test_excludes_tools_and_hair_accessories(name):
    assert _item_match_category(_p("", name)) is None


def test_brush_inside_product_name_is_not_a_tool():
    """'ブラシリキッドリップ'(브러시형 립)처럼 제품명에 붓이 들어간 화장품은 남겨야 한다.

    'ブラシ' 단독으로 잘라내면 이런 정상 상품이 함께 사라진다 — 세트/수량 표기와 함께일 때만
    도구로 본다.
    """
    assert _item_match_category(_p("", "パルガントン ブラシリキッドリップRM R01ドライローズレッド 2g 口紅")) == "lip"


def test_ivory_shade_is_not_eye_category():
    """'아이'를 부분문자열로 두면 '아이보리'(ivory)가 걸린다.

    실측: '바비브라운 … 파운데이션 SPF 20 W026 웜 아이보리' 가 아이 컬럼에 꽂혔다.
    """
    name = "바비브라운 스킨 롱웨어 플루이드 파우더 파운데이션 SPF 20 W026 웜 아이보리"
    assert _item_match_category(_p("", name)) == "base"
    # 진짜 아이 제품은 그대로 eye 로 남아야 한다.
    assert _item_match_category(_p("", "바비브라운 럭스 아이섀도우 2.5g")) == "eye"


# ── '컨실러 팔레트' 회귀 (2026-08-07 사용자 리포트) ────────────────────────────
# eye 정규식의 '팔레트'가 base 의 '컨실러'보다 먼저 검사돼, 컨실러 팔레트가 아이 컬럼에 떴다.
# 실측(카탈로그 9,706건): 국내몰 7 · 글로벌 3 · 아마존JP 6건.

@pytest.mark.parametrize(
    "name",
    [
        "어뮤즈 에어리 스팟 컨실러 팔레트",
        "데이지크 프로 컨실러 팔레트 2colors",
        "정샘물 아티스트 컨실러 팔레트 2종",
        "[NEW] 디어에이 퍼펙트 커버 컨실러 팔레트 퍼프 기획 3종",
        "[TIRTIR] MASK FIT CONCEALER PALETTE マスクフィットコンシーラーパレット #01",
        # '아이돌'이 '아이' 로 잡히던 건도 컨실러 우선 판정으로 함께 해결된다.
        "[NEW/24시간 밀착] 티핏 아이돌 커버 컨실러 6.5g 7colors",
    ],
)
def test_concealer_palette_is_base_not_eye(name):
    assert _item_match_category(_p("", name)) == "base"


def test_eyeshadow_palette_stays_eye():
    """컨실러를 앞세웠다고 진짜 아이섀도 팔레트까지 base 로 가면 안 된다."""
    assert _item_match_category(_p("", "앤드바이롬앤 멜로우 아이 팔레트 2.4g BR01 소프트 브라운")) == "eye"
    assert _item_match_category(_p("", "3CE 멀티 아이 컬러 팔레트")) == "eye"


# ── '아이' 부분문자열 오탐 (2026-08-07) ────────────────────────────────────────
# '아이'를 맨몸으로 두면 브랜드명과 눈가 스킨케어가 통째로 아이섀도우 칸에 들어온다.
# 실측: '아이'만으로 eye 가 된 376건 중 진짜 아이메이크업은 90건뿐이었다.

@pytest.mark.parametrize(
    "name,expected",
    [
        # 브랜드명 — 아이디얼포맨 76건, 아이오페 20건, 아이코닉 23건, 아이젠틀맨 11건, 아이소이 6건.
        ("아이디얼 포 맨 퍼펙트 탄력 로션 150mL", None),
        ("아이오페 맨 컴파운드 선스크린 50ml", None),
        ("아이코닉 코트니 케이블파우치", None),
        ("[시그니처] 아이젠틀맨 오드퍼퓸 50ml(3가지향)", None),
        ("아이소이 포맨 아쿠아 수딩 토너 150ml", None),
        # 눈가 '스킨케어' — 색조 아이템매칭 칸에 들어갈 물건이 아니다(아이크림 30 · 아이패치 20건).
        ("아비브 콜라겐 아이크림 부활초 튜브 30ml", None),
        ("헤이미쉬 불가리안 로즈 아이패치 60매", None),
        ("코스알엑스 어드벤스드 스네일 펩타이드 아이 크림", None),
        ("일리윤 젠틀 딥 립&아이리무버 140ml", "lip"),  # '립'이 있으니 립 칸이 맞다
        # 'ice' 계열.
        ("VT 크라이오 아이스 마스크 30매", None),
        ("히말라야 핑크솔트치약 아이스민트 100g", None),
        # 진짜 아이메이크업은 남는다.
        ("더페이스샵 디자이닝 아이브로우 01 라이트브라운", "eye"),
        ("[NEW컬러] 롬앤 베러 댄 아이즈", "eye"),
        ("바닐라코 하이퍼 홀로빔 아이 글리터 1.8g BL01 소다 팝", "eye"),
        ("헤라 아이 디자이너 펜슬 블랙", "eye"),
        ("페리페라 무드 인 쉐이드 아이스틱 (매트/펄 2type)", "eye"),
        ("홀리카홀리카 아이메탈글리터", "eye"),
        ("바닐라코 컬리 스튜디오 노글루 아이래쉬 01 올데이", "eye"),
    ],
)
def test_eye_requires_a_makeup_word_after_ai(name, expected):
    assert _item_match_category(_p("", name)) == expected


@pytest.mark.parametrize(
    "keyword,expected_first",
    [
        # 라쿠텐은 사실상 AND 매칭이라 복합 색상어가 0건이 된다 → 기본색만 남겨 재질의한다.
        ("ニュートラルピンク ファンデーション", "ピンク ファンデーション"),
        ("ライトクールベージュ ファンデーション", "ベージュ ファンデーション"),
        ("라이트 쿨 베이지 파운데이션", "베이지 파운데이션"),
    ],
)
def test_broaden_keyword_simplifies_compound_color(keyword, expected_first):
    candidates = _broaden_keyword(keyword)
    assert candidates and candidates[0] == expected_first
    # 마지막 후보는 카테고리어 단독(컬럼이 비지 않게 하는 최후 폴백).
    assert candidates[-1] == keyword.split()[-1]


def test_broaden_keyword_single_token_has_no_fallback():
    assert _broaden_keyword("ファンデーション") == []


# ── 주입 게이트 회귀 (2026-08-03 사용자 리포트) ─────────────────────────────────
# "한국 지역 + 모든 플랫폼 / 네이버 에서 네일 컬럼이 비어 있다."
# 원인: 빈 컬럼을 채우는 주입이 **올리브영·아마존 탭에서만** 돌았다. KR 네일 후보를 만들던
# 네이버 색상검색이 2026-07-31 종료돼 후보 소스가 사라졌는데, 채워줄 주입까지 탭에 막혀
# 이중 공백이었다(카탈로그엔 네일 96건 존재). 플랫폼 탭은 '어디서 사나' 필터지 컬럼을
# 비우는 장치가 아니다.

def test_injected_product_keeps_direct_link_and_gains_others(monkeypatch):
    """주입 상품에 다른 플랫폼 링크를 붙이되, 카탈로그 **직링크는 지켜야** 한다.

    그냥 resolve 를 돌리면 국내몰 직링크(goodsNo)가 검색 링크로 격하된다 — Cloudflare 때문에
    KR 국내몰은 검증이 불가해 resolve 가 검색 링크만 만들기 때문이다. 카탈로그가 확정해 준
    상품을 다시 추측으로 되돌리는 셈이라, 병합하되 직링크가 이기게 한다.
    """
    from app.api import routes

    direct = "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000251335"

    def _fake_resolve(product, region, **kwargs):
        # resolve 가 만드는 '추측' 링크들 — 올리브영은 검색 링크로 격하된 형태.
        product.platform_links = {
            "naver": "https://search.shopping.naver.com/search/all?query=x",
            "oliveyoung": "https://www.oliveyoung.co.kr/store/search/getSearchMain.do?query=x",
        }
        product.matched_platforms = sorted(product.platform_links)

    monkeypatch.setattr(routes, "resolve_product_platforms", _fake_resolve)

    item = SimpleNamespace(platform_links={"oliveyoung": direct}, matched_platforms=["oliveyoung"])
    routes._attach_links_keeping_direct(item, "kr")

    assert item.platform_links["oliveyoung"] == direct, "직링크가 검색 링크로 격하되면 안 된다"
    assert item.platform_links["naver"], "네이버 탭에서 걸러지지 않으려면 링크가 붙어야 한다"
    assert item.matched_platforms == ["naver", "oliveyoung"]

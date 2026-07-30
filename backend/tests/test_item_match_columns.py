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

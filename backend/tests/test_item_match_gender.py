"""성별 기반 아이템매칭 카테고리 분류/밸런싱 테스트.

여성=립/블러셔/아이/베이스/네일, 남성(Level 2)=베이스/브로우/컨실러/립밤.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.routes import _balance_item_categories, _item_match_category


def _p(keyword: str, name: str = "", score: float = 1.0):
    return SimpleNamespace(keyword=keyword, name=name, score=score)


@pytest.mark.parametrize(
    "keyword,expected",
    [
        ("남자 쿠션", "base"),
        ("남성 톤업크림", "base"),
        ("맨즈 비비크림", "base"),
        ("남자 아이브로우", "brow"),
        ("남성 눈썹 펜슬", "brow"),
        ("소프트 브라운 아이브로우", "brow"),
        ("남자 컨실러", "concealer"),
        ("남성 잡티 컨실러", "concealer"),
        ("남자 립밤", "lipbalm"),
        ("코랄 립", "lipbalm"),
    ],
)
def test_male_category_classification(keyword, expected):
    assert _item_match_category(_p(keyword), "male") == expected


def test_male_concealer_not_swallowed_by_base():
    # base 정규식이 concealer 를 포함하므로 컨실러가 base 로 새면 안 된다(우선순위 검증).
    assert _item_match_category(_p("남성 컨실러 파운데이션 커버"), "male") == "concealer"


@pytest.mark.parametrize(
    "name",
    [
        "퓨어 남자운동 소프트쿠션 운동화 225",  # 쿠션 신발
        "쿠션양말 남성 가는골지 3型",           # 쿠션 양말
        "남성 슬리퍼 쿠션",
        "방석 쿠션커버",
        "ナイキ 3足組ソックス メンズ Everyday Cushion",  # 일본어: 쿠션 양말
        "メンズ スニーカー クッション",                  # 일본어: 스니커
        "座布団 クッション",                             # 일본어: 방석
    ],
)
def test_non_cosmetic_junk_excluded(name):
    # '남자 쿠션' 검색이 물어오는 신발/양말/방석 등 잡화는 어느 컬럼에도 넣지 않는다(사용자 지적).
    assert _item_match_category(_p(name), "male") is None
    assert _item_match_category(_p(name), "female") is None


@pytest.mark.parametrize(
    "keyword,expected",
    [
        ("코랄 블러셔", "blush"),
        ("브라운 아이섀도우", "eye"),
        ("누드 립", "lip"),
        ("파운데이션", "base"),
        ("젤네일", "nail"),
    ],
)
def test_female_classification_unchanged(keyword, expected):
    assert _item_match_category(_p(keyword), "female") == expected


def test_male_balancing_excludes_color_categories():
    # 블러셔/아이/네일(색조)은 남성 결과에 남은 칸으로도 새면 안 된다.
    items = [
        _p("블러셔 코랄"), _p("아이섀도우 브라운"), _p("젤네일 로즈"),   # 색조(제외 대상)
        _p("남자 쿠션"), _p("남자 아이브로우"), _p("남자 컨실러"), _p("남자 립밤"),
    ]
    selected = _balance_item_categories(items, limit=10, per_category=2, gender="male")
    cats = {_item_match_category(x, "male") for x in selected}
    assert cats == {"base", "brow", "concealer", "lipbalm"}
    assert not (cats & {"blush", "eye", "nail"})


def test_female_balancing_still_fills_five_columns():
    items = [
        _p("누드 립"), _p("코랄 블러셔"), _p("브라운 아이섀도우"),
        _p("파운데이션 쿠션"), _p("젤네일 로즈"),
    ]
    selected = _balance_item_categories(items, limit=10, per_category=2, gender="female")
    cats = {_item_match_category(x, "female") for x in selected}
    assert cats == {"lip", "blush", "eye", "base", "nail"}


# ── JP 남성: 글로벌몰 남성 상품 주입 ─────────────────────────────────────────

import csv  # noqa: E402
from pathlib import Path  # noqa: E402

import app.services.oliveyoung_catalog as oc  # noqa: E402
from app.api.routes import _inject_male_global_products  # noqa: E402

_MALE_CAT_HEADER = ["prdtNo", "prdtNameEn", "brandName", "korPrdtName", "gdsCd", "sellStatCode", "stockQty", "saleAmt"]
_MALE_CAT_ROWS = [
    ("M_CU", "Dashu Mens Cover Cushion", "DASHU", "다슈 맨즈 커버 쿠션", "1", "10", "5", "18.00"),
    ("M_BR", "Dashu Mens Eyebrow Pencil", "DASHU", "다슈 맨즈 아이브로우 펜슬", "2", "10", "5", "9.00"),
    ("M_CO", "Jungsaemmool Men Concealer", "JUNGSAEMMOOL", "정샘물 맨 다크존 컨실러", "3", "10", "5", "16.00"),
    ("M_LB", "Dashu Mens Color Lip Balm", "DASHU", "다슈 맨즈 컬러 립밤", "4", "10", "5", "12.00"),
    ("W_TINT", "Romand Juicy Tint", "rom&nd", "롬앤 쥬시 래스팅 틴트", "5", "10", "5", "8.00"),  # 여성(남성신호 없음) → 제외
]


def test_inject_male_global_products(monkeypatch, tmp_path):
    path = tmp_path / "oliveyoung_global_products.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(_MALE_CAT_HEADER)
        w.writerows(_MALE_CAT_ROWS)
    monkeypatch.setattr(oc, "_catalog_path", lambda: path)
    oc.clear_cache()

    products: list = []
    _inject_male_global_products(products)
    oc.clear_cache()

    # 남성 4개 카테고리가 채워지고, 각 카드에 올리브영 글로벌 직링크가 붙는다.
    cats = {_item_match_category(p, "male") for p in products}
    assert cats == {"base", "brow", "concealer", "lipbalm"}
    assert all("oliveyoung" in (p.platform_links or {}) for p in products)
    assert all("global.oliveyoung.com/product/detail" in p.platform_links["oliveyoung"] for p in products)
    assert all(p.source == "oliveyoung_global" for p in products)
    # 여성 상품(롬앤 틴트)은 남성 신호가 없어 주입되지 않는다.
    assert not any("롬앤" in p.name for p in products)
    # USD→JPY 근사 변환(18달러 → 2700엔 근처).
    base = next(p for p in products if _item_match_category(p, "male") == "base")
    assert base.price > 1000


# ── KR 남성: 국내몰 남성 상품 주입 (2026-08-07 사용자 리포트) ─────────────────
# KR 남성 카드 버튼이 **글로벌몰**(global.oliveyoung.com)로 나갔다. 한국 사용자를 해외몰로
# 보내는 셈이라, 지역별로 카탈로그를 갈라 KR 은 국내몰 goodsNo 직링크를 쓴다.

import app.services.oliveyoung_kr_search as oks  # noqa: E402
from app.api.routes import _inject_male_kr_products  # noqa: E402

_KR_CAT_HEADER = ["goodsNo", "brandName", "goodsName", "soldOut", "imageUrl"]
_KR_CAT_ROWS = [
    ("A0001", "다슈", "다슈 맨즈 퍼펙트 커버 컨실러", "N", "https://img/1.jpg"),
    ("A0002", "다슈", "다슈 맨즈 굿 룩스 아이브로우 펜슬 블랙", "N", "https://img/2.jpg"),
    ("A0003", "비레디", "[맨즈 1위 쿠션] 비레디 임수빈 PICK 블루 쿠션", "N", "https://img/3.jpg"),
    ("A0004", "포맨트", "포맨트 히든 립밤 3.6g 포맨", "N", "https://img/4.jpg"),
    ("A0005", "롬앤", "롬앤 쥬시 래스팅 틴트", "N", ""),          # 여성 → 제외
    ("A0006", "다슈", "다슈 맨즈 커버 쿠션", "Y", ""),             # 품절 → 제외
    # 잡화: '쿠션'+'남자'로 잡히지만 화장품이 아니다(실측으로 베이스 컬럼에 떴다).
    ("A0007", "닥터숄", "닥터숄 발뒤꿈치 쿠션 기능성 인솔 남자용 / 여자용", "N", ""),
]


def test_inject_male_kr_products_uses_domestic_links(monkeypatch, tmp_path):
    path = tmp_path / "oliveyoung_kr_products.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(_KR_CAT_HEADER)
        w.writerows(_KR_CAT_ROWS)
    monkeypatch.setattr(oks, "_kr_catalog_path", lambda: path)
    oks.clear_kr_catalog_cache()

    products: list = []
    _inject_male_kr_products(products)
    oks.clear_kr_catalog_cache()

    cats = {_item_match_category(p, "male") for p in products}
    assert cats == {"base", "brow", "concealer", "lipbalm"}
    # 핵심: 국내몰 goodsNo 직링크여야 한다(글로벌몰이면 한국 사용자가 해외몰로 간다).
    for p in products:
        link = (p.platform_links or {})["oliveyoung"]
        assert "oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=" in link
        assert "global.oliveyoung.com" not in link
    assert all(p.source == "oliveyoung_kr" for p in products)
    assert not any("롬앤" in p.name for p in products)      # 여성 상품
    assert not any("A0006" in p.id for p in products)       # 품절
    assert not any("닥터숄" in p.brand for p in products)   # 인솔(잡화)


def test_verify_rakuten_adds_direct_link_only_when_found():
    # 라쿠텐 API 검증: 브랜드 일치 리스팅이 있으면 직링크, 없으면 라쿠텐 버튼 안 붙음(오탐 방지).
    from app.api.routes import _verify_rakuten_for_global

    class _FakeClient:
        configured = True
        def search(self, query, hits=3):
            if "dashu" in query.lower() or "ダシュ" in query:
                return [SimpleNamespace(brand="DASHU", name="ダシュ メンズ BB", product_url="https://item.rakuten.co.jp/x/")]
            return []

    on = SimpleNamespace(brand="ダシュ", name="DASHU メンズBBローション", source="oliveyoung_global",
                         platform_links={"oliveyoung": "oy://d"}, matched_platforms=["oliveyoung"])
    off = SimpleNamespace(brand="オブジェ", name="OBJET メンズリップ", source="oliveyoung_global",
                          platform_links={"oliveyoung": "oy://o"}, matched_platforms=["oliveyoung"])
    _verify_rakuten_for_global([on, off], _FakeClient())
    assert on.platform_links.get("rakuten") == "https://item.rakuten.co.jp/x/"
    assert "rakuten" not in off.platform_links  # 라쿠텐에 없으면 버튼 없음

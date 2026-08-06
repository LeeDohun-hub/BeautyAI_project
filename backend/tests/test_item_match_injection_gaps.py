"""아이템매칭에서 컬럼이 비는 두 구멍에 대한 회귀 테스트(2026-08-06 사용자 리포트).

배경
  KR 의 라이브 후보 소스는 네이버 색상검색이었는데 2026-07-31 에 API 가 종료돼 0건이다
  (200 OK + 빈 결과). 그래서 KR 은 카탈로그 주입이 사실상 유일한 후보 공급원인데,
  그 주입이 두 군데서 막혀 있었다.

  1) 남성: 주입 블록 전체가 `gender != "male"` 로 막혀 있었고, 남성 전용 주입기는
     `region == "jp"` 전용이었다 → KR 남성은 주입이 하나도 없어 아이브로우·컨실러가 빈다.
  2) 여성: DB 폴백(영문명·이미지 없음) 2장이 컬럼을 '채워진' 것으로 만들어 주입이 안 돈다
     → 블러셔가 'Dandelion Baby-Pink Blush'(Benefit) 같은 영문 카드로만 찬다.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.api.routes import (
    _catalog_price,
    _item_match_category,
    _thin_item_categories,
    _USD_TO_JPY,
    _USD_TO_KRW,
)


def _p(name: str, source: str = "rakuten", keyword: str = ""):
    return SimpleNamespace(name=name, keyword=keyword, source=source)


class TestThinColumnsIgnoreDbFallback:
    """DB 폴백만 있는 컬럼은 '비어 있음'으로 봐야 주입이 돈다."""

    def test_db_only_column_is_still_thin(self):
        # 실측 사례: 블러셔 컬럼이 Benefit 영문 카드 2장으로 차서 주입이 건너뛰어졌다.
        products = [
            _p("Dandelion Baby-Pink Blush", source="database"),
            _p("Mini Dandelion Baby-Pink Blush", source="database"),
        ]
        assert "blush" in _thin_item_categories(products, "female")

    def test_live_products_do_fill_a_column(self):
        products = [
            _p("에뛰드 러블리쿠키 블러셔 코랄"),
            _p("클리오 프리즘 에어 블러셔 핑크"),
        ]
        assert "blush" not in _thin_item_categories(products, "female")

    def test_mixed_counts_only_live(self):
        products = [
            _p("에뛰드 러블리쿠키 블러셔 코랄"),
            _p("Dandelion Baby-Pink Blush", source="database"),
        ]
        # 라이브 1건 + DB 1건 = 유효 1건 < minimum(2) → 여전히 thin
        assert "blush" in _thin_item_categories(products, "female")

    def test_male_columns_use_male_categories(self):
        products = [_p("다슈 맨즈 퍼펙트 커버 컨실러")]
        thin = _thin_item_categories(products, "male")
        # 남성 컬럼 집합으로 판정돼야 한다(여성 패턴이면 brow/concealer/lipbalm 이 안 나온다).
        assert {"brow", "lipbalm", "base"} <= thin


class TestMaleCatalogClassification:
    """주입할 남성 카탈로그 상품이 남성 컬럼으로 분류되는지."""

    def test_korean_male_names_map_to_male_columns(self):
        cases = {
            "다슈 맨즈 퍼펙트 커버 컨실러": "concealer",
            "아이디얼포맨 베러톤 아이브로우": "brow",
            "YNM 맨즈 비타 생기 립밤 3g": "lipbalm",
            "다슈 맨즈 아쿠아 톤업 비비로션 40ml": "base",
        }
        for name, expected in cases.items():
            assert _item_match_category(SimpleNamespace(keyword="", name=name), "male") == expected

    def test_brow_knife_is_not_a_cosmetic(self):
        # '아이디얼포맨 투인원 눈썹칼'은 도구다 — 컬럼에 들어가면 안 된다.
        assert _item_match_category(SimpleNamespace(keyword="", name="아이디얼포맨 투인원 눈썹칼 2개"), "male") is None


class TestNonCosmeticFalsePositives:
    """잡화 배제 규칙이 진짜 화장품을 지우고 있었다.

    실측(글로벌 카탈로그 3,374건): 배제 85건 중 **82건이 오탐**이었다.
      러그 43건 — 브랜드 '컬러그램' 안의 부분문자열
      매트 35건 — matte 화장품(쿠션/프라이머/왁스)
      지갑·이어폰·헤어핀 4건 — '(+멜론동전지갑)' 같은 사은품 표기
    """

    def test_matte_cosmetics_survive(self):
        for name in (
            "라네즈 네오 쿠션 매트 15g",
            "아누아 제로캐스트 포어 블러링 매트 프라이머 선젤 50ml",
            "다슈 맨즈 아쿠아 매트 비비 쿠션(리필용)",
        ):
            assert _item_match_category(SimpleNamespace(keyword="", name=name), "female") == "base", name

    def test_brand_containing_rug_substring_survives(self):
        # '컬러그램' ⊃ '러그'
        assert _item_match_category(
            SimpleNamespace(keyword="", name="컬러그램 음영 창조 라이너"), "female"
        ) == "eye"

    def test_freebie_does_not_delete_the_product(self):
        cases = [
            ("퓌 글로이 스무디 틴티드 립밤 9.5g GN01 구아바 크러쉬 기획 (+ 멜론동전지갑)", "lip"),
            ("에뛰드 마이 쁘띠 팔레트 6.9g 02 코랄 기획 (+미니 이어폰)", "eye"),
        ]
        for name, expected in cases:
            assert _item_match_category(SimpleNamespace(keyword="", name=name), "female") == expected, name

    def test_freebie_does_not_decide_the_category(self):
        # 본품은 스킨케어인데 덤이 립밤이라고 립 컬럼에 가면 안 된다.
        assert _item_match_category(
            SimpleNamespace(keyword="", name="아누아 어성초 토너 250ml 기획 (+미니 립밤)"), "female"
        ) != "lip"

    def test_real_household_goods_still_excluded(self):
        for name in ("요가매트 논슬립 6mm", "メイクブラシ 5本セット", "아이디얼포맨 투인원 눈썹칼 2개"):
            assert _item_match_category(SimpleNamespace(keyword="", name=name), "female") is None, name


class TestKoreanCategoryWords:
    """한글 카테고리어가 빠져 있어 한국어명 상품이 통째로 미분류였다.

    실측(글로벌 카탈로그 3,374건): 파우더 47 · 팔레트 24 · 마스카라 24 · 라이너 23 ·
    프라이머 23 · 쉐딩 17 · 컨실러 17 · 하이라이터 16 · 글로스 13건이 어느 컬럼에도 못 들어갔다.
    KR 은 네이버 API 종료 뒤 한국어명 카탈로그가 사실상 유일한 후보라 그대로 빈 컬럼이 된다.
    """

    def test_korean_eye_words(self):
        for name in (
            "페리페라 올테이크무드팔레트 5.5g 001",
            "에뛰드 컬 픽스 마스카라 미니 4g 01 블랙",
            "컬러그램 음영 창조 라이너",
        ):
            assert _item_match_category(SimpleNamespace(keyword="", name=name), "female") == "eye", name

    def test_korean_base_words(self):
        for name in (
            "에뛰드 피지쏙 젤리 파우더 8g",
            "바닐라코 프라임 프라이머 피니쉬 파우더 12g",
            "에스쁘아 스트로빙 하이라이터 8g 1호 비너스",
        ):
            assert _item_match_category(SimpleNamespace(keyword="", name=name), "female") == "base", name

    def test_korean_lip_word_without_lip_token(self):
        assert _item_match_category(
            SimpleNamespace(keyword="", name="에뛰드 글레이즈 플럼프 글로스 01 스파클링 블루"), "female"
        ) == "lip"


class TestCatalogPriceCurrency:
    """글로벌몰 USD 가격을 지역 통화로 옮긴다. KR 에 엔화 환산가를 쓰면 9배 작게 나온다."""

    def test_jp_uses_yen(self):
        assert _catalog_price(10.0, "jp") == round(10.0 * _USD_TO_JPY)

    def test_kr_uses_won(self):
        assert _catalog_price(10.0, "kr") == round(10.0 * _USD_TO_KRW)

    def test_kr_is_not_yen(self):
        assert _catalog_price(10.0, "kr") != _catalog_price(10.0, "jp")

"""상담 챗봇의 카탈로그 갈래 — 상품명 조회와 대체 상품 추천(2026-08-10).

두 질문은 LLM 이 아니라 DB 가 답해야 한다. 모델이 문장을 지어내면 **없는 상품을 있다고**
말하게 되고, 상담 오답과 달리 재고 오답은 사용자를 매장까지 헛걸음시킨다.
그래서 여기서 보는 것은 두 가지다:
  1. 의도 판별이 **보수적인가** — 일반 성분·루틴 질문을 조회로 오인하면 상담이 통째로 망가진다.
  2. 못 찾았을 때 **못 찾았다고 말하는가** — 비슷한 걸 아무거나 내밀지 않는다.
"""

from __future__ import annotations

import re

import pytest

from app.services import chat_catalog_answers as catalog

HANGUL = re.compile(r"[가-힣]")


# ── 의도 판별 ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("‘코스알엑스 스네일 에센스’ 라는 상품명 조회가 되나요?", "코스알엑스 스네일 에센스"),
        ("라운드랩 자작나무 수분크림이라는 제품 있나요?", "라운드랩 자작나무 수분크림"),
        ("상품명은 numbuzin No.3 인데 취급하나요?", "numbuzin No.3"),
        ("「メラノCC」という商品はありますか？", "メラノCC"),
    ],
)
def test_extracts_product_name(message, expected):
    assert catalog.extract_product_query(message) == expected


@pytest.mark.parametrize(
    "message",
    [
        "나이아신아마이드는 언제 쓰면 좋을까요?",
        "레티놀이랑 AHA 같이 써도 되나요?",
        "모공 관리 루틴 알려주세요",
        # 조회 의도어가 있어도 이름이 특정되지 않으면 받지 않는다.
        "이런 제품 찾을 수 있나요?",
        "",
    ],
)
def test_does_not_hijack_normal_questions(message):
    assert catalog.extract_product_query(message) is None


@pytest.mark.parametrize(
    "message",
    [
        "매장에 내가 고른 상품이 없다는데, 다른 추천 상품 있을까요?",
        "그거 품절이래요. 비슷한 제품 알려주세요",
        "在庫がないと言われました。他のおすすめはありますか？",
    ],
)
def test_detects_alternative_request(message):
    assert catalog.is_alternative_request(message) is True


def test_alternative_request_beats_lookup_when_both_appear():
    """'그 상품 없대요, 다른 거 있나요?' 의 정답은 '있다/없다'가 아니라 대체 상품이다."""
    message = "‘설화수 자음생크림’ 이라는 상품이 매장에 없다는데 다른 추천 있을까요?"
    assert catalog.is_alternative_request(message) is True


# ── 매칭 ────────────────────────────────────────────────────────────────────

class _FakeBrand:
    def __init__(self, name):
        self.name = name


class _FakeProduct:
    def __init__(self, pid, brand, name, category="serum", rating=4.5):
        self.id = pid
        self.brand = _FakeBrand(brand)
        self.name = name
        self.category = category
        self.avg_rating = rating


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def options(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows=()):
        self._rows = list(rows)
        self.added = []

    def query(self, *_args, **_kwargs):
        return _FakeQuery(self._rows)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        pass


PRODUCTS = [
    _FakeProduct(1, "COSRX", "Advanced Snail 96 Mucin Power Essence 100ml"),
    _FakeProduct(2, "numbuzin", "No.3 Skin Softening Serum"),
    _FakeProduct(3, "Round Lab", "1025 Dokdo Toner", category="toner"),
]


def test_finds_product_by_partial_name():
    hits = catalog.find_products(_FakeSession(PRODUCTS), "COSRX 스네일 96 에센스")
    assert hits and hits[0].id == 1


def test_finds_product_ignoring_spacing_and_volume():
    hits = catalog.find_products(_FakeSession(PRODUCTS), "advancedsnail96mucinpoweressence")
    assert hits and hits[0].id == 1


def test_unknown_product_is_reported_as_not_found():
    """카탈로그에 없으면 '못 찾았다'고 말해야 한다 — 아무거나 대신 내밀지 않는다."""
    result = catalog.answer_product_lookup(_FakeSession(PRODUCTS), "존재하지않는브랜드 크림")
    assert "찾지 못했" in result.answer
    for product in PRODUCTS:
        assert product.name not in result.answer


def test_found_answer_lists_the_product():
    result = catalog.answer_product_lookup(_FakeSession(PRODUCTS), "1025 Dokdo Toner")
    assert "1025 Dokdo Toner" in result.answer
    assert "Round Lab" in result.answer


# ── 표기 ────────────────────────────────────────────────────────────────────

def test_brand_is_not_printed_twice():
    """카탈로그 상당수가 상품명 안에 브랜드를 품고 있다(실측: '라운드랩 … 라운드랩 1025 …')."""
    rows = [_FakeProduct(9, "라운드랩", "라운드랩 [대용량] 1025 독도 로션 400ml", category="body.lotion")]
    result = catalog.answer_product_lookup(_FakeSession(rows), "라운드랩 1025 독도 로션")
    assert result.answer.count("라운드랩") == 2, result.answer  # 질의 1회 + 상품명 1회


def test_internal_category_key_is_not_shown_raw():
    """category 는 'body.lotion' 같은 내부 키다 — 화면에 코드가 나가면 안 된다."""
    rows = [_FakeProduct(9, "Round Lab", "1025 Dokdo Lotion", category="body.lotion")]
    result = catalog.answer_product_lookup(_FakeSession(rows), "1025 Dokdo Lotion")
    assert "body.lotion" not in result.answer
    assert "바디로션" in result.answer


def test_unknown_category_is_hidden_rather_than_guessed():
    rows = [_FakeProduct(9, "Round Lab", "1025 Dokdo Something", category="weird.internal.key")]
    result = catalog.answer_product_lookup(_FakeSession(rows), "1025 Dokdo Something")
    assert "weird.internal.key" not in result.answer
    assert "()" not in result.answer


def test_category_label_tables_cover_the_same_keys():
    assert set(catalog._CATEGORY_LABELS["ko"]) == set(catalog._CATEGORY_LABELS["ja"])


@pytest.mark.parametrize("text", list(catalog._CATEGORY_LABELS["ja"].values()))
def test_japanese_category_labels_have_no_korean(text):
    assert not HANGUL.search(text), f"일본어 카테고리 라벨에 한국어가 남아 있습니다: {text}"


# ── 일본어 ──────────────────────────────────────────────────────────────────

def test_text_tables_cover_the_same_keys():
    """한쪽만 늘면 그 문장에서 일본어 모드에 한국어가 샌다(이 저장소의 반복 사고 유형)."""
    assert set(catalog._TEXT["ko"]) == set(catalog._TEXT["ja"])


@pytest.mark.parametrize("text", list(catalog._TEXT["ja"].values()))
def test_japanese_table_has_no_korean(text):
    assert not HANGUL.search(text), f"일본어 표에 한국어가 남아 있습니다: {text}"


def test_japanese_lookup_answer_has_no_korean():
    result = catalog.answer_product_lookup(_FakeSession(PRODUCTS), "1025 Dokdo Toner", lang="ja")
    assert not HANGUL.search(result.answer), result.answer


def test_japanese_not_found_answer_has_no_korean():
    result = catalog.answer_product_lookup(_FakeSession([]), "存在しない商品", lang="ja")
    assert not HANGUL.search(result.answer), result.answer


# ── 대체 추천 ───────────────────────────────────────────────────────────────

def test_alternatives_without_analysis_asks_for_analysis_first():
    """피부 점수가 없으면 성분 기준을 세울 수 없다 — 지어내지 말고 분석을 먼저 권한다."""
    result = catalog.answer_alternatives(_FakeSession([]), None)
    assert "피부 분석" in result.answer


def test_alternatives_without_analysis_has_no_korean_in_japanese():
    result = catalog.answer_alternatives(_FakeSession([]), None, lang="ja")
    assert not HANGUL.search(result.answer), result.answer


# ── 라우팅 ──────────────────────────────────────────────────────────────────

def test_normal_question_falls_through_to_general_consult():
    assert catalog.answer_catalog_question(_FakeSession(PRODUCTS), "레티놀 사용법 알려주세요") is None

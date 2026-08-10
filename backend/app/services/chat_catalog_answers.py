"""상담 챗봇의 '카탈로그' 갈래 — 상품명 조회와 대체 상품 추천.

왜 LLM 보다 **먼저** 가로채는가
  두 질문은 성분·루틴 상담과 성격이 다르다. 둘 다 "우리 카탈로그에 무엇이 있는가"를 묻는
  사실 질문이라, 모델이 문장을 지어내면 **없는 상품을 있다고 답하게 된다.** 상담 오답은
  다시 물으면 되지만 재고 오답은 사용자를 매장까지 헛걸음시킨다. 그래서 이 갈래는
  llm_consult 를 타지 않고 DB 조회 결과만으로 답한다.

문장 관리 방식
  한국어·일본어 문장은 모듈 상수에 **쌍으로** 둔다(skin_analyzer._confidence_notes 와 같은 방식).
  함수 안에 한국어 리터럴을 남기지 않아야 한쪽만 늘어나는 사고가 구조적으로 막힌다 —
  이 저장소에서 반복된 사고 유형이다(tests/test_assembled_sentence_inventory.py 참고).
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session, selectinload

from app.models import Ingredient, Product, ProductIngredient
from app.schemas.api import ChatResponse, SkinScores, SurveyInput

# 조회 결과로 보여줄 상품 수. 더 늘리면 상담 답변이 다시 '스크롤 벽'이 된다.
_MAX_HITS = 4
_MAX_ALTERNATIVES = 4

# 상품명이 이 길이보다 짧으면 조회로 보지 않는다 — '이 제품 어때요?' 같은 지시대명사가
# 상품명으로 잡혀 카탈로그 전체와 매칭되는 것을 막는다.
_MIN_QUERY_LEN = 2

# 상품명이 따옴표 안에 있으면 그게 가장 확실한 신호다.
_QUOTED = re.compile(r"[\"'‘“「『]\s*(?P<name>[^\"'’”」』]{2,80})\s*[\"'’”」』]")

# "OO 라는 상품명" / "OO という商品" — 조회 질문의 표준형.
# ⚠ 마침표를 제외하면 안 된다 — 'No.3', 'pH 5.5' 처럼 상품명에 마침표가 흔해서
#   문장부호만으로는 이름의 끝을 판단할 수 없다(이름 끝은 '라는 상품'이 정해 준다).
_NAMED = re.compile(
    r"(?P<name>[^,?!\n]{2,80}?)\s*(?:이?라는|이?란|という|といった)\s*(?:상품|제품|아이템|商品|製品|アイテム)"
)

# 위 두 형태가 아니어도 '상품명'을 명시하고 조회를 물으면 받는다.
# 여기서는 이름의 끝을 정해 주는 말이 없으므로 _cut_tail 로 질문 꼬리를 잘라낸다.
_NAME_LABEL = re.compile(r"(?:상품명|제품명|商品名|製品名)\s*(?:은|는|이|가|을|를|の|は)?\s*(?P<name>[^,?!\n]{2,80})")

# 이름 뒤에 붙는 질문 꼬리. '상품명은 numbuzin No.3 인데 취급하나요?' 의 '인데 취급하나요'.
_QUERY_TAIL_TOKENS = (
    "인데", "인가", "이라고", "라고", "맞나", "맞는", "조회", "검색", "취급", "판매",
    "파나", "있나", "있어", "있을", "입고", "들어오", "찾을", "찾아",
    "という", "ですか", "ありま", "取り扱", "販売", "入荷", "検索", "照会",
)


def _cut_tail(name: str) -> str:
    cut = len(name)
    for token in _QUERY_TAIL_TOKENS:
        found = name.find(token)
        # 0 번째면 이름 자체가 꼬리라는 뜻이라 자를 게 없다.
        if found > 0:
            cut = min(cut, found)
    return name[:cut].strip()

# 조회 의도어. 위 패턴으로 이름을 뽑아도 이 말이 없으면 그냥 상품을 언급한 문장일 수 있다.
_LOOKUP_INTENT = re.compile(
    r"(조회|검색|찾을\s*수|찾아|있나요|있어요|있을까|파나요|판매|취급|들어\s*오|입고"
    r"|検索|照会|探せ|ありますか|ありますでしょうか|取り扱|販売|入荷)"
)

# 대체 상품 요청. '매장에 없다 / 품절이다 / 다른 걸 달라'가 핵심이다.
_ALTERNATIVE_INTENT = re.compile(
    r"(다른\s*(?:상품|제품|추천)|대체|대신|비슷한\s*(?:상품|제품)|품절|재고\s*없|없다는|없대|없다고|안\s*판"
    r"|他の(?:商品|製品|おすすめ)|代わり|代替|似た(?:商品|製品)|売り切れ|在庫\s*(?:切れ|なし|がない)|置いてな)"
)

# 상품명 대조용 정규화에서 지우는 글자. 용량·세트 표기가 붙고 안 붙고로 어긋나는 걸 줄인다.
_NOISE = re.compile(r"[\s\-_/()\[\]{},.·・…&+]+")


def _normalize(text: str) -> str:
    return _NOISE.sub("", (text or "").lower())


def _tokens(text: str) -> set[str]:
    # 길이 2 미만 토큰은 버린다 — 'a', '3' 같은 조각이 겹쳐 엉뚱한 상품이 잡힌다.
    return {token for token in re.split(r"[^0-9a-z가-힣ぁ-んァ-ヶ一-龥]+", (text or "").lower()) if len(token) >= 2}


# 질문 끝에 붙는 군더더기. 이름만 남겨야 카탈로그와 대조된다.
_TRAILING_JOSA = re.compile(r"(?:이|가|은|는|을|를|의|도|와|과|랑|이랑|って|は|が|を|の)\s*$")


def extract_product_query(message: str) -> str | None:
    """질문에서 조회 대상 상품명을 뽑는다. 조회 질문이 아니면 None.

    보수적으로 잡는다 — 일반 성분·루틴 질문을 상품 조회로 오인하면 상담이 통째로 망가진다.
    따옴표/‘라는 상품’/‘상품명’ 셋 중 하나로 이름이 특정되고, 조회 의도어까지 있을 때만 받는다.
    """
    if not message or not _LOOKUP_INTENT.search(message):
        return None
    # 꼬리 절단은 _NAME_LABEL 에만 건다 — 따옴표와 '라는 상품'은 이름의 끝이 이미 정해져 있어,
    # 자르면 '있어요 크림'처럼 꼬리 토큰을 품은 정상 상품명이 잘려 나간다.
    for pattern, cut_tail in ((_QUOTED, False), (_NAMED, False), (_NAME_LABEL, True)):
        found = pattern.search(message)
        if not found:
            continue
        name = found.group("name").strip()
        if cut_tail:
            name = _cut_tail(name)
        name = _TRAILING_JOSA.sub("", name).strip()
        if len(_normalize(name)) >= _MIN_QUERY_LEN:
            return name
    return None


def is_alternative_request(message: str) -> bool:
    """'매장에 없대요, 다른 추천 있을까요?' 부류인가."""
    return bool(message) and bool(_ALTERNATIVE_INTENT.search(message))


def _match_score(product: Product, query_norm: str, query_tokens: set[str]) -> float:
    """상품 하나와 질의의 일치도. 0 이면 후보가 아니다."""
    brand = product.brand.name if product.brand else ""
    full_norm = _normalize(f"{brand}{product.name}")
    if not full_norm:
        return 0.0
    # 한쪽이 다른 쪽을 통째로 품으면 확실한 일치다(용량 표기 차이 등).
    if query_norm in full_norm or full_norm in query_norm:
        return 100.0 + len(query_norm)
    overlap = query_tokens & _tokens(f"{brand} {product.name}")
    if not overlap:
        return 0.0
    # 질의 토큰이 얼마나 덮였는지로 본다. 상품명이 긴 카탈로그라 '겹친 개수'만 세면
    # 이름이 긴 상품이 항상 이긴다(부분문자열 오탐과 같은 부류의 실수).
    return len(overlap) / len(query_tokens) * 10.0


def find_products(db: Session, query: str, limit: int = _MAX_HITS) -> list[Product]:
    query_norm = _normalize(query)
    query_tokens = _tokens(query)
    if not query_norm:
        return []
    rows = db.query(Product).options(selectinload(Product.brand)).all()
    scored = [(score, product) for product in rows if (score := _match_score(product, query_norm, query_tokens)) > 0]
    # 동점이면 평점이 높은 쪽을 앞세운다.
    scored.sort(key=lambda item: (item[0], item[1].avg_rating or 0.0), reverse=True)
    # 부분 일치만 있는 경우(점수 10 미만 = 질의의 절반도 못 덮음)는 노이즈라 버린다.
    best = scored[0][0] if scored else 0.0
    cutoff = 5.0 if best >= 100.0 else 5.0
    return [product for score, product in scored[:limit] if score >= cutoff]


def _ingredient_names(db: Session, product_ids: list[int]) -> dict[int, list[str]]:
    if not product_ids:
        return {}
    rows = (
        db.query(ProductIngredient)
        .options(selectinload(ProductIngredient.ingredient))
        .filter(ProductIngredient.product_id.in_(product_ids))
        .all()
    )
    names: dict[int, list[str]] = {}
    for row in rows:
        if row.ingredient is not None:
            names.setdefault(row.product_id, []).append(row.ingredient.name)
    return names


def _alternative_products(db: Session, ingredients: list[Ingredient], limit: int) -> list[Product]:
    """주어진 성분을 가진 상품을 평점 순으로 고른다."""
    ids = [ingredient.id for ingredient in ingredients]
    if not ids:
        return []
    rows = (
        db.query(Product)
        .options(selectinload(Product.brand))
        .join(ProductIngredient, ProductIngredient.product_id == Product.id)
        .filter(ProductIngredient.ingredient_id.in_(ids))
        .all()
    )
    ranked: dict[int, tuple[int, Product]] = {}
    for product in rows:
        hits, _existing = ranked.get(product.id, (0, product))
        ranked[product.id] = (hits + 1, product)
    ordered = sorted(ranked.values(), key=lambda item: (item[0], item[1].avg_rating or 0.0), reverse=True)
    return [product for _hits, product in ordered[:limit]]


# ── 문장(한국어·일본어 쌍) ────────────────────────────────────────────────────
# ⚠ 함수 안에 한국어 문장을 두지 않는다. 여기 한 쌍으로 모아 두어야 한쪽만 늘어나지 않는다.
_TEXT: dict[str, dict[str, str]] = {
    "ko": {
        "found": "‘{query}’ 로 찾은 상품이에요.",
        "item": "· {brand} {name} ({category})",
        "item_rating": "· {brand} {name} ({category}) · ★ {rating}",
        "item_plain": "· {brand} {name}",
        "item_rating_plain": "· {brand} {name} · ★ {rating}",
        "found_tail": "맞춤 추천 화면의 상품 카드에서 구매처 링크를 열 수 있어요.",
        "not_found": "‘{query}’ 는 지금 카탈로그에서 찾지 못했어요.",
        "not_found_tail": "이름을 조금 더 짧게(브랜드나 제품 라인만) 적어 주시면 다시 찾아볼게요.",
        "near_miss": "이름이 비슷한 상품은 이렇게 있어요.",
        "alt_lead": "매장 재고는 저희가 확인할 수 없어요. 대신 같은 성분 계열로 고를 수 있는 상품을 정리했어요.",
        "alt_basis": "기준 성분: {ingredients}",
        "alt_tail": "성분이 같으면 브랜드가 달라도 기대하는 효과는 비슷합니다. 하나씩 바꿔 써 보세요.",
        "alt_no_context": "먼저 피부 분석을 한 번 진행해 주시면 피부 상태에 맞는 대체 상품을 골라 드릴 수 있어요.",
        "alt_empty": "지금 카탈로그에는 같은 성분 계열의 대체 상품이 없어요. 지역이나 구매 플랫폼을 넓혀서 다시 추천받아 보세요.",
    },
    "ja": {
        "found": "「{query}」で見つかった商品です。",
        "item": "・{brand} {name}（{category}）",
        "item_rating": "・{brand} {name}（{category}）・★ {rating}",
        "item_plain": "・{brand} {name}",
        "item_rating_plain": "・{brand} {name}・★ {rating}",
        "found_tail": "カスタムおすすめ画面の商品カードから購入先リンクを開けます。",
        "not_found": "「{query}」は現在のカタログでは見つかりませんでした。",
        "not_found_tail": "商品名をもう少し短く（ブランド名や製品ラインだけ）ご入力いただければ、もう一度お探しします。",
        "near_miss": "名前が近い商品はこちらです。",
        "alt_lead": "店舗の在庫はこちらでは確認できません。代わりに、同じ成分系統から選べる商品をまとめました。",
        "alt_basis": "基準の成分: {ingredients}",
        "alt_tail": "成分が同じであれば、ブランドが違っても期待できる効果は近くなります。ひとつずつ試してみてください。",
        "alt_no_context": "先に肌分析を一度行っていただくと、肌状態に合わせた代わりの商品をお選びできます。",
        "alt_empty": "現在のカタログには同じ成分系統の代わりになる商品がありません。地域や購入プラットフォームを広げて、もう一度おすすめを受け取ってみてください。",
    },
}


def _lang_key(lang: str | None) -> str:
    return "ja" if (lang or "ko").strip().lower().startswith("ja") else "ko"


# 카탈로그의 category 는 'body.lotion' 같은 내부 키다. 그대로 보여주면 사용자 화면에
# 코드가 노출된다. 표에 없는 키는 통째로 감춘다 — 모르는 코드를 보여주느니 안 보이는 게 낫다.
_CATEGORY_LABELS: dict[str, dict[str, str]] = {
    "ko": {
        "cleanser": "클렌저", "cleansers": "클렌저", "body.wash": "바디워시",
        "toner": "토너", "toners": "토너", "serum": "세럼", "serums": "세럼",
        "essence": "에센스", "ampoule": "앰플", "moisturizer": "보습", "moisturizers": "보습",
        "cream": "크림", "lotion": "로션", "body.lotion": "바디로션", "body.cream": "바디크림",
        "sunscreen": "선크림", "suncare": "선크림", "mask": "마스크", "masks": "마스크",
        "eye": "아이케어", "lip": "립", "acne & blemish treatments": "트러블 케어",
    },
    "ja": {
        "cleanser": "クレンザー", "cleansers": "クレンザー", "body.wash": "ボディウォッシュ",
        "toner": "化粧水", "toners": "化粧水", "serum": "美容液", "serums": "美容液",
        "essence": "エッセンス", "ampoule": "アンプル", "moisturizer": "保湿", "moisturizers": "保湿",
        "cream": "クリーム", "lotion": "乳液", "body.lotion": "ボディローション", "body.cream": "ボディクリーム",
        "sunscreen": "日焼け止め", "suncare": "日焼け止め", "mask": "マスク", "masks": "マスク",
        "eye": "アイケア", "lip": "リップ", "acne & blemish treatments": "トラブルケア",
    },
}


def _display_name(product: Product) -> tuple[str, str]:
    """(브랜드, 상품명). 상품명이 이미 브랜드로 시작하면 브랜드를 비운다.

    카탈로그 상당수가 상품명 안에 브랜드를 품고 있어서(실측: '라운드랩 [대용량] 라운드랩 1025
    독도 로션'), 그대로 '{브랜드} {상품명}' 으로 이으면 브랜드가 두 번 찍힌다.
    """
    brand = product.brand.name if product.brand else ""
    name = (product.name or "").strip()
    if brand and _normalize(name).startswith(_normalize(brand)):
        return "", name
    return brand, name


def _product_lines(products: list[Product], text: dict[str, str], lang_key: str) -> list[str]:
    labels = _CATEGORY_LABELS[lang_key]
    lines = []
    for product in products:
        brand, name = _display_name(product)
        category = labels.get((product.category or "").strip().lower(), "")
        key = "item_rating" if product.avg_rating else "item"
        if not category:
            key = "item_rating_plain" if product.avg_rating else "item_plain"
        fields = {"brand": brand, "name": name, "category": category}
        if product.avg_rating:
            lines.append(text[key].format(**fields, rating=f"{product.avg_rating:.1f}").strip())
        else:
            lines.append(text[key].format(**fields).strip())
    return lines


def answer_product_lookup(db: Session, query: str, lang: str | None = "ko") -> ChatResponse:
    """'OO 라는 상품 있나요?' 답변. 못 찾으면 못 찾았다고 말한다(지어내지 않는다)."""
    key = _lang_key(lang)
    text = _TEXT[key]
    hits = find_products(db, query)
    if hits:
        lines = [text["found"].format(query=query), *_product_lines(hits, text, key), text["found_tail"]]
        return ChatResponse(answer="\n".join(lines), sources=[])
    # 통째 조회는 실패했지만 이름의 앞부분(브랜드·라인)으로는 걸릴 수 있다.
    head = " ".join(query.split()[:2])
    near = find_products(db, head) if head and head != query else []
    lines = [text["not_found"].format(query=query)]
    if near:
        lines.append(text["near_miss"])
        lines.extend(_product_lines(near, text, key))
    else:
        lines.append(text["not_found_tail"])
    return ChatResponse(answer="\n".join(lines), sources=[])


def answer_alternatives(db: Session, context: dict | None, lang: str | None = "ko") -> ChatResponse:
    """'매장에 없대요, 다른 추천 있을까요?' 답변.

    피부 점수·설문에서 뽑은 **성분**을 기준으로 고른다. 재고를 아는 척하지 않고,
    '같은 성분 계열이면 대체할 수 있다'는 근거를 명시한다.
    """
    # 순환 참조를 피해 함수 안에서 가져온다(recommender 는 무거운 모듈을 여럿 끌고 온다).
    from app.services.recommender import infer_ingredients

    key = _lang_key(lang)
    text = _TEXT[key]
    raw_scores = (context or {}).get("scores") or {}
    raw_survey = (context or {}).get("survey") or {}
    if not raw_scores:
        return ChatResponse(answer=text["alt_no_context"], sources=[])
    try:
        scores = SkinScores(**{key: raw_scores.get(key, 0) for key in SkinScores.model_fields})
        survey = SurveyInput(**raw_survey) if raw_survey else SurveyInput(skin_type="normal", concerns=[])
    except Exception:
        # 프론트가 보내는 문맥 형태가 바뀌어도 상담 자체가 죽지는 않게 한다.
        return ChatResponse(answer=text["alt_no_context"], sources=[])

    ingredients = infer_ingredients(db, scores, survey)
    products = _alternative_products(db, ingredients, _MAX_ALTERNATIVES)
    if not products:
        return ChatResponse(answer="\n".join([text["alt_lead"], text["alt_empty"]]), sources=[])
    names = [ingredient.name for ingredient in ingredients[:3]]
    lines = [
        text["alt_lead"],
        text["alt_basis"].format(ingredients=", ".join(names)),
        *_product_lines(products, text, key),
        text["alt_tail"],
    ]
    return ChatResponse(answer="\n".join(lines), sources=names)


def answer_catalog_question(
    db: Session, message: str, context: dict | None = None, lang: str | None = "ko"
) -> ChatResponse | None:
    """카탈로그 갈래에 해당하면 답변을, 아니면 None 을 돌려 일반 상담으로 흘려보낸다.

    순서가 중요하다 — '그 상품 없대요, 다른 거 있나요?' 에는 상품명과 대체 요청이 함께 들어 있다.
    이때 원하는 답은 '있다/없다'가 아니라 **대체 상품**이므로 대체 요청을 먼저 본다.
    """
    if not message:
        return None
    if is_alternative_request(message):
        return answer_alternatives(db, context, lang)
    query = extract_product_query(message)
    if query:
        return answer_product_lookup(db, query, lang)
    return None

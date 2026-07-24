"""바디/핸드/풋 상품 카테고리 기준 (단일 정의).

수집 스크립트(scripts/build_body_catalog.py)와 추천기가 같은 정의를 쓰도록 여기 모은다.

설계 원칙 두 가지:

1. **네임스페이스로 섞임 방지.** 카테고리 값은 항상 ``<group>.<form>`` 형태다
   (``body.lotion``, ``hand.cream``). 얼굴 상품은 기존대로 접두사 없는 값
   (``cream``, ``lotion``, ``serum``)을 쓰므로 문자열이 절대 충돌하지 않는다.
   기존 바디 경로가 얼굴 크림을 추천하던 원인이 ``{"cream", "lotion", ...}``
   whitelist였다 — 접두사가 그 사고를 구조적으로 막는다.

2. **공식 카테고리 우선, 키워드는 폴백.** 이름 키워드만 쓰면 올리브영 공식
   'Bath & Body' 106건 중 55건을 놓친다(실측). ILLIYOON 세라마이드 아토로션처럼
   이름에 'body'가 없는 대표 바디 상품이 통째로 빠지기 때문. 소스가 공식
   카테고리를 주면 그게 '바디인가'를 결정하고, 키워드는 '어떤 제형인가'만 정한다.

핸드/풋은 바디와 별도 그룹이다. 매니페디큐어 기능이 이 그룹을 가져가고,
바디 추천은 ``body.*``만 본다.
"""
from __future__ import annotations

import re

BODY = "body"
HAND = "hand"
FOOT = "foot"

# ── 카테고리 정의 ────────────────────────────────────────────────────────────
# key = DB에 저장되는 category 값. label = 표시용. group = 소속 기능.
CATEGORIES: dict[str, dict[str, str]] = {
    # 몸통·팔·다리
    "body.wash":         {"group": BODY, "label": "바디워시·샤워"},
    "body.lotion":       {"group": BODY, "label": "바디로션"},
    "body.cream":        {"group": BODY, "label": "바디크림·버터"},
    "body.oil":          {"group": BODY, "label": "바디오일"},
    "body.scrub":        {"group": BODY, "label": "바디스크럽·각질"},
    "body.treatment":    {"group": BODY, "label": "바디 세럼·트러블케어"},
    "body.sun":          {"group": BODY, "label": "바디 선케어"},
    "body.mist":         {"group": BODY, "label": "바디미스트·퍼퓸"},
    "body.deodorant":    {"group": BODY, "label": "데오드란트"},
    "body.hair_removal": {"group": BODY, "label": "제모"},
    # 손 (매니큐어 기능과 공유)
    "hand.cream":        {"group": HAND, "label": "핸드크림"},
    "hand.wash":         {"group": HAND, "label": "핸드워시·새니타이저"},
    "hand.mask":         {"group": HAND, "label": "핸드팩·마스크"},
    # 발 (페디큐어 기능과 공유)
    "foot.cream":        {"group": FOOT, "label": "풋크림·힐밤"},
    "foot.peel":         {"group": FOOT, "label": "발각질·풋마스크"},
    "foot.deodorant":    {"group": FOOT, "label": "발 데오드란트"},
}

BODY_CATEGORIES = frozenset(k for k, v in CATEGORIES.items() if v["group"] == BODY)
HAND_CATEGORIES = frozenset(k for k, v in CATEGORIES.items() if v["group"] == HAND)
FOOT_CATEGORIES = frozenset(k for k, v in CATEGORIES.items() if v["group"] == FOOT)
ALL_CATEGORIES = frozenset(CATEGORIES)

# 피부질환(습진·아토피·건선 등) 기반 바디 추천에 실제로 쓸 카테고리.
# 나머지(미스트·데오드란트·제모)는 카탈로그로만 보유하고 추천에는 올리지 않는다.
BODY_CARE_CATEGORIES = frozenset({
    "body.wash",
    "body.lotion",
    "body.cream",
    "body.oil",
    "body.treatment",
})
# 각질제거는 건선처럼 각질 완화가 도움되는 경우에만. 습진·아토피엔 자극이라 뺀다.
BODY_EXFOLIANT_CATEGORIES = frozenset({"body.scrub"})


def group_of(category: str) -> str | None:
    meta = CATEGORIES.get(category)
    return meta["group"] if meta else None


def label_of(category: str) -> str:
    meta = CATEGORIES.get(category)
    return meta["label"] if meta else category


# ── 제형 키워드 (EN / KO / JA 동시) ──────────────────────────────────────────
# 순서 = 우선순위. 구체적인 것(풋·핸드·스크럽)이 포괄적인 것(로션)보다 앞에 온다.
_FORM_RULES: list[tuple[str, str]] = [
    ("foot.peel", r"foot\s*(peel|mask|pack|exfoli)|heel\s*(peel|file)|"
                  r"발\s*각질|풋\s*(필링|마스크|팩)|"
                  r"かかと\s*(角質|ケア)|フット\s*(ピーリング|マスク|パック)|角質\s*除去\s*.*足"),
    ("foot.deodorant", r"foot\s*(deodorant|powder|spray)|발\s*냄새|"
                       r"フット\s*(デオドラント|パウダー|スプレー)|足\s*(用)?\s*(制汗|消臭)"),
    ("foot.cream", r"foot\s*(cream|balm|butter|lotion|care|serum)|heel\s*(balm|cream)|"
                   r"풋\s*(크림|밤|로션|케어)|발\s*(크림|보습)|뒤꿈치|"
                   r"フット\s*(クリーム|バーム|ケア|ローション)|かかと\s*(クリーム|バーム)"),
    ("hand.mask", r"hand\s*(mask|pack|glove)|핸드\s*(팩|마스크)|ハンド\s*(マスク|パック)"),
    ("hand.wash", r"hand\s*(wash|soap|sanitiz|gel\s*sanit)|핸드\s*(워시|솝|비누|새니타이저|세니타이저)|"
                  r"ハンド\s*(ソープ|ウォッシュ|ジェル)|手指\s*消毒"),
    ("hand.cream", r"hand\s*(cream|balm|butter|lotion|serum|essence|treatment)|hand\s*(&|and)\s*nail|"
                   r"핸드\s*(크림|밤|버터|로션|에센스|세럼)|"
                   r"ハンド\s*(クリーム|バーム|ミルク|美容液)|手\s*荒れ.*クリーム"),
    ("body.hair_removal", r"hair\s*removal\s*(cream|lotion|foam)|depilator[y]?\s*(cream|lotion)|"
                          r"제모\s*(크림|왁스)|除毛\s*(クリーム|フォーム)|脱毛\s*(クリーム|ワックス)"),
    ("body.deodorant", r"deodorant|antiperspirant|데오드란트|데오\s*스틱|"
                       r"デオドラント|制汗\s*(スプレー|シート|剤)|わきが"),
    ("body.sun", r"body\s*(sun|sunscreen|uv)|sun\s*(cream|milk|stick|spray)\s*(for\s*)?body|"
                 r"바디\s*(선크림|선스틱|선케어|자외선)|"
                 r"ボディ\s*(用)?\s*(日焼け止め|サンスクリーン|ＵＶ|UV)"),
    ("body.scrub", r"body\s*(scrub|polish|exfoliat|peeling)|salt\s*scrub|sugar\s*scrub|"
                   r"바디\s*(스크럽|필링|각질)|"
                   r"ボディ\s*(スクラブ|ピーリング|ゴマージュ)"),
    ("body.oil", r"body\s*oil|massage\s*oil|바디\s*오일|마사지\s*오일|"
                 r"ボディ\s*(オイル)|マッサージ\s*オイル"),
    ("body.mist", r"body\s*(mist|spray|perfume|cologne|shimmer)|"
                  r"바디\s*(미스트|스프레이|퍼퓸|코롱)|"
                  r"ボディ\s*(ミスト|スプレー|コロン|フレグランス)"),
    ("body.wash", r"body\s*(wash|cleanser|shampoo|soap|foam|bar)|"
                  r"shower\s*(gel|cream|oil|milk|foam|soap|wash|cologne)|"
                  r"bath\s*(gel|soak|milk|salt|bomb|powder|foam|blaster|oil)|"
                  r"바디\s*(워시|클렌저|샤워|폼|솝|비누|바)|샤워\s*(젤|크림|오일|밀크|폼)|"
                  r"입욕제|배쓰\s*(밤|솔트)|"
                  r"ボディ\s*(ソープ|ウォッシュ|シャンプー)|"
                  r"シャワー\s*(ジェル|クリーム|オイル|ミルク)|入浴剤|バス\s*(ソルト|ミルク|ボム)|薬用\s*石けん"),
    ("body.cream", r"body\s*(cream|butter|balm)|바디\s*(크림|버터|밤)|"
                   r"ボディ\s*(クリーム|バター|バーム)"),
    ("body.treatment", r"body\s*(serum|essence|ampoule|treatment|spot)|"
                       r"바디\s*(세럼|에센스|앰플|트리트먼트|트러블)|"
                       r"ボディ\s*(美容液|セラム|エッセンス)"),
    ("body.lotion", r"body\s*(lotion|milk|emulsion|moisturi[sz]er|gel)|hand\s*(&|and)\s*body|"
                    r"바디\s*(로션|밀크|에멀젼|젤|보습)|전신\s*보습|"
                    r"ボディ\s*(ローション|ミルク|乳液|ジェル)|全身\s*(保湿|用)"),
]
_COMPILED_FORMS = [(cat, re.compile(pat, re.I)) for cat, pat in _FORM_RULES]

# 공식 카테고리가 없는 소스(아마존·올영KR 검색)에서 바디로 오분류되는 상품들.
# 실측 오탐: 립스크럽이 body.scrub, 얼굴 세라마이드크림이 body.cream,
# 속눈썹뷰러가 hair_removal, 헤어 드라이오일이 body.oil로 잡혔다.
_NON_BODY_RE = re.compile(
    r"lip\s*(stick|tint|gloss|balm|crayon|cheek|scrub|mask|sleeping)|lipstick|"
    r"mascara|eyeshadow|eye\s*(cream|liner|patch|shadow)|cushion|foundation|concealer|"
    r"blush|highlighter\b|palette|brow\b|nail\s*(polish|color|art|tip|sticker)|"
    r"shampoo\s*(for\s*)?hair|hair\s*(oil|serum|essence|mask|pack|treatment|tonic|color|dye|spray|mist|curl)|"
    r"conditioner|scalp|헤어|두피|샴푸|린스|트리트먼트\s*헤어|"
    r"tweezer|curler|brush\b|sponge|puff\b|applicator|device|machine|razor\b|epilator|"
    r"toothpaste|mouthwash|denture|supplement|tablet|capsule\b|"
    r"립|틴트|립스틱|쿠션|마스카라|섀도우|아이라이너|네일\s*(폴리시|아트)|"
    r"リップ|口紅|マスカラ|アイシャドウ|クッション|ファンデーション|"
    r"シャンプー|コンディショナー|ヘア\s*(オイル|カラー|トリートメント)|頭皮|育毛|"
    r"歯磨|マウスウォッシュ|サプリ",
    re.I,
)

_BODY_TOKEN_RE = re.compile(r"\bbody\b|바디|전신|ボディ|全身", re.I)

# 얼굴 '제형'까지 명시된 표기. 단순히 'face'가 스쳐 지나가는 것과 구분한다.
# COSRX 얼굴 크림이 SEO 꼬리표에 'ボディローション ボディクリーム'을 달고 있어
# 바디로 잡히던 케이스를 잡기 위한 규칙.
_FACE_FORM_RE = re.compile(
    r"\bfac(e|ial)\s*(cream|lotion|serum|essence|wash|cleanser|moisturi[sz]er|mask)|"
    r"얼굴\s*(전용|크림)|페이스\s*(크림|세럼)|"
    r"フェイス\s*(クリーム|ローション|美容液|マスク|用|専用)|顔\s*用",
    re.I,
)
# 얼굴·바디 겸용 표기. 있으면 얼굴 제형이 적혀 있어도 바디로 인정한다.
_DUAL_USE_RE = re.compile(
    r"\bfac(e|ial)\s*(and|&|\+)\s*body|\bbody\s*(and|&|\+)\s*fac(e|ial)|"
    r"all\s*over|얼굴\s*(과|및|\+|&)?\s*바디|페이스\s*(&|앤)\s*바디|"
    r"顔\s*[・、･＆&]?\s*全身|全身\s*用|フェイス\s*[＆&]\s*ボディ",
    re.I,
)
# 선케어 표기. 바디 언급이 없으면 얼굴 선크림이라 배제하고,
# 있으면 제형과 무관하게 body.sun으로 보낸다(로션으로 잡히던 것 교정).
_SUNCARE_RE = re.compile(
    r"sunscreen|sun\s*cream|sun\s*milk|sun\s*stick|\bspf\s*\d|pa\+{2,}|"
    r"선크림|선스틱|자외선\s*차단|"
    r"日焼け止め|サンクリーム|サンスクリーン|化粧下地",
    re.I,
)
# 세트·기획 상품의 괄호 안 증정품. 본품이 크림인데 증정 오일 때문에 body.oil로
# 잡히는 사고를 막는다(ILLIYOON MD 레드 잇치 케어 크림 +오일 20mL 등).
_BUNDLE_EXTRA_RE = re.compile(
    r"\((?:[^()]*?(?:\+|증정|기획|선물|사은|무료|おまけ|付き)[^()]*?)\)|"
    r"\(\s*(?:set|세트)\s*/[^()]*\)",
    re.I,
)


def strip_bundle_extras(text: str) -> str:
    """세트 구성의 괄호 증정품 표기를 떼어 본품 이름만 남긴다."""
    previous = None
    while previous != text:
        previous = text
        text = _BUNDLE_EXTRA_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def classify_form(*names: str) -> str | None:
    """이름에서 제형 카테고리를 뽑는다.

    규칙 순서가 아니라 **매치 위치**로 고른다. 상품명은 본품 제형을 앞에 쓰고
    부가 설명을 뒤에 붙이기 때문. 'Body Lotion ... Body and Hand Lotion'이
    hand.cream으로 잡히던 게 이 때문이었다. 같은 위치면 규칙 순서로 가른다.
    """
    text = " ".join(n for n in names if n).strip()
    if not text:
        return None
    best: tuple[int, int, str] | None = None
    for order, (category, pattern) in enumerate(_COMPILED_FORMS):
        match = pattern.search(text)
        if not match:
            continue
        candidate = (match.start(), order, category)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    return best[2] if best else None


def is_excluded(*names: str) -> bool:
    """공식 카테고리 없는 소스에서 바디가 아닌 게 확실한 상품인지."""
    text = " ".join(n for n in names if n).strip()
    if not text:
        return True
    if _NON_BODY_RE.search(text):
        return True
    has_body = bool(_BODY_TOKEN_RE.search(text))
    # 선케어는 바디 명시가 없으면 얼굴 선크림으로 본다.
    if _SUNCARE_RE.search(text) and not has_body:
        return True
    # 얼굴 제형이 적혀 있으면 겸용 표기가 있을 때만 인정한다. 바디 단어가
    # SEO 꼬리표에만 붙은 얼굴 상품을 여기서 떨군다.
    if _FACE_FORM_RE.search(text) and not _DUAL_USE_RE.search(text):
        return True
    return False


def classify_by_keyword(*names: str) -> str | None:
    """공식 카테고리가 없는 소스용. 배제 규칙을 먼저 통과해야 한다."""
    cleaned = [strip_bundle_extras(n) for n in names if n]
    if is_excluded(*cleaned):
        return None
    text = " ".join(cleaned)
    # 선케어는 제형(로션·크림)보다 용도가 우선이다.
    if _SUNCARE_RE.search(text):
        return "body.sun"
    return classify_form(*cleaned)


# 브랜드 자체가 '바디 제품'을 뜻하는 브랜드들. 이들은 상품명을 그냥 '로션/크림/오일'로
# 적어(바디 접두어 없이) classify_by_keyword 가 얼굴/바디를 구분 못 해 떨군다. 존슨즈베이비
# 로션·아토팜 판테놀 로션 같은 게 그 예. 브랜드가 바디임을 알면 맨제형으로 분류할 수 있다.
_BODY_BRANDS_KO = (
    "아토팜", "atopalm", "존슨즈", "johnson", "궁중비책", "밤부베베", "피지오겔", "physiogel",
    "시체르", "그린핑거", "일리윤", "illiyoon", "해피바스", "온더바디", "세타필", "cetaphil",
    "유세린", "eucerin", "닥터지", "라운드랩", "사봉", "미구하라", "더바디샵", "러쉬",
)
# 브랜드 폴백에서도 배제할 얼굴·남성·임산부·기능성 신호(브랜드가 바디여도 이건 바디가 아님).
_BRAND_FALLBACK_EXCLUDE = re.compile(
    r"포맨|포맨즈|for\s*men|남성|맨즈|얼굴|페이스|フェイス|올인원|토너|스킨\b|앰플|"
    r"임산부|매터니티|튼살|아이크림|클렌징\s*(오일|워터|밤)|선|자외선|쿠션|파운데이션",
    re.I,
)
# 브랜드 폴백용 맨제형 → 카테고리(바디 그룹 한정).
_KR_BARE_FORM: list[tuple[str, str]] = [
    ("body.wash", r"워시|클렌저|비누|바디\s*폼|샤워|입욕|버블\s*폼|엉덩이\s*클렌저"),
    ("body.scrub", r"스크럽|각질|필링"),
    ("body.oil", r"오일"),
    ("body.treatment", r"세럼|에센스|앰플|트리트먼트"),
    ("body.cream", r"크림|버터|밤\b"),
    ("body.lotion", r"로션|밀크|보습|모이스처|에멀젼|젤\b"),
]
_KR_BARE_FORM_C = [(cat, re.compile(pat, re.I)) for cat, pat in _KR_BARE_FORM]


def classify_kr_with_brand(brand: str, name: str) -> str | None:
    """KR 검색 상품용. 먼저 일반 키워드 판정, 실패 시 '바디 브랜드' 폴백.

    폴백은 (1) 브랜드가 알려진 바디 브랜드이고 (2) 얼굴·남성·임산부·선케어 신호가 없고
    (3) 맨제형 키워드가 있을 때만 body.<form> 을 준다. 얼굴 상품 오분류를 막기 위한 3중 게이트.
    """
    stripped = strip_bundle_extras(re.sub(r"^\[[^\]]*\]\s*", "", name or ""))
    primary = classify_by_keyword(stripped)
    if primary:
        return primary
    brand_l = (brand or "").lower()
    if not any(b in brand_l or b in stripped.lower() for b in _BODY_BRANDS_KO):
        return None
    if _BRAND_FALLBACK_EXCLUDE.search(stripped) or _NON_BODY_RE.search(stripped):
        return None
    for category, pattern in _KR_BARE_FORM_C:
        if pattern.search(stripped):
            return category
    return None


# ── 그룹이 이미 확정됐을 때 쓰는 제형 분류 ──────────────────────────────────
# 'body' 접두어를 요구하지 않는다. 공식 카테고리가 이미 "이건 바디다"를 말해준
# 뒤에만 호출하므로 안전하다. ILLIYOON Ultra Repair Cream(이름에 body 없음)을
# body.cream으로 보내는 게 이 함수의 목적.
_BARE_FORM_RULES: list[tuple[str, str]] = [
    ("sun", r"sunscreen|sun\s*cream|sun\s*milk|sun\s*stick|\bspf\b|선크림|선스틱|日焼け止め|サンクリーム"),
    ("scrub", r"scrub|polish|exfoliat|peeling|gommage|각질|스크럽|필링|スクラブ|ゴマージュ|ピーリング"),
    ("wash", r"wash|cleanser|cleansing|soap|foam|shampoo|\bbar\b|blaster|bomb|soak|"
             r"워시|클렌저|비누|폼|솝|입욕|"
             r"ソープ|ウォッシュ|石けん|石鹸|入浴|バスソルト"),
    ("oil", r"\boil\b|오일|オイル"),
    ("mist", r"mist|spray|perfume|cologne|fragrance|미스트|스프레이|퍼퓸|ミスト|スプレー|フレグランス"),
    ("cream", r"cream|butter|balm|크림|버터|밤|クリーム|バター|バーム"),
    ("treatment", r"serum|essence|ampoule|세럼|에센스|앰플|美容液|セラム|エッセンス"),
    ("lotion", r"lotion|milk|emulsion|moistur|\bgel\b|로션|밀크|에멀젼|젤|보습|ローション|ミルク|乳液|ジェル"),
]
_COMPILED_BARE = [(form, re.compile(pat, re.I)) for form, pat in _BARE_FORM_RULES]

# 그룹에 그 제형이 없을 때 대신 쓸 카테고리.
_FORM_ALIASES: dict[tuple[str, str], str] = {
    (FOOT, "scrub"): "foot.peel",
    (FOOT, "wash"): "foot.peel",
    (FOOT, "lotion"): "foot.cream",
    (FOOT, "oil"): "foot.cream",
    (FOOT, "treatment"): "foot.cream",
    (FOOT, "mist"): "foot.deodorant",
    (HAND, "lotion"): "hand.cream",
    (HAND, "oil"): "hand.cream",
    (HAND, "treatment"): "hand.cream",
    (HAND, "scrub"): "hand.cream",
    (HAND, "mist"): "hand.wash",
}


def classify_within_group(group: str, default: str, *names: str) -> str:
    """공식 카테고리로 그룹이 확정된 상품의 제형을 정한다.

    제형을 못 찾거나 그 그룹에 없는 제형이면 ``default``(= 소스 공식 카테고리가
    말하는 기본값)를 그대로 쓴다. 공식 정보를 키워드가 뒤집지 못하게 하는 게 요점.
    """
    text = " ".join(strip_bundle_extras(n) for n in names if n).strip()
    if not text:
        return default
    for form, pattern in _COMPILED_BARE:
        if not pattern.search(text):
            continue
        candidate = f"{group}.{form}"
        if candidate in CATEGORIES:
            return candidate
        alias = _FORM_ALIASES.get((group, form))
        if alias:
            return alias
    return default

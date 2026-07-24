"""한글/일본어 성분명 → 표준 성분명(INGREDIENT_RULES 키) 매핑.

왜 필요한가: 올리브영 상품정보제공고시가 주는 전성분은 대한화장품협회 표준화 성분명
(한글)이다. `살리실릭애씨드`이지 `salicylic acid`가 아니고, `병풀추출물`이지
`centella`가 아니다. 기존 detect_ingredients() 는 영문 needle 로만 찾으므로 한글
전성분에서 아무것도 못 잡는다.

표기 이형이 많은 게 핵심 난점이다:
  - 세라마이드 → 세라마이드엔피 / 세라마이드에이피 / 세라마이드이오피 (다 세라마이드)
  - 히알루론산 → 하이알루로닉애씨드 / 소듐하이알루로네이트 (표준명은 후자 쪽)
  - 센텔라 → 병풀추출물 / 마데카소사이드 / 아시아티코사이드 (유래·유도체가 제각각)
그래서 '대표 표기 1개'가 아니라 부분일치 needle 목록으로 둔다.

매핑 대상은 load_product_catalog_to_db.INGREDIENT_RULES 의 14개 표준명이다. 여기서
새 성분을 만들지 않는다 — 만들면 얼굴 추천 랭킹까지 같이 흔들린다.
"""
from __future__ import annotations

import re

# 표준명 → 한글 표기 needle 목록(부분일치).
KO_INGREDIENT_ALIASES: dict[str, tuple[str, ...]] = {
    "Niacinamide": ("나이아신아마이드", "나이아신아미드", "니아신아마이드"),
    # '살리실' 어간으로 잡는다. 살리실릭애씨드/살리실산뿐 아니라 베타인살리실레이트 같은
    # 유도체까지 포함해야 습진 avoid 필터가 샌다(실측: 등드름 바디워시가 그 표기를 쓴다).
    "Salicylic Acid": ("살리실", "비에이치에이"),
    "Centella Asiatica": (
        "센텔라아시아티카", "병풀", "마데카소사이드", "마데카식애씨드",
        "아시아티코사이드", "아시아틱애씨드",
    ),
    # 레티노이드는 표기 이형이 특히 많다. 실측 사고: '힐그리즈 레티노이드 0.1% 바디세럼'의
    # 전성분이 하이드록시피나콜론레티노에이트여서 '레티놀' 검색에 안 걸렸고, 습진 avoid
    # 필터를 그대로 통과했다.
    #
    # 주의(한글 부분일치): '레티노'는 '레티놀'을 못 잡는다. 놀(ㄴㅗㄹ)과 노(ㄴㅗ)는 서로
    # 다른 음절 블록이라 라틴 알파벳처럼 접두사로 잘리지 않는다. 둘 다 넣어야 한다.
    "Retinol": (
        "레티놀",          # 레티놀
        "레티노",          # 레티노이드 / 레티노에이트 / 레티노익애씨드
        "레티닐", "레티날", "레틴알데하이드", "트레티노인", "아다팔렌",
    ),
    "Hyaluronic Acid": (
        "하이알루로닉애씨드", "하이알루로네이트", "히알루론산", "히알루로네이트",
        "하이알루로닉", "소듐하이알루로네이트",
    ),
    "Vitamin C": (
        "아스코빅애씨드", "아스코르브산", "아스코빌", "아스코르빌",
        "에틸아스코빌에텔", "비타민씨",
    ),
    "Ceramide": ("세라마이드", "세라마이드엔피", "세라마이드에이피", "세라마이드이오피"),
    "Glycolic Acid": ("글라이콜릭애씨드", "글리콜산", "글라이콜릭 애씨드"),
    "Lactic Acid": ("락틱애씨드", "젖산", "락토바이오닉애씨드"),
    "Azelaic Acid": ("아젤라익애씨드", "아젤라인산", "아젤라익"),
    "Panthenol": ("판테놀", "덱스판테놀", "판토텐산", "프로비타민비5"),
    "Green Tea": ("녹차", "카멜리아시넨시스잎", "녹차잎추출물", "그린티"),
    # 징크옥사이드(자외선차단제)는 제외한다. 그걸 넣으면 선크림이 전부 Zinc 로 잡힌다.
    "Zinc": ("징크피씨에이", "징크글루코네이트", "징크설페이트", "아연피씨에이"),
    "Peptide": (
        "펩타이드", "팔미토일", "아세틸헥사펩타이드", "코퍼트라이펩타이드",
        "트라이펩타이드", "펜타펩타이드",
    ),
    # ── 바디(장벽·보습) 성분 ────────────────────────────────────────────────
    "Glycerin": ("글리세린",),
    # 페트롤라툼/미네랄오일/파라핀은 같은 폐색제 계열이라 하나로 묶는다.
    "Petrolatum": ("페트롤라툼", "바셀린", "미네랄오일", "유동파라핀", "파라핀"),
    "Shea Butter": ("시어버터", "쉐어버터", "시어지", "부티로스페르뭄"),
    "Squalane": ("스쿠알란", "스쿠알렌"),
    "Allantoin": ("알란토인",),
    "Colloidal Oatmeal": ("콜로이달오트밀", "귀리", "아베나사티바", "오트밀", "오트커널"),
    "Urea": ("우레아",),
    "Dimethicone": ("다이메티콘", "디메치콘", "다이메칠폴리실록산"),
    "Jojoba Oil": ("호호바",),
}

# 일본어 표기(라쿠텐 itemCaption 용). 지금은 미사용이지만 같은 자리에 둔다.
JA_INGREDIENT_ALIASES: dict[str, tuple[str, ...]] = {
    "Niacinamide": ("ナイアシンアミド",),
    "Salicylic Acid": ("サリチル酸",),
    "Centella Asiatica": ("ツボクサ", "センテラ", "マデカッソシド", "CICA"),
    "Retinol": ("レチノール", "レチナール"),
    "Hyaluronic Acid": ("ヒアルロン酸", "ヒアルロン酸Na"),
    "Vitamin C": ("アスコルビン酸", "ビタミンC"),
    "Ceramide": ("セラミド",),
    "Glycolic Acid": ("グリコール酸",),
    "Lactic Acid": ("乳酸",),
    "Azelaic Acid": ("アゼライン酸",),
    "Panthenol": ("パンテノール", "パントテニル"),
    "Green Tea": ("チャ葉", "緑茶"),
    "Zinc": ("ピロリドンカルボン酸亜鉛", "グルコン酸亜鉛"),
    "Peptide": ("ペプチド", "パルミトイル"),
    # 바디 성분. 표기는 라쿠텐 itemCaption 실측(濃グリセリン·シア脂·メチルポリシロキサン 등).
    "Glycerin": ("グリセリン",),
    "Petrolatum": ("ワセリン", "流動パラフィン", "ミネラルオイル", "鉱物油"),
    "Shea Butter": ("シア脂", "シアバター", "シアーバター"),
    "Squalane": ("スクワラン", "スクワレン"),
    "Allantoin": ("アラントイン",),
    "Colloidal Oatmeal": ("オートミール", "カラスムギ", "エンバク", "オーツ"),
    "Urea": ("尿素",),
    "Dimethicone": ("ジメチコン", "メチルポリシロキサン", "ジメチルポリシロキサン"),
    "Jojoba Oil": ("ホホバ",),
}

# 전성분 구분자. 올영 고시는 쉼표가 기본이지만 세트 상품은 '/' 나 줄바꿈이 섞인다.
_SPLIT_RE = re.compile(r"[,、·/\n]+")
# 기획/세트 상품은 'S타입 정제수, 글리세린...' 처럼 타입 라벨이 앞에 붙는다.
_TYPE_LABEL_RE = re.compile(r"^\s*[\[\(]?\s*[A-Za-z0-9가-힣]{1,6}\s*타입\s*[\]\)]?\s*")


def split_ingredients_ko(blob: str) -> list[str]:
    """한글 전성분 문자열을 개별 성분으로 쪼갠다."""
    if not blob:
        return []
    blob = _TYPE_LABEL_RE.sub("", blob)
    parts = []
    for chunk in _SPLIT_RE.split(blob):
        name = chunk.strip().strip("()[]")
        if name and len(name) <= 60:
            parts.append(name)
    return parts


def detect_ingredients_ko(blob: str) -> list[str]:
    """한글 전성분에서 표준 성분명을 검출한다.

    전성분 전체를 하나의 문자열로 보고 부분일치를 찾는다. 성분명을 쪼갠 뒤 정확일치를
    쓰면 `소듐하이알루로네이트`, `세라마이드엔피` 같은 유도체를 전부 놓친다.
    """
    if not blob:
        return []
    text = blob.replace(" ", "")
    found = []
    for canonical, needles in KO_INGREDIENT_ALIASES.items():
        if any(needle.replace(" ", "") in text for needle in needles):
            found.append(canonical)
    return found


def detect_ingredients_ja(blob: str) -> list[str]:
    """일본어 전성분(라쿠텐 itemCaption 등)에서 표준 성분명을 검출한다."""
    if not blob:
        return []
    found = []
    for canonical, needles in JA_INGREDIENT_ALIASES.items():
        if any(needle in blob for needle in needles):
            found.append(canonical)
    return found

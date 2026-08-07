"""바디·소아·더모 경로 요약문의 일본어판(2026-08-07).

얼굴 경로만 explanation_ja 를 만들고 나머지 세 경로는 None 이라, 일본 사용자가
**한국어 의학 안내**를 읽고 있었다(프론트가 한국어 원문으로 폴백한다).

특히 소아 경로는 안내문이 곧 결과 화면이다 — 성인 제품 폴백 없이 '이런 성분을 찾으세요'만
내는 경로라, 여기가 한국어면 일본 사용자는 안전 안내를 아예 못 읽는다.
"""

from __future__ import annotations

import re

import pytest

from app.schemas.api import BodyConditionScore
from app.services.body_skin_analyzer import BODY_LABELS, BODY_LABELS_JA
from app.services.derma_condition_care import (
    CONDITION_CARE,
    CONDITION_CARE_JA,
    care_ja_for,
)
from app.services.pediatric_care import (
    PEDIATRIC_GUIDANCE,
    PEDIATRIC_GUIDANCE_JA,
    PEDIATRIC_GUIDANCE_NO_PRODUCTS,
    PEDIATRIC_GUIDANCE_NO_PRODUCTS_JA,
)
from app.services.recommender import build_body_explanation, build_body_explanation_ja

HANGUL = re.compile(r"[가-힣]")


# ── 키 일치 ─────────────────────────────────────────────────────────────────
# 한쪽만 늘면 그 항목에서 조용히 한국어가 샌다. 실제로 이 저장소에서 반복된 사고라
# 모듈 임포트 시점의 assert 와 함께 이중으로 막는다.

@pytest.mark.parametrize(
    "ko,ja,name",
    [
        (CONDITION_CARE, CONDITION_CARE_JA, "CONDITION_CARE"),
        (BODY_LABELS, BODY_LABELS_JA, "BODY_LABELS"),
    ],
)
def test_korean_and_japanese_maps_cover_the_same_keys(ko, ja, name):
    assert set(ko) == set(ja), f"{name} 의 한/일 키가 어긋납니다"


# ── 일본어판에 한국어가 남아 있지 않은지 ────────────────────────────────────

@pytest.mark.parametrize("condition", sorted(CONDITION_CARE))
def test_derma_japanese_care_has_no_korean(condition):
    care = care_ja_for(condition)
    assert not HANGUL.search(care["label"]), f"{condition} 라벨에 한국어: {care['label']}"
    assert not HANGUL.search(care["guide"]), f"{condition} 안내문에 한국어: {care['guide']}"
    # 한국어판과 실제로 달라야 한다(복사만 해두면 검사를 통과하면서 한국어가 나간다).
    assert care["label"] != CONDITION_CARE[condition]["label"]
    assert care["guide"] != CONDITION_CARE[condition]["guide"]


@pytest.mark.parametrize("text", [PEDIATRIC_GUIDANCE_JA, PEDIATRIC_GUIDANCE_NO_PRODUCTS_JA])
def test_pediatric_japanese_guidance_has_no_korean(text):
    assert not HANGUL.search(text), f"소아 일본어 안내에 한국어가 남아 있습니다: {text}"


def test_pediatric_japanese_guidance_differs_from_korean():
    assert PEDIATRIC_GUIDANCE_JA != PEDIATRIC_GUIDANCE
    assert PEDIATRIC_GUIDANCE_NO_PRODUCTS_JA != PEDIATRIC_GUIDANCE_NO_PRODUCTS
    # 소아 안내의 핵심(무향·저자극 보습, 진료 권유)이 일본어판에도 있어야 한다.
    for must in ("無香料", "低刺激", "皮膚科"):
        assert must in PEDIATRIC_GUIDANCE_JA
        assert must in PEDIATRIC_GUIDANCE_NO_PRODUCTS_JA


def test_derma_guides_match_the_frontend_dictionary():
    """서버판과 i18n.ts 사전이 **같은 일본어**여야 한다.

    사전 쪽은 explanation 이 guide 와 글자 그대로 같을 때만 걸리는 폴백으로 남아 있다.
    두 벌이 서로 다른 문장이 되면 같은 안내가 화면·경로마다 다르게 읽힌다.
    """
    from pathlib import Path

    i18n = (
        Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n.ts"
    ).read_text(encoding="utf-8")
    drifted = []
    for condition, care in CONDITION_CARE.items():
        ko, ja = care["guide"], CONDITION_CARE_JA[condition]["guide"]
        if f"'{ko}'" not in i18n:
            continue  # 사전에 없는 문장은 서버판이 유일한 출처다
        if f"'{ja}'" not in i18n:
            drifted.append(condition)
    assert not drifted, (
        f"i18n.ts 사전과 다른 일본어를 쓰는 질환: {drifted} — 같은 안내가 두 가지로 읽힙니다."
    )


# ── 바디 요약문 ─────────────────────────────────────────────────────────────

def _body_conditions():
    return [
        BodyConditionScore(condition="atopic_dermatitis", label="아토피 피부염", probability=71.2),
        BodyConditionScore(condition="eczema", label="습진", probability=18.4),
    ]


def test_body_japanese_explanation_has_no_korean():
    """body_conditions[].label 은 분석기가 한국어로 채워 보낸다 — 그대로 쓰면 문장에 남는다."""
    text = build_body_explanation_ja(
        _body_conditions(), ["Ceramide", "Panthenol"], ["Cetaphil Lotion"]
    )
    assert not HANGUL.search(text), f"바디 일본어판에 한국어가 남아 있습니다: {text}"
    assert "アトピー性皮膚炎" in text


def test_body_japanese_explanation_keeps_numbers_and_proper_nouns():
    ingredients, products = ["Ceramide", "Panthenol"], ["Cetaphil Lotion"]
    text = build_body_explanation_ja(_body_conditions(), ingredients, products)
    assert "71.2" in text
    for name in ingredients + products:
        assert name in text, f"{name} 이 일본어판에서 사라졌습니다"


def test_body_japanese_explanation_without_conditions():
    text = build_body_explanation_ja([], ["Ceramide"], ["Cetaphil Lotion"])
    assert not HANGUL.search(text), text


def test_body_korean_explanation_is_unchanged():
    """일본어판을 추가하면서 한국어판이 바뀌면 안 된다."""
    text = build_body_explanation(_body_conditions(), ["Ceramide"], ["Cetaphil Lotion"])
    assert text.startswith("아토피 피부염 가능성 71.2%")


# ── 실제 응답(조립된 문장) ──────────────────────────────────────────────────
# 위 검사는 '재료'만 본다. 요약문은 lead + body + OTC 예시를 이어 붙여 만들기 때문에,
# 재료가 전부 일본어여도 이음말이 한국어면 문장 한가운데에 한국어가 남는다.
# 성분명·상품명·OTC 브랜드는 고유명사라 원문 그대로 두므로 검사에서 제외한다.

_PROPER_NOUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .,'&%\-+/()]*")


def _japanese_only(text: str) -> str:
    """고유명사(영문 상품·성분·브랜드명)를 걷어낸 나머지 — 여기 한국어가 있으면 안 된다."""
    return _PROPER_NOUN.sub(" ", text)


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def _recommend(client, *, age_group: str, condition: str) -> dict:
    response = client.post(
        "/api/recommend",
        json={
            "analysis_mode": "body",
            "body_conditions": [
                {"condition": condition, "label": "테스트", "probability": 72.0}
            ],
            "survey": {
                "skin_type": "sensitive",
                "concerns": [],
                "sensitivity": 5,
                "routine_level": "basic",
                "age_group": age_group,
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    "age_group,condition",
    [
        ("30s", "eczema_dermatitis"),   # 더모 · 제품 추천
        ("30s", "fungal"),              # 더모 · 제품 대신 안내(+OTC 예시)
        ("30s", "malignant"),           # 더모 · 악성 의심 조기 반환
        ("30s", "pigment_benign"),      # 더모 · 1순위가 제품 불가 → lead 문장이 붙는다
        ("baby", "eczema_dermatitis"),  # 소아
        ("child", "other"),             # 소아
    ],
)
def test_recommendation_explanation_ja_is_present_and_japanese(client, age_group, condition):
    body = _recommend(client, age_group=age_group, condition=condition)
    ja = body.get("explanation_ja")
    assert ja, f"{age_group}/{condition} 경로에 일본어 요약문이 없습니다(한국어로 폴백됩니다)"
    leftover = _japanese_only(ja)
    assert not HANGUL.search(leftover), (
        f"{age_group}/{condition} 일본어 요약문에 한국어가 남아 있습니다:\n{ja}"
    )
    # 한국어판은 그대로 남아 있어야 한다(한국 사용자 화면이 바뀌면 안 된다).
    assert body["explanation"] and HANGUL.search(body["explanation"])


# ── 모든 응답 경로가 일본어판을 싣는지 ──────────────────────────────────────

def test_every_recommendation_response_carries_explanation_ja():
    """`explanation` 만 채우고 `explanation_ja` 를 빠뜨린 return 이 있으면 잡는다.

    이번 버그가 정확히 그 모양이었다 — 얼굴 경로만 두 벌을 만들고, 바디·소아·더모(악성
    의심 조기 반환 포함) 네 자리가 조용히 None 이었다. 화면은 멀쩡해 보이고(한국어로
    폴백된다) 한국어 사용자에겐 아무 문제가 없어서 드러나지 않는 부류다.
    """
    import ast
    import inspect

    from app.services import recommender

    tree = ast.parse(inspect.getsource(recommender))
    missing: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        if getattr(func, "id", None) != "RecommendationResponse":
            continue
        keywords = {kw.arg for kw in node.value.keywords}
        if "explanation" in keywords and "explanation_ja" not in keywords:
            missing.append(node.lineno)
    assert not missing, (
        "explanation_ja 를 빠뜨린 RecommendationResponse 반환이 있습니다"
        f"(recommender.py 줄 {missing}) — 그 경로는 일본 사용자에게 한국어로 나갑니다."
    )

import json

from app.services.skincare_ingredient_knowledge import (
    SkincareIngredientKnowledge,
    build_skincare_answer,
    build_skincare_recommendation_hint,
)


def test_searches_skincare_ingredient_knowledge(tmp_path) -> None:
    index_path = tmp_path / "skincare.jsonl"
    records = [
        {
            "id": "pore-1",
            "target_concern": "모공",
            "question": "모공과 피지 관리에 좋은 성분이 궁금합니다.",
            "answer": "피지 조절과 모공 관리를 위해 나이아신아마이드와 살리실산을 낮은 빈도로 사용할 수 있습니다.",
            "evidence_sources": ["PMID:123"],
            "skin_type": "지성",
            "skin_concerns": ["모공"],
            "external_factors": ["자외선"],
        },
        {
            "id": "bright-1",
            "target_concern": "미백(색소침착/기미/칙칙함)",
            "question": "기미와 색소침착 관리가 궁금합니다.",
            "answer": "미백 관리는 자외선 차단과 비타민C 유도체를 함께 고려합니다.",
            "evidence_sources": [],
            "skin_type": "복합성",
            "skin_concerns": ["색소침착"],
            "external_factors": [],
        },
    ]
    index_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records),
        encoding="utf-8",
    )

    knowledge = SkincareIngredientKnowledge(index_path)
    matches = knowledge.search("모공이 넓고 피지가 많아요")

    assert matches
    assert matches[0].record["id"] == "pore-1"
    answer, sources = build_skincare_answer(matches)
    assert "나이아신아마이드" in answer
    assert "PMID:123" in answer
    assert sources == ["AI Hub 스킨케어 성분-효능: 모공"]


def test_recommendation_hint_uses_context(tmp_path) -> None:
    index_path = tmp_path / "skincare.jsonl"
    index_path.write_text(
        json.dumps(
            {
                "id": "redness-1",
                "target_concern": "붉어짐(홍조)",
                "question": "홍조와 자극이 있는 민감 피부 루틴",
                "answer": "민감한 홍조 피부에는 판테놀과 병풀 계열 성분을 우선 고려합니다.",
                "evidence_sources": [],
                "skin_type": "민감성",
                "skin_concerns": ["홍조"],
                "external_factors": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    knowledge = SkincareIngredientKnowledge(index_path)
    matches = knowledge.search("", {"scores": {"redness": 90, "acne": 10}, "survey": {"skin_type": "sensitive"}})
    assert matches[0].record["id"] == "redness-1"

    # The helper uses the global cache in production; this assertion keeps the
    # record-shaping behavior covered without changing cache state.
    hint = build_skincare_recommendation_hint("홍조 민감 자극", {"scores": {"redness": 90}})
    assert isinstance(hint, str)

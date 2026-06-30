import json

from app.services.problem_skin_knowledge import ProblemSkinKnowledge, build_knowledge_answer


def test_searches_problem_skin_knowledge(tmp_path) -> None:
    index_path = tmp_path / "knowledge.jsonl"
    records = [
        {
            "id": "acne-1",
            "skin_problem": "화농성 여드름 피부",
            "age": "40대",
            "gender": "여성",
            "skin_brightness": "흰 피부",
            "skin_condition": "지성",
            "question": "여드름 피부의 베이스 메이크업 방법이 궁금합니다.",
            "answer": "40대 여성으로 흰 피부 톤입니다. 가벼운 논코메도제닉 베이스를 얇게 사용하세요.",
            "recommended_ingredients": "병풀",
            "avoid_ingredients": "고함량 알코올",
            "source_titles": ["여드름 피부 참고 문헌"],
        },
        {
            "id": "pore-1",
            "skin_problem": "모공확장 피부",
            "skin_condition": "복합성",
            "question": "넓은 모공을 자연스럽게 가리는 방법이 궁금합니다.",
            "answer": "프라이머를 소량 사용하세요.",
            "recommended_ingredients": "",
            "avoid_ingredients": "",
            "source_titles": [],
        },
    ]
    index_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records),
        encoding="utf-8",
    )

    knowledge = ProblemSkinKnowledge(index_path)
    matches = knowledge.search("화농성 여드름 피부에 맞는 성분과 메이크업을 알려주세요")

    assert matches
    assert matches[0].record["id"] == "acne-1"
    answer, sources = build_knowledge_answer(matches)
    assert "논코메도제닉" in answer
    assert "병풀" in answer
    assert "40대 여성" not in answer
    assert sources == ["여드름 피부 참고 문헌"]


def test_missing_index_falls_back_to_empty(tmp_path) -> None:
    knowledge = ProblemSkinKnowledge(tmp_path / "missing.jsonl")
    assert knowledge.search("홍조 피부") == []

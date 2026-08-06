"""성분 근거 문단의 일본어 처리.

일본몰 결과지에 이 문단이 **한국어 그대로** 나갔다(제보 2026-08-06).
본문은 개인화된 산문 8,341건(약 300만 자)이라 사전으로 못 옮긴다 → id 로 1:1 대응하는
번역 코퍼스를 별도 파일로 붙인다(scripts/translate_ingredient_knowledge_ja.py).

여기서 지키는 규칙: **번역이 없으면 한국어를 대신 보여주지 않고 문단을 생략한다.**
정보가 하나 빠지는 것보다 일본 사용자에게 한국어 의학 안내가 나가는 쪽이 나쁘다.
"""

from __future__ import annotations

import json
import re

import pytest

import app.services.skincare_ingredient_knowledge as knowledge

HANGUL = re.compile(r"[가-힣]")


@pytest.fixture(autouse=True)
def _clear_cache():
    knowledge._ja_answers.cache_clear()
    yield
    knowledge._ja_answers.cache_clear()


def _first_matching_record():
    """실제 검색에 걸리는 레코드 하나(코퍼스가 없으면 스킵)."""
    matches = knowledge.get_skincare_ingredient_knowledge().search("모공 피지", None, limit=1)
    if not matches or matches[0].score < 2:
        pytest.skip("성분 지식 코퍼스가 없어 스킵")
    return matches[0].record


def test_japanese_hint_is_empty_without_translation(monkeypatch):
    _first_matching_record()
    monkeypatch.setattr(knowledge, "_ja_answers", lambda: {})
    hint = knowledge.build_skincare_recommendation_hint("모공 피지", None, lang="ja")
    assert hint == "", f"번역이 없는데 문단이 나왔습니다: {hint[:60]}"


def test_korean_hint_still_works():
    record = _first_matching_record()
    hint = knowledge.build_skincare_recommendation_hint("모공 피지", None, lang="ko")
    assert hint.startswith("성분 근거 참고:")
    assert str(record.get("target_concern", "")) in hint


def test_japanese_hint_uses_translation_when_present(monkeypatch):
    record = _first_matching_record()
    translated = {
        str(record.get("id")): {
            "id": record.get("id"),
            "target_concern": "毛穴",
            "answer": "皮脂の分泌を抑える成分を中心に、低刺激のケアから始めるのが安全です。",
        }
    }
    monkeypatch.setattr(knowledge, "_ja_answers", lambda: translated)
    hint = knowledge.build_skincare_recommendation_hint("모공 피지", None, lang="ja")
    assert hint.startswith("成分の根拠:")
    assert "毛穴" in hint
    assert not HANGUL.search(hint), f"일본어 문단에 한국어가 섞였습니다: {hint}"


def test_translation_file_is_keyed_by_id(tmp_path, monkeypatch):
    """번역본은 id 로 붙는다. 파일이 없어도 기능은 그대로 돌아야 한다."""
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "skincare_ingredient_knowledge_path_ja", str(tmp_path / "none.jsonl"))
    knowledge._ja_answers.cache_clear()
    assert knowledge._ja_answers() == {}

    path = tmp_path / "some.jsonl"
    path.write_text(json.dumps({"id": "abc", "answer": "テスト"}, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(settings, "skincare_ingredient_knowledge_path_ja", str(path))
    knowledge._ja_answers.cache_clear()
    assert knowledge._ja_answers()["abc"]["answer"] == "テスト"


def test_japanese_search_is_restricted_to_translated_records(monkeypatch):
    """일본어는 **번역된 것 중에서** 최적 매칭을 고른다.

    전체 1등을 뽑고 나서 번역 유무를 보면, 번역이 있는 차선책을 두고도 문단이 빠진다.
    여기서는 전체 1등이 아닌 레코드 하나만 번역해 두고, 그게 선택되는지 본다.
    """
    kn = knowledge.get_skincare_ingredient_knowledge()
    top = kn.search("모공 피지", None, limit=5)
    if len(top) < 2:
        pytest.skip("후보가 부족해 스킵")

    runner_up = top[1].record  # 1등이 아닌 것
    assert str(runner_up.get("id")) != str(top[0].record.get("id"))

    monkeypatch.setattr(knowledge, "_ja_answers", lambda: {
        str(runner_up.get("id")): {
            "id": runner_up.get("id"),
            "target_concern": "毛穴",
            "answer": "皮脂ケアを中心に整えます。",
        }
    })
    hint = knowledge.build_skincare_recommendation_hint("모공 피지", None, lang="ja")
    assert hint.startswith("成分の根拠:"), "번역된 차선책이 있는데 문단이 빠졌습니다"
    assert "皮脂ケアを中心に整えます。" in hint


def test_korean_still_picks_the_overall_best(monkeypatch):
    """한국어는 번역 여부와 무관하게 전체 1등을 그대로 쓴다."""
    kn = knowledge.get_skincare_ingredient_knowledge()
    top = kn.search("모공 피지", None, limit=1)
    if not top or top[0].score < 2:
        pytest.skip("코퍼스가 없어 스킵")
    monkeypatch.setattr(knowledge, "_ja_answers", lambda: {})
    hint = knowledge.build_skincare_recommendation_hint("모공 피지", None, lang="ko")
    assert str(top[0].record.get("target_concern", "")) in hint

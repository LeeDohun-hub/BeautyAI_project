"""서버가 값을 끼워 조립하는 '한국어 문장'의 전수 목록을 고정한다(2026-08-07).

왜 필요한가
  프론트 사전(i18n.ts)은 **문장 전체가 키와 글자 그대로 같을 때만** 걸린다. 서버가 숫자·이름을
  끼워 만든 문장은 완성형이 매번 달라 조회가 항상 실패하고, 일본어 모드에서 한국어가 그대로
  나간다. 이 부류는 화면이 멀쩡해 보이고 기존 테스트도 통과한다 — 한국어 사용자에게는
  아무 문제가 없어서 드러나지 않는다.

  실제로 이 저장소에서 반복됐다:
    · 2026-08-06 추천 요약문(얼굴)
    · 2026-08-07 바디·소아·더모 요약문, 가상성형 5단계 결과지, 상담 답변 전체,
      소아 컬럼 제목, 얼굴 피부분석 요약

  그래서 '전부 찾아 고쳤다'로 끝내지 않고, **새로 생기면 분류하도록 강제**한다.
  이 테스트가 실패하면 새 조립형 문장이 생긴 것이다 — 화면에 나가는지 보고,
  나간다면 일본어 경로를 만든 뒤 아래 목록에 이유와 함께 등록할 것.

무엇을 세지 않는가
  화면에 안 나가는 것(로그·예외 메시지·죽은 코드)도 목록에는 남긴다. '왜 괜찮은지'를
  적어 두는 것이 다음 사람에게 정보이기 때문이다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

BACKEND_APP = Path(__file__).resolve().parents[1] / "app"
HANGUL = re.compile(r"[가-힣]")

# 조립형 한국어 문장 → 왜 괜찮은지(일본어 경로) 또는 왜 화면에 안 나가는지.
# 키는 (파일 경로, 값 자리를 {} 로 지운 뼈대). 줄 번호는 넣지 않는다 — 코드가 움직여도
# 목록이 흔들리면 안 되기 때문이다.
HANDLED: dict[tuple[str, str], str] = {
    # ── 화면에 나가고, 일본어 경로가 있다 ──────────────────────────────────
    ("services/recommender.py", "가장 두드러진 피부 신호는 {}입니다. {}와 선택한 고민을 기준으로 {} 성분을 우선 추천했습니다. 추천 제품은 {} 등입니다."):
        "build_explanation_ja",
    ("services/recommender.py", "{}를 기준으로 피부 장벽과 보습 중심의 성분 {}을 우선했습니다. 자극 가능성이 있는 레티놀과 AHA/BHA 성분 제품은 제외했습니다. 추천 제품은 {}입니다."):
        "build_body_explanation_ja",
    ("services/recommender.py", "{}에 적합한 {} 성분 중심으로 골랐습니다. {}"):
        "recommend_derma_care 가 explanation_ja 를 나란히 조립",
    ("services/recommender.py", "{}은(는) 제품으로 해결하기 어렵습니다. 함께 감지된 {} 기준으로 제품을 추천합니다."):
        "recommend_derma_care lead_ja",
    ("services/recommender.py", "약국 OTC 예시(미국 FDA 기준): {}. 사용 전 약사와 상담하세요."):
        "recommend_derma_care explanation_ja",
    ("services/recommender.py", "추천 제품: {}."):
        "recommend_derma_care body_ja",
    ("services/recommender.py", "{} (순한 성분)"):
        "프론트 tColumnLabel 이 라벨/접미사를 나눠 옮긴다",
    ("services/recommender.py", "{}개 바디 진정 성분"):
        "프론트 tReasonTag 의 '{n}개 {label}' 갈래",
    ("services/skincare_ingredient_knowledge.py", "성분 근거 참고: {}에는 {}"):
        "같은 함수의 lang='ja' 갈래('成分の根拠')",
    ("services/skincare_ingredient_knowledge.py", "{} 성분 근거: {}"):
        "일본어판 문장 자체",
    ("services/skincare_ingredient_knowledge.py", "YoPalette 자체 모델 분석에 따르면, {} 케이스에서는 {}"):
        "build_skincare_answer_ja",
    ("services/skincare_ingredient_knowledge.py", "참고 근거: {}."):
        "build_skincare_answer_ja ('参考根拠')",
    ("services/skincare_ingredient_knowledge.py", "YoPalette 성분·효능 분석: {}"):
        "build_skincare_answer_ja 의 sources",
    ("services/chatbot.py", "{}{} 기능성 성분은 한 번에 하나씩 추가하고, 피부가 민감하다면 패치 테스트를 먼저 권장합니다."):
        "answer_skin_question 의 ja 갈래(KNOWLEDGE_BASE_JA)",
    ("services/chatbot.py", "최근 분석 점수를 기준으로는 {} 관리에 조금 더 집중해 보세요."):
        "answer_skin_question 의 ja 갈래(TARGET_LABELS_JA)",
    ("services/virtual_surgery_simulator.py", "{} 폭을 약 {}% 정리했습니다."):
        "프론트 tSurgeryDetail",
    ("services/virtual_surgery_simulator.py", "콧방울 폭을 약 {}% 좁히고 콧대에 하이라이트를 얹었습니다."):
        "프론트 tSurgeryDetail",
    ("services/virtual_surgery_simulator.py", "사진에서 자동 후보 {}개를 찾았습니다. 사용자가 직접 누른 위치만 제거하는 방식으로 신뢰도를 높일 수 있습니다."):
        "프론트 tSurgeryDetail(결과지도 이 경로를 탄다 — 2026-08-07 수정)",
    ("services/dermatology_analyzer.py", "양성으로 보이며 {} 계열 가능성이 있습니다. 케어·상담 안내용이며 확정 진단은 아닙니다."):
        "프론트 tScreeningSummary",
    ("services/skin_analyzer.py", "우선 관리가 필요한 항목은 {}입니다."):
        "프론트 tScreeningSummary('{items}' 갈래 — 2026-08-07 추가)",
    ("api/routes.py", "사진 속 컬러는 '{}'에 가장 가깝습니다({})."):
        "프론트 tScreeningSummary 네일 갈래",
    ("services/personal_color_analyzer.py", "{} 피부 밝기와 {} 대비, {}를 종합해 {} 타입으로 판정했습니다."):
        "skin_summary_ja",
    ("services/personal_color_analyzer.py", "{} 피부 밝기와 {} 대비, {}와 로지한 혈색을 종합해 {} 타입으로 판정했습니다."):
        "skin_summary_ja",
    ("services/personal_color_analyzer.py", "{} 피부 밝기와 {} 대비, {}이 감지되어 {} 경향으로 분석했습니다."):
        "skin_summary_ja",
    ("services/personal_color_analyzer.py", "{}로 판정했지만 {}와 매우 가까운 경계 결과입니다."):
        "decision_note_ja",
    ("services/personal_color_analyzer.py", "주 타입은 {}이며, 보조 경향은 {} 쪽에 가깝습니다."):
        "decision_note_ja",
    ("services/personal_color_analyzer.py", "최종 타입은 {}입니다. 사진별 결과 흔들림이 있어 {} 경향도 함께 참고하세요."):
        "decision_note_ja",
    ("services/personal_color_analyzer.py", "{} 기준으로 어울리는 색을 정리했습니다."):
        "같은 자리에서 skin_summary_ja 를 '{label}' 자리표시자로 함께 채운다",

    # ── 화면에 나가지만 목록 뒤쪽이라 실제로는 안 보인다 ────────────────────
    ("services/personal_color_analyzer.py", "조명이 색을 왜곡한 사진 {}장은 판정에서 제외했습니다."):
        "advice 의 뒤쪽에 붙는다(프론트는 advice[0]=profile.advice 만 렌더). "
        "advice 를 전체 렌더하게 되면 일본어 경로가 필요하다.",

    # ── 화면에 안 나간다 ───────────────────────────────────────────────────
    ("services/body_skin_analyzer.py", "몸 피부 이미지 분류 결과는 {} 가능성 {}%로 나타났습니다. {}이는 6개 피부질환 범주 사이의 비교 결과이며 확정 진단이 아닙니다."):
        "BodySkinAnalyzer 는 어디서도 쓰이지 않는다(바디는 DermatologyAnalyzer 경로).",
    ("services/problem_skin_knowledge.py", "YoPalette 자체 모델 분석에 따르면, {} 케이스에서는 {}"):
        "일본어 상담은 이 코퍼스를 조회하지 않는다(번역본 없음 — chatbot 에서 건너뛴다).",
    ("services/problem_skin_knowledge.py", "권장 성분: {}."):
        "위와 같음",
    ("services/problem_skin_knowledge.py", "피하는 편이 좋은 성분: {}."):
        "위와 같음",
    ("services/problem_skin_knowledge.py", "YoPalette 피부 상담 분석 {}"):
        "위와 같음",
    ("core/database.py",
     "운영 DB 로 접속하려고 합니다(APP_ENV={}). - 개발용 DB 를 쓰려면 .env 의 DATABASE_URL 을 개발 DB 로 "
     "바꾸세요. - 운영 데이터를 정말 봐야 한다면 ALLOW_PRODUCTION_DB=true 를 명시하세요. - 운영 컨테이너인데 "
     "이 오류가 났다면 APP_ENV=production 이 빠진 것입니다. - 운영 마이그레이션(alembic)이라면 "
     "ALLOW_PRODUCTION_DB=true 를 붙여 실행하세요."):
        "개발자용 기동 오류 메시지(사용자 화면 아님).",
    ("services/nail_design_index.py", "임베딩 가중치를 찾을 수 없습니다: {}"):
        "개발자용 예외 메시지.",
    ("services/nail_palette.py", "NAIL_SHADE_HEX 에 '{}' 이 없습니다 — PROFILES 에 색이름을 추가했다면 여기도 채우세요."):
        "개발자용 예외 메시지.",
}

# skn16 패키지는 통째로 제외한다.
#   · 한국어 문장을 만드는 classify()/format_result() 를 앱이 호출하지 않는다
#     (skn16_classifier 는 extract_robust_lab_features / classify_subtype_relative / predict_proba 만 쓴다)
#   · [DEBUG]/[디버그] 출력은 skn16_classifier 가 redirect_stdout 으로 삼켜 화면에 못 간다
SKIPPED_DIRS = ("ai/skn16/",)


def _skeleton(node: ast.JoinedStr) -> str:
    parts = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        else:
            parts.append("{}")
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _inventory() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in sorted(BACKEND_APP.rglob("*.py")):
        rel = str(path.relative_to(BACKEND_APP)).replace("\\", "/")
        if any(rel.startswith(prefix) for prefix in SKIPPED_DIRS):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.JoinedStr):
                continue
            if not any(isinstance(v, ast.FormattedValue) for v in node.values):
                continue
            literal = "".join(
                v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)
            )
            if not HANGUL.search(literal) or len(literal.strip()) < 6:
                continue
            found.add((rel, _skeleton(node)))
    return found


def test_no_unclassified_assembled_korean_sentence() -> None:
    new = sorted(_inventory() - set(HANDLED))
    assert not new, (
        f"분류되지 않은 조립형 한국어 문장 {len(new)}건 —\n"
        "화면에 나가는지 확인하고, 나간다면 일본어 경로를 만든 뒤 HANDLED 에 이유와 함께 등록하세요.\n"
        "(사전만으로는 안 됩니다 — 값이 끼면 완성형이 매번 달라 조회가 실패합니다.)\n"
        + "\n".join(f"  {f}\n    {s}" for f, s in new)
    )


# ── 이어 붙여 만드는 문장 ───────────────────────────────────────────────────
# 위 검사는 f-string 만 본다. 그런데 `parts.append("...")` 를 모아 `" ".join(parts)` 하는
# 방식은 **각 조각이 평범한 문자열 리터럴**이라 거기에 안 걸린다.
# 값이 안 끼어도 결과 문장은 조건 조합마다 달라지므로, 사전으로는 똑같이 못 옮긴다 —
# 실제로 촬영 품질 안내(조합 8가지)가 일본어 모드에 한국어로 나갔다(제보 2026-08-07).

# 촬영 품질 안내(skin_analyzer._confidence_notes)는 여기 없다 — 조각을 (한국어, 일본어)
# **쌍**으로 모듈 상수에 두어 함수 안에 한국어 리터럴이 남지 않기 때문이다.
# 그 구조가 유지되는지는 test_chat_ja 쪽의 전용 검사가 본다(쌍이 깨지면 거기서 실패한다).
JOIN_HANDLED: dict[tuple[str, str], str] = {
    ("services/recommender.py", "build_product_columns"):
        "이어 붙이는 건 추천 사유 배지(태그)다. 태그별로 사전에 있고 프론트가 하나씩 옮긴다"
        "(tColumnReason → tReasonTag).",
    ("services/recommender.py", "recommend_products"):
        "위와 같음(배지 태그).",
}


def _join_inventory() -> set[tuple[str, str]]:
    """한국어 조각을 2개 이상 모아 join 하는 함수."""
    found: set[tuple[str, str]] = set()
    for path in sorted(BACKEND_APP.rglob("*.py")):
        rel = str(path.relative_to(BACKEND_APP)).replace("\\", "/")
        if any(rel.startswith(prefix) for prefix in SKIPPED_DIRS):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            has_join = any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "join"
                for n in ast.walk(func)
            )
            if not has_join:
                continue
            pieces = 0
            for node in ast.walk(func):
                targets = []
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "append":
                    targets = node.args
                elif isinstance(node, (ast.List, ast.Tuple)):
                    targets = node.elts
                for element in targets:
                    if (
                        isinstance(element, ast.Constant)
                        and isinstance(element.value, str)
                        and HANGUL.search(element.value)
                        and len(element.value.strip()) >= 6
                    ):
                        pieces += 1
            if pieces >= 2:
                found.add((rel, func.name))
    return found


def test_no_unclassified_joined_korean_sentence() -> None:
    new = sorted(_join_inventory() - set(JOIN_HANDLED))
    assert not new, (
        f"분류되지 않은 '이어 붙이는' 한국어 문장 {len(new)}건 —\n"
        "조각을 조건에 따라 이어 붙이면 결과가 조합마다 달라져 사전으로 못 옮깁니다.\n"
        "화면에 나간다면 서버가 두 벌을 만들거나(예: confidence_note_ja),\n"
        "조각 단위로 옮길 수 있게 내려보낸 뒤 JOIN_HANDLED 에 이유와 함께 등록하세요.\n"
        + "\n".join(f"  {f}  {fn}()" for f, fn in new)
    )


def test_join_handled_list_has_no_stale_entries() -> None:
    stale = sorted(set(JOIN_HANDLED) - _join_inventory())
    assert not stale, "코드에 더 이상 없는 항목이 JOIN_HANDLED 에 남아 있습니다:\n" + "\n".join(
        f"  {f}  {fn}()" for f, fn in stale
    )


def test_handled_list_has_no_stale_entries() -> None:
    """고쳐서 사라진 문장이 목록에 남아 있으면 지운다(목록이 사실과 어긋나면 신뢰를 잃는다)."""
    stale = sorted(set(HANDLED) - _inventory())
    assert not stale, "코드에 더 이상 없는 항목이 HANDLED 에 남아 있습니다:\n" + "\n".join(
        f"  {f}\n    {s}" for f, s in stale
    )

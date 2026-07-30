from sqlalchemy.orm import Session

from app.models import ChatHistory
from app.schemas.api import ChatResponse
from app.services import llm_consult
from app.services.problem_skin_knowledge import build_knowledge_answer, get_problem_skin_knowledge
from app.services.skincare_ingredient_knowledge import build_skincare_answer, get_skincare_ingredient_knowledge


# 지식베이스 채택 임계값. 점수는 (겹치는 단어 수) + 문제명 일치 8.0 + 별칭 일치 6.0 구조라,
# 예전 기준(2.0)은 **일반 단어 두 개만 겹쳐도 통과**해서 주제가 다른 답이 나갔다
# (실측: '이 퍼스널컬러에 어울리는 립 발색은?' → 민감성 피부 답변, 점수 2.70).
# 실측 분포 — 주제 맞음 9.05~24.25 / 주제 벗어남 1.25~2.70 → 6.0 이면 양쪽에 여유가 있다.
KNOWLEDGE_MIN_SCORE = 6.0

# LLM 에 넘길 '참고 자료'를 고르는 기준. 확정 답변보다 느슨하게 잡아 재료를 넓게 준다.
_RETRIEVAL_MIN_SCORE = 4.0

# 어느 지식베이스에도 걸리지 않을 때. 예전에는 KNOWLEDGE_BASE[:2](일반 안내)를 무조건
# 답으로 내보내 "모르는 걸 아는 척"했다. 출시 제품에서는 확신에 찬 오답이 무응답보다 나쁘다.
OUT_OF_SCOPE_ANSWER = (
    "그 주제는 아직 정확히 답변드리기 어려워요. "
    "지금은 피부 고민(트러블·모공·주름·홍조·색소침착·유분)과 성분·루틴 질문에 답할 수 있습니다."
)

KNOWLEDGE_BASE = [
    ("skin care guide", "클렌저, 보습제, 자외선 차단제를 기본으로 두고 기능성 성분은 천천히 추가해 보세요."),
    ("niacinamide", "나이아신아마이드는 유분, 모공, 피부 톤, 장벽 관리에 자주 선택되는 성분입니다."),
    ("salicylic acid", "살리실산은 모공 안쪽 각질을 정돈해 트러블과 유분이 고민인 피부에 도움을 줄 수 있습니다."),
    ("centella", "병풀 추출물은 홍조와 민감 피부를 진정시키는 용도로 많이 사용됩니다."),
    ("retinol", "레티놀은 주름과 피부결 관리에 도움을 주지만, 밤에 낮은 빈도부터 천천히 시작하는 것이 좋습니다."),
    ("vitamin c", "비타민 C는 색소침착과 칙칙함 관리에 쓰이며, 보통 아침 루틴에서 자외선 차단제와 함께 사용합니다."),
]

TARGET_LABELS = {
    "acne": "트러블",
    "pore": "모공",
    "wrinkle": "주름",
    "redness": "홍조",
    "pigmentation": "색소침착",
    "oiliness": "유분",
}


def _retrieve(message: str, context: dict | None) -> tuple[list[str], list[str]]:
    """상담 근거 문단과 출처를 모은다(임계값 미만이어도 참고용으로는 쓴다).

    LLM 에 넘길 재료라 채택 임계값(KNOWLEDGE_MIN_SCORE)보다 느슨하게 잡는다 — 확정 답변으로
    내보내는 게 아니라 '참고 자료'로만 쓰이고, 최종 문장은 LLM 이 쓰기 때문이다.
    """
    passages: list[str] = []
    sources: list[str] = []
    skin = get_problem_skin_knowledge().search(message, context, limit=2)
    if skin and skin[0].score >= _RETRIEVAL_MIN_SCORE:
        answer, skin_sources = build_knowledge_answer(skin)
        if answer:
            passages.append(answer)
            sources.extend(skin_sources)
    care = get_skincare_ingredient_knowledge().search(message, context, limit=2)
    if care and care[0].score >= _RETRIEVAL_MIN_SCORE:
        answer, care_sources = build_skincare_answer(care)
        if answer:
            passages.append(answer)
            sources.extend(care_sources)
    return passages, list(dict.fromkeys(sources))


def answer_skin_question(db: Session, message: str, user_id: int | None = None, context: dict | None = None) -> ChatResponse:
    # LLM 이 켜져 있으면 RAG 로 답한다 — 검색한 근거를 재료로 주고 문장은 LLM 이 쓴다.
    # 이렇게 해야 (1) 퍼스널컬러·메이크업처럼 지식베이스에 없는 주제도 답할 수 있고
    # (2) 근거가 있으면 그대로 출처로 붙어 신뢰도를 유지한다.
    if llm_consult.is_enabled():
        passages, sources = _retrieve(message, context)
        generated = llm_consult.generate(message, passages, context)
        if generated:
            db.add(ChatHistory(user_id=user_id, message=message, answer=generated))
            db.commit()
            # 근거 없이 일반 지식으로 답한 경우엔 출처를 비워 화면에 '참고 근거 없음'이 드러나게 한다.
            return ChatResponse(answer=generated, sources=sources if passages else [])
        # 호출 실패(키 만료·쿼터·네트워크)면 아래 지식베이스 경로로 그대로 폴백한다.

    knowledge_matches = get_problem_skin_knowledge().search(message, context)
    if knowledge_matches and knowledge_matches[0].score >= KNOWLEDGE_MIN_SCORE:
        answer, sources = build_knowledge_answer(knowledge_matches)
        db.add(ChatHistory(user_id=user_id, message=message, answer=answer))
        db.commit()
        return ChatResponse(answer=answer, sources=sources)

    skincare_matches = get_skincare_ingredient_knowledge().search(message, context)
    if skincare_matches and skincare_matches[0].score >= KNOWLEDGE_MIN_SCORE:
        answer, sources = build_skincare_answer(skincare_matches)
        db.add(ChatHistory(user_id=user_id, message=message, answer=answer))
        db.commit()
        return ChatResponse(answer=answer, sources=sources)

    lower = message.lower()
    matched = [item for item in KNOWLEDGE_BASE if item[0] in lower]
    if not matched:
        # 키워드조차 안 걸리면 범위 밖 질문이다 — 억지로 일반 안내를 내보내지 않는다.
        db.add(ChatHistory(user_id=user_id, message=message, answer=OUT_OF_SCOPE_ANSWER))
        db.commit()
        return ChatResponse(answer=OUT_OF_SCOPE_ANSWER, sources=[])

    context_hint = ""
    if context and context.get("scores"):
        top = sorted(context["scores"].items(), key=lambda item: item[1], reverse=True)[:2]
        focus = ", ".join(TARGET_LABELS.get(name, name) for name, _ in top)
        context_hint = f" 최근 분석 점수를 기준으로는 {focus} 관리에 조금 더 집중해 보세요."

    answer = (
        f"{matched[0][1]}{context_hint} 기능성 성분은 한 번에 하나씩 추가하고, 피부가 민감하다면 패치 테스트를 먼저 권장합니다."
    )
    db.add(ChatHistory(user_id=user_id, message=message, answer=answer))
    db.commit()
    return ChatResponse(answer=answer, sources=[name for name, _ in matched])


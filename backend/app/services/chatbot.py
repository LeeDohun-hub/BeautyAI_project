from sqlalchemy.orm import Session

from app.models import ChatHistory
from app.schemas.api import ChatResponse


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


def answer_skin_question(db: Session, message: str, user_id: int | None = None, context: dict | None = None) -> ChatResponse:
    lower = message.lower()
    matched = [item for item in KNOWLEDGE_BASE if item[0] in lower]
    if not matched:
        matched = KNOWLEDGE_BASE[:2]

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


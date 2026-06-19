from sqlalchemy.orm import Session

from app.models import ChatHistory
from app.schemas.api import ChatResponse


KNOWLEDGE_BASE = [
    ("skin care guide", "Start with cleanser, moisturizer, sunscreen, then add active ingredients slowly."),
    ("niacinamide", "Niacinamide is often chosen for oiliness, pores, tone, and barrier support."),
    ("salicylic acid", "Salicylic acid can help acne-prone and oily skin by exfoliating inside pores."),
    ("centella", "Centella asiatica is commonly used for soothing redness and sensitive skin."),
    ("retinol", "Retinol supports wrinkles and texture, but should be introduced gradually at night."),
    ("vitamin c", "Vitamin C is used for pigmentation and dullness, usually in morning routines with sunscreen."),
]


def answer_skin_question(db: Session, message: str, user_id: int | None = None, context: dict | None = None) -> ChatResponse:
    lower = message.lower()
    matched = [item for item in KNOWLEDGE_BASE if item[0] in lower]
    if not matched:
        matched = KNOWLEDGE_BASE[:2]

    context_hint = ""
    if context and context.get("scores"):
        top = sorted(context["scores"].items(), key=lambda item: item[1], reverse=True)[:2]
        context_hint = " Based on your recent scores, focus on " + ", ".join(name for name, _ in top) + "."

    answer = (
        f"{matched[0][1]}{context_hint} Introduce one active at a time and patch test if your skin is sensitive."
    )
    db.add(ChatHistory(user_id=user_id, message=message, answer=answer))
    db.commit()
    return ChatResponse(answer=answer, sources=[name for name, _ in matched])


from sqlalchemy.orm import Session

from app.models import ChatHistory
from app.schemas.api import ChatResponse
from app.services import llm_consult
from app.services.chat_catalog_answers import answer_catalog_question
from app.services.problem_skin_knowledge import build_knowledge_answer, get_problem_skin_knowledge
from app.services.skincare_ingredient_knowledge import (
    build_skincare_answer,
    build_skincare_answer_ja,
    get_skincare_ingredient_knowledge,
)


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
OUT_OF_SCOPE_ANSWER_JA = (
    "そのテーマにはまだ正確にお答えできません。"
    "現在は肌悩み（トラブル・毛穴・シワ・赤み・色素沈着・皮脂）と、成分・ルーティンのご質問にお答えできます。"
)

KNOWLEDGE_BASE = [
    ("skin care guide", "클렌저, 보습제, 자외선 차단제를 기본으로 두고 기능성 성분은 천천히 추가해 보세요."),
    ("niacinamide", "나이아신아마이드는 유분, 모공, 피부 톤, 장벽 관리에 자주 선택되는 성분입니다."),
    ("salicylic acid", "살리실산은 모공 안쪽 각질을 정돈해 트러블과 유분이 고민인 피부에 도움을 줄 수 있습니다."),
    ("centella", "병풀 추출물은 홍조와 민감 피부를 진정시키는 용도로 많이 사용됩니다."),
    ("retinol", "레티놀은 주름과 피부결 관리에 도움을 주지만, 밤에 낮은 빈도부터 천천히 시작하는 것이 좋습니다."),
    ("vitamin c", "비타민 C는 색소침착과 칙칙함 관리에 쓰이며, 보통 아침 루틴에서 자외선 차단제와 함께 사용합니다."),
]

# ⚠ 키는 KNOWLEDGE_BASE 와 같아야 한다(아래 assert 로 강제). 한쪽만 늘면 그 성분 질문에서
#   일본어 모드에 한국어 답이 나간다.
KNOWLEDGE_BASE_JA = {
    "skin care guide": "クレンザー・保湿剤・日焼け止めを基本に置き、機能性成分は少しずつ足していきましょう。",
    "niacinamide": "ナイアシンアミドは皮脂・毛穴・肌のトーン・バリアのケアによく選ばれる成分です。",
    "salicylic acid": "サリチル酸は毛穴の内側の角質を整え、トラブルや皮脂が気になる肌に役立つ可能性があります。",
    "centella": "ツボクサ（センテラ）エキスは、赤みや敏感な肌を落ち着かせる目的でよく使われます。",
    "retinol": "レチノールはシワや肌のキメのケアに役立ちますが、夜に少ない頻度からゆっくり始めるのがおすすめです。",
    "vitamin c": "ビタミンCは色素沈着やくすみのケアに使われ、通常は朝のルーティンで日焼け止めと一緒に使います。",
}
assert {key for key, _ in KNOWLEDGE_BASE} == set(KNOWLEDGE_BASE_JA)

TARGET_LABELS = {
    "acne": "트러블",
    "pore": "모공",
    "wrinkle": "주름",
    "redness": "홍조",
    "pigmentation": "색소침착",
    "oiliness": "유분",
}

TARGET_LABELS_JA = {
    "acne": "トラブル",
    "pore": "毛穴",
    "wrinkle": "シワ",
    "redness": "赤み",
    "pigmentation": "色素沈着",
    "oiliness": "皮脂",
}
assert set(TARGET_LABELS) == set(TARGET_LABELS_JA)


def _retrieve(message: str, context: dict | None, lang: str = "ko") -> tuple[list[str], list[str]]:
    """상담 근거 문단과 출처를 모은다(임계값 미만이어도 참고용으로는 쓴다).

    LLM 에 넘길 재료라 채택 임계값(KNOWLEDGE_MIN_SCORE)보다 느슨하게 잡는다 — 확정 답변으로
    내보내는 게 아니라 '참고 자료'로만 쓰이고, 최종 문장은 LLM 이 쓰기 때문이다.

    ⚠ 일본어 상담에는 **한국어 근거를 넣지 않는다.** 참고 자료가 한국어면 모델이 그 표현을
      그대로 옮겨 붙이거나 답변 언어가 흔들린다. 성분 코퍼스는 전량 번역돼 있으므로 그쪽을
      쓰고, 번역본이 없는 문제성 피부 코퍼스(problem_skin)는 일본어에서는 건너뛴다 —
      근거 문단이 하나 없는 것이 한국어가 섞이는 것보다 낫다.
    """
    ja = _is_ja(lang)
    passages: list[str] = []
    sources: list[str] = []
    if not ja:
        skin = get_problem_skin_knowledge().search(message, context, limit=2)
        if skin and skin[0].score >= _RETRIEVAL_MIN_SCORE:
            answer, skin_sources = build_knowledge_answer(skin)
            if answer:
                passages.append(answer)
                sources.extend(skin_sources)
    care = get_skincare_ingredient_knowledge().search(message, context, limit=2)
    if care and care[0].score >= _RETRIEVAL_MIN_SCORE:
        answer, care_sources = (build_skincare_answer_ja if ja else build_skincare_answer)(care)
        if answer:
            passages.append(answer)
            sources.extend(care_sources)
    return passages, list(dict.fromkeys(sources))


def _is_ja(lang: str | None) -> bool:
    return (lang or "ko").strip().lower().startswith("ja")


def answer_skin_question(
    db: Session,
    message: str,
    user_id: int | None = None,
    context: dict | None = None,
    lang: str = "ko",
) -> ChatResponse:
    """상담 답변.

    ⚠ 상담 화면은 일본어 모드에도 그대로 열려 있는데, 예전엔 모든 답변 경로가 한국어였다
      (LLM 프롬프트가 "한국어로 답합니다"를 명시했고, 폴백 지식베이스도 한국어 문장뿐).
      실측 2026-08-07 — 일본어로 물어도 한국어 답이 돌아왔다.
    """
    ja = _is_ja(lang)

    # ⚠ 카탈로그 질문은 **LLM 보다 먼저** 가로챈다. '이 상품 있나요' / '매장에 없대요, 다른 거'
    #   두 부류는 우리 DB 를 조회해야 답할 수 있는 사실 질문이라, 모델에 맡기면 없는 상품을
    #   있다고 지어낸다. 상담 오답은 다시 물으면 되지만 재고 오답은 헛걸음을 만든다.
    catalog = answer_catalog_question(db, message, context, lang)
    if catalog is not None:
        db.add(ChatHistory(user_id=user_id, message=message, answer=catalog.answer))
        db.commit()
        return catalog

    # LLM 이 켜져 있으면 RAG 로 답한다 — 검색한 근거를 재료로 주고 문장은 LLM 이 쓴다.
    # 이렇게 해야 (1) 퍼스널컬러·메이크업처럼 지식베이스에 없는 주제도 답할 수 있고
    # (2) 근거가 있으면 그대로 출처로 붙어 신뢰도를 유지한다.
    if llm_consult.is_enabled():
        passages, sources = _retrieve(message, context, lang)
        generated = llm_consult.generate(message, passages, context, lang=lang)
        if generated:
            db.add(ChatHistory(user_id=user_id, message=message, answer=generated))
            db.commit()
            # 근거 없이 일반 지식으로 답한 경우엔 출처를 비워 화면에 '참고 근거 없음'이 드러나게 한다.
            return ChatResponse(answer=generated, sources=sources if passages else [])
        # 호출 실패(키 만료·쿼터·네트워크)면 아래 지식베이스 경로로 그대로 폴백한다.

    # 문제성 피부 코퍼스는 일본어판이 없다 — 일본어 상담에서는 건너뛴다(위 _retrieve 와 같은 이유).
    if not ja:
        knowledge_matches = get_problem_skin_knowledge().search(message, context)
        if knowledge_matches and knowledge_matches[0].score >= KNOWLEDGE_MIN_SCORE:
            answer, sources = build_knowledge_answer(knowledge_matches)
            db.add(ChatHistory(user_id=user_id, message=message, answer=answer))
            db.commit()
            return ChatResponse(answer=answer, sources=sources)

    skincare_matches = get_skincare_ingredient_knowledge().search(message, context)
    if skincare_matches and skincare_matches[0].score >= KNOWLEDGE_MIN_SCORE:
        answer, sources = (build_skincare_answer_ja if ja else build_skincare_answer)(skincare_matches)
        if answer:  # 일본어판은 번역이 없으면 빈 문자열이다 — 그때는 아래로 흘려보낸다.
            db.add(ChatHistory(user_id=user_id, message=message, answer=answer))
            db.commit()
            return ChatResponse(answer=answer, sources=sources)

    lower = message.lower()
    matched = [item for item in KNOWLEDGE_BASE if item[0] in lower]
    if not matched:
        # 키워드조차 안 걸리면 범위 밖 질문이다 — 억지로 일반 안내를 내보내지 않는다.
        out_of_scope = OUT_OF_SCOPE_ANSWER_JA if ja else OUT_OF_SCOPE_ANSWER
        db.add(ChatHistory(user_id=user_id, message=message, answer=out_of_scope))
        db.commit()
        return ChatResponse(answer=out_of_scope, sources=[])

    context_hint = ""
    if context and context.get("scores"):
        top = sorted(context["scores"].items(), key=lambda item: item[1], reverse=True)[:2]
        labels = TARGET_LABELS_JA if ja else TARGET_LABELS
        focus = "、".join(labels.get(name, name) for name, _ in top) if ja else \
            ", ".join(labels.get(name, name) for name, _ in top)
        context_hint = (
            f" 最近の分析スコアを基準にすると、{focus} のケアにもう少し重点を置いてみてください。"
            if ja else
            f" 최근 분석 점수를 기준으로는 {focus} 관리에 조금 더 집중해 보세요."
        )

    if ja:
        answer = (
            f"{KNOWLEDGE_BASE_JA[matched[0][0]]}{context_hint} "
            "機能性成分は一度に一つずつ足し、肌が敏感な場合はパッチテストを先におすすめします。"
        )
    else:
        answer = (
            f"{matched[0][1]}{context_hint} 기능성 성분은 한 번에 하나씩 추가하고, 피부가 민감하다면 패치 테스트를 먼저 권장합니다."
        )
    db.add(ChatHistory(user_id=user_id, message=message, answer=answer))
    db.commit()
    return ChatResponse(answer=answer, sources=[name for name, _ in matched])


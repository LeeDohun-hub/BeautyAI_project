"""LLM 상담(RAG). 지식베이스에서 뽑은 근거로 답을 쓰게 한다.

**왜 순수 LLM 이 아니라 RAG 인가**: 지금 답변에 붙는 '참고 근거'는 실제 논문·연구 제목이라
서비스 신뢰도의 핵심 자산이다. LLM 만 쓰면 그 근거가 사라지고 피부·건강 도메인에서 환각
위험이 생긴다. 그래서 검색으로 근거를 뽑고, 그 문단을 재료로만 답을 쓰게 한다.

**키가 없으면 아무것도 하지 않는다**(`generate` → None). 호출부는 기존 지식베이스 답변으로
그대로 폴백하므로, 키 미설정 환경에서도 상담이 깨지지 않는다.
"""

from __future__ import annotations

import logging

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# 화장품 상담 범위를 벗어나지 않도록 고정하는 지침. 의료 판단·진단은 명시적으로 금지한다.
SYSTEM_PROMPT = (
    "당신은 뷰티 서비스 'YoPalette'의 상담원입니다. 화장품·스킨케어·퍼스널컬러·메이크업 범위에서만"
    " 한국어로 답합니다.\n"
    "규칙:\n"
    "1. 아래 '참고 자료'가 주어지면 그 내용을 우선 근거로 삼고, 자료에 없는 사실을 지어내지 마세요.\n"
    "2. 질병 진단·치료 판단은 하지 말고, 그런 내용이 필요하면 피부과 전문의 상담을 권하세요.\n"
    "3. 효능을 단정하지 말고 '도움이 될 수 있다'처럼 여지를 두세요.\n"
    "4. 3~5문장으로 간결하게, 실행할 수 있는 순서로 답하세요.\n"
    "5. 새 제품·성분은 소량 패치 테스트를 권하세요.\n"
    "6. 데이터셋 이름이나 내부 시스템 명칭은 언급하지 마세요."
)

# ⚠ 한국어판 프롬프트가 "한국어로 답합니다"를 **명시**하고 있어서, 일본어로 물어도 한국어
#   답이 돌아왔다(실측 2026-08-07). 상담 화면은 일본어 모드에도 그대로 열려 있다.
#   참고 자료(passages)는 일본어판 코퍼스에서 오지만, 문장을 쓰는 건 모델이므로
#   여기서 언어를 지정해야 한다.
SYSTEM_PROMPT_JA = (
    "あなたはビューティーサービス「YoPalette」の相談員です。化粧品・スキンケア・"
    "パーソナルカラー・メイクの範囲でのみ、日本語で答えます。\n"
    "ルール:\n"
    "1. 下に「参考資料」がある場合はその内容を優先的な根拠とし、資料にない事実を作らないでください。\n"
    "2. 病気の診断・治療の判断はせず、必要な場合は皮膚科専門医への相談をすすめてください。\n"
    "3. 効果を断定せず、「役立つ可能性があります」のように含みを持たせてください。\n"
    "4. 3〜5文で簡潔に、実行できる順序で答えてください。\n"
    "5. 新しい製品・成分は少量でのパッチテストをすすめてください。\n"
    "6. データセット名や内部システムの名称には触れないでください。"
)

# 사용자 정보·참고 자료·질문 머리말. 모델에게 주는 문맥이라 답변 언어와 맞춘다.
_LABELS = {
    "ko": ("사용자 정보: ", "참고 자료:\n", "질문: "),
    "ja": ("ユーザー情報: ", "参考資料:\n", "質問: "),
}

_MAX_PASSAGE_CHARS = 1200


def _client():
    settings = get_settings()
    if not settings.openai_api_key:
        return None, settings
    try:
        from openai import OpenAI
    except Exception:  # noqa: BLE001 - SDK 미설치 환경에서도 상담이 죽지 않게.
        logger.warning("openai SDK 를 불러오지 못했습니다 — 지식베이스 답변으로 폴백합니다.")
        return None, settings
    return OpenAI(api_key=settings.openai_api_key), settings


def generate(
    message: str, passages: list[str], context: dict | None = None, lang: str = "ko"
) -> str | None:
    """근거 문단을 바탕으로 상담 답변을 만든다. 키가 없거나 실패하면 None(폴백 신호).

    passages 가 비어 있어도 호출한다 — 퍼스널컬러/메이크업처럼 지식베이스에 문서가 없는
    주제는 일반 뷰티 지식으로 답하는 편이 '답변 불가'보다 낫기 때문이다. 대신 그때는
    호출부가 근거(sources)를 비워 '참고 근거 없음'이 화면에 그대로 드러난다.
    """
    client, settings = _client()
    if client is None:
        return None

    ja = (lang or "ko").lower().startswith("ja")
    user_label, ref_label, question_label = _LABELS["ja" if ja else "ko"]

    parts: list[str] = []
    if context:
        hints = {k: v for k, v in context.items() if k in {
            "personal_color", "tone", "subtype", "skin_type", "age_group", "gender",
        } and v}
        if hints:
            parts.append(user_label + ", ".join(f"{k}={v}" for k, v in hints.items()))
    if passages:
        joined = "\n---\n".join(p.strip() for p in passages if p and p.strip())
        parts.append(ref_label + joined[:_MAX_PASSAGE_CHARS])
    parts.append(f"{question_label}{message}")

    try:
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_JA if ja else SYSTEM_PROMPT},
                {"role": "user", "content": "\n\n".join(parts)},
            ],
            temperature=0.4,
            max_tokens=450,
            timeout=20,
        )
    except Exception:  # noqa: BLE001 - 네트워크/쿼터 실패는 폴백으로 흡수한다.
        logger.warning("LLM 상담 호출 실패 — 지식베이스 답변으로 폴백합니다.", exc_info=True)
        return None

    answer = (response.choices[0].message.content or "").strip()
    return answer or None


def is_enabled() -> bool:
    """LLM 상담을 쓸 수 있는 상태인지(키 설정 여부)."""
    return bool(get_settings().openai_api_key)

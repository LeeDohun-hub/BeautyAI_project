from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import get_settings


WORD_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")

CONCERN_ALIASES = {
    "acne": ("여드름", "뾰루지", "트러블", "면포", "화농"),
    "pore": ("모공", "피지", "블랙헤드"),
    "wrinkle": ("주름", "탄력", "처짐", "팔자", "노화"),
    "redness": ("홍조", "붉어짐", "민감", "자극", "아토피"),
    "pigmentation": ("미백", "색소", "기미", "칙칙", "잡티"),
    "oiliness": ("유분", "번들", "지성", "피지"),
    "dryness": ("건조", "각질", "보습", "장벽"),
}

CONCERN_TARGETS = {
    "acne": {"acne", "oiliness"},
    "pore": {"pore", "oiliness"},
    "wrinkle": {"wrinkle"},
    "redness": {"redness"},
    "pigmentation": {"pigmentation"},
    "oiliness": {"oiliness", "pore"},
    "dryness": {"redness", "wrinkle"},
}

CONTEXT_LABELS = {
    "dry": "건성 건조 보습 장벽",
    "oily": "지성 유분 피지 모공",
    "combination": "복합성 유수분 모공",
    "normal": "중성 기본",
    "sensitive": "민감 홍조 자극 장벽",
}


@dataclass(frozen=True)
class SkincareKnowledgeMatch:
    record: dict[str, Any]
    score: float


def normalize(value: str) -> str:
    return " ".join(WORD_PATTERN.findall(value.lower()))


def query_terms(value: str) -> set[str]:
    normalized = normalize(value)
    terms = {term for term in normalized.split() if len(term) >= 2}
    compact = normalized.replace(" ", "")
    for canonical, aliases in CONCERN_ALIASES.items():
        if any(alias in compact for alias in aliases):
            terms.add(canonical)
            terms.update(alias for alias in aliases if len(alias) >= 2)
    return terms


# 코퍼스 레코드의 인구통계 표기 ↔ 설문 값. 코퍼스 답변은 사례 원문이라 **첫 문장이
# 그 사례 본인의 나이·성별·피부타입으로 시작한다**("52세 복합성 피부의…").
# 그래서 검색이 인구통계에 눈감으면 34세 남성에게 "28세 여성분의…"로 시작하는 근거가 붙는다
# (실측 2026-08-10). 아래 표로 '이 사람과 같은 사례'를 우선한다.
_RECORD_GENDER = {"male": "남성", "female": "여성"}
_RECORD_SKIN_TYPE = {
    "dry": "건성",
    "oily": "지성",
    "combination": "복합성",
    "normal": "중성",
    # 민감성은 코퍼스에 별도 타입이 없다 — 맞출 수 없으니 가점도 없다(0점으로 떨어진다).
}


def _age_band(value: object) -> int | None:
    """'30s' / '34' / 34 → 30. 50대 이상은 한 묶음(코퍼스에 60대까지 있다)."""
    text = str(value or "").strip()
    if not text:
        return None
    digits = "".join(char for char in text if char.isdigit())
    if not digits:
        return None
    band = int(digits) // 10 * 10
    return 50 if band >= 50 else band


def demographic_fit(record: dict[str, Any], context: dict | None) -> float:
    """이 사례가 '지금 이 사람'과 얼마나 같은가(0~3).

    ⚠ 이 값은 score 에 더하지 않는다. 더하면 주제가 다른 사례도 인구통계만으로 임계값
      (KNOWLEDGE_MIN_SCORE)을 넘어 '확신에 찬 오답'이 나간다 — 임계값을 2.0 에서 6.0 으로
      올린 이유가 바로 그것이었다. 관련도가 엇비슷한 후보들 사이의 **순서**로만 쓴다.
    """
    survey = (context or {}).get("survey")
    if not isinstance(survey, dict):
        return 0.0
    fit = 0.0
    gender = _RECORD_GENDER.get(str(survey.get("gender") or "").lower())
    if gender and gender == str(record.get("gender") or "").strip():
        fit += 1.0
    band = _age_band(survey.get("age_group") or survey.get("age"))
    if band is not None and band == _age_band(record.get("age")):
        fit += 1.0
    skin = _RECORD_SKIN_TYPE.get(str(survey.get("skin_type") or "").lower())
    if skin and skin == str(record.get("skin_type") or "").strip():
        fit += 1.0
    return fit


def context_text(context: dict | None) -> str:
    if not context:
        return ""
    parts: list[str] = []
    survey = context.get("survey")
    if isinstance(survey, dict):
        skin_type = survey.get("skin_type")
        if skin_type:
            parts.append(CONTEXT_LABELS.get(str(skin_type), str(skin_type)))
        for key in ("concerns", "makeup_concerns", "area_concerns", "male_extras"):
            values = survey.get(key)
            if isinstance(values, list):
                parts.extend(str(value) for value in values)

    scores = context.get("scores")
    if isinstance(scores, dict):
        labels = {
            "acne": "여드름 뾰루지 트러블",
            "pore": "모공 피지",
            "wrinkle": "주름 탄력 처짐",
            "redness": "홍조 민감 자극",
            "pigmentation": "미백 색소 기미 칙칙함",
            "oiliness": "유분 지성 피지",
        }
        ranked = sorted(scores.items(), key=lambda item: float(item[1]), reverse=True)[:2]
        parts.extend(labels.get(name, name) for name, _ in ranked)
    return " ".join(parts)


class SkincareIngredientKnowledge:
    def __init__(self, index_path: str | Path | None = None) -> None:
        configured = index_path or get_settings().skincare_ingredient_knowledge_path
        path = Path(configured)
        if not path.is_absolute():
            path = get_settings().project_root / path
        self.path = path
        self.records = self._load(path)
        self._indexed = [self._prepare(record) for record in self.records]

    @staticmethod
    def _load(path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        records = []
        with path.open(encoding="utf-8") as source:
            for line in source:
                if line.strip():
                    records.append(json.loads(line))
        return records

    @staticmethod
    def _prepare(record: dict[str, Any]) -> tuple[dict[str, Any], str, str, set[str]]:
        concern = normalize(str(record.get("target_concern", "")))
        question = normalize(str(record.get("question", "")))
        metadata = normalize(
            " ".join(
                [
                    str(record.get("skin_type", "")),
                    " ".join(str(item) for item in record.get("skin_concerns", []) or []),
                    " ".join(str(item) for item in record.get("external_factors", []) or []),
                    str(record.get("answer", ""))[:800],
                ]
            )
        )
        return record, concern, question, query_terms(f"{concern} {question} {metadata}")

    # 일본어 질문 → 한국어 고민어. 코퍼스 색인은 한국어 토큰으로 만들어져 있어서, 일본어
    # 질문은 **점수가 그냥 0 이다**(실측 2026-08-07: '毛穴と皮脂が気になります' → 매칭 없음,
    # 같은 뜻의 한국어 질문은 22.25). 그래서 일본어 상담은 근거 없이 LLM 일반지식으로만
    # 답하고 있었다 — '참고 근거'는 이 서비스가 신뢰도의 핵심 자산으로 두는 것인데(llm_consult
    # 모듈 주석), 일본 사용자에게만 통째로 빠져 있었다.
    #
    # 코퍼스를 일본어로 다시 색인하지 않고, **질문에서 고민어만 한국어로 바꿔 덧붙인다.**
    # 고민 축은 8개뿐이고(target_concern), 점수의 대부분이 그 축에서 나오기 때문이다.
    # 원문도 함께 남긴다 — 성분명(레티놀/ナイアシンアミド 등)이 겹치면 그만큼 더 오른다.
    _JA_CONCERN_HINTS: tuple[tuple[str, str], ...] = (
        ("毛穴", "모공"),
        ("皮脂", "피지 유분"), ("テカリ", "피지 유분"), ("オイリー", "피지 유분"),
        ("しわ", "주름"), ("シワ", "주름"), ("小じわ", "주름"),
        ("ハリ", "탄력"), ("たるみ", "탄력 피부처짐"), ("弾力", "탄력"),
        ("ニキビ", "여드름"), ("吹き出物", "여드름"), ("肌荒れ", "여드름 트러블"),
        ("赤み", "붉어짐 홍조"), ("紅潮", "홍조"), ("敏感", "민감성"),
        ("シミ", "색소침착 미백"), ("色素沈着", "색소침착"), ("くすみ", "칙칙함 미백"),
        ("美白", "미백"), ("そばかす", "색소침착"),
        ("乾燥", "건조"), ("角質", "각질 과각질"), ("カサつき", "건조"),
        ("保湿", "보습"), ("バリア", "장벽"), ("キメ", "피부결"),
    )

    @classmethod
    def _with_ja_hints(cls, message: str) -> str:
        """일본어 질문에 대응하는 한국어 고민어를 덧붙인다(없으면 원문 그대로)."""
        text = message or ""
        hints = [ko for ja, ko in cls._JA_CONCERN_HINTS if ja in text]
        return f"{text} {' '.join(dict.fromkeys(hints))}".strip() if hints else text

    def search(
        self,
        message: str,
        context: dict | None = None,
        limit: int = 3,
        allowed_ids: set[str] | None = None,
    ) -> list[SkincareKnowledgeMatch]:
        """allowed_ids 를 주면 그 안에서만 고른다.

        일본어는 번역된 레코드만 쓸 수 있다. 전체에서 1등을 뽑고 나서 '번역이 없네'
        하고 버리면, 번역이 있는 차선책이 있어도 문단이 통째로 빠진다 —
        코퍼스 68% 번역이 사용자에겐 68% 노출로 그대로 내려앉는다.
        후보 집합을 먼저 좁히면 같은 번역량으로 노출이 거의 100% 가 된다.
        """
        # 일본어 질문이면 고민어를 한국어로 덧붙인다(색인이 한국어 토큰이라 그냥은 0점이다).
        # 한국어 질문에는 아무 영향이 없다 — 일본어 표기가 없으면 원문 그대로다.
        query = f"{self._with_ja_hints(message)} {context_text(context)}"
        terms = query_terms(query)
        normalized_query = normalize(query)
        matches: list[SkincareKnowledgeMatch] = []
        for record, concern, question, record_terms in self._indexed:
            if allowed_ids is not None and str(record.get("id", "")) not in allowed_ids:
                continue
            overlap = terms.intersection(record_terms)
            score = float(len(overlap))
            if concern and concern in normalized_query:
                score += 6.0
            for canonical, aliases in CONCERN_ALIASES.items():
                if canonical in terms and any(alias in concern for alias in aliases):
                    score += 5.0
            score += min(3.0, sum(1 for term in terms if term in question) * 0.25)
            if score > 0:
                matches.append(SkincareKnowledgeMatch(record=record, score=score))
        # 1점 버킷으로 묶어 **관련도가 엇비슷한 후보들 안에서만** 인구통계로 순서를 바꾼다.
        # 주제가 확실히 더 맞는 사례(버킷이 높은 쪽)는 인구통계와 무관하게 그대로 이긴다.
        return sorted(
            matches,
            key=lambda item: (
                round(item.score),
                demographic_fit(item.record, context),
                item.score,
            ),
            reverse=True,
        )[:limit]


@lru_cache(maxsize=1)
def get_skincare_ingredient_knowledge() -> SkincareIngredientKnowledge:
    return SkincareIngredientKnowledge()


def build_skincare_answer(matches: list[SkincareKnowledgeMatch]) -> tuple[str, list[str]]:
    if not matches:
        return "", []
    best = matches[0].record
    concern = str(best.get("target_concern", "피부 고민"))
    answer = str(best.get("answer", "")).strip()
    if len(answer) > 900:
        answer = answer[:897].rstrip() + "..."

    # 위와 같은 이유로 데이터셋 표현을 쓰지 않는다.
    sections = [f"YoPalette 자체 모델 분석에 따르면, {concern} 케이스에서는 {answer}"]
    evidence = [str(item) for item in best.get("evidence_sources", []) or [] if str(item).strip()]
    if evidence:
        sections.append(f"참고 근거: {', '.join(evidence[:3])}.")
    sections.append("피부가 예민하거나 치료 중이면 새 성분은 낮은 빈도로 패치 테스트부터 시작하는 편이 안전합니다.")

    sources: list[str] = []
    for match in matches:
        record = match.record
        label = f"YoPalette 성분·효능 분석: {record.get('target_concern', '')}".strip()
        if label not in sources:
            sources.append(label)
    return " ".join(sections), sources


def build_skincare_answer_ja(matches: list[SkincareKnowledgeMatch]) -> tuple[str, list[str]]:
    """build_skincare_answer 의 일본어판(상담 답변용).

    코퍼스는 2026-08-07 에 8,341건 전량 번역돼 **한국어와 같은 커버리지**를 갖는다. 그래서
    build_skincare_recommendation_hint 처럼 후보를 좁힐 필요 없이, 고른 레코드의 번역본을
    그대로 쓴다. 번역이 없으면 빈 문자열을 돌려 호출부가 다음 경로로 넘어가게 한다 —
    **한국어를 대신 내보내지 않는다**(일본 사용자에게 한국어 안내가 나가는 것이 더 나쁘다).

    evidence_sources 는 논문 제목이라 원문 그대로 둔다(옮기면 찾을 수 없다).
    """
    if not matches:
        return "", []
    translated_all = _ja_answers()
    best = matches[0].record
    translated = translated_all.get(str(best.get("id", "")).strip())
    if not translated:
        return "", []
    answer = str(translated.get("answer", "")).strip()
    if not answer:
        return "", []
    concern = str(translated.get("target_concern") or "肌悩み")
    if len(answer) > 900:
        answer = answer[:897].rstrip() + "..."

    sections = [f"YoPalette 独自モデルの分析によると、{concern} のケースでは {answer}"]
    evidence = [str(item) for item in best.get("evidence_sources", []) or [] if str(item).strip()]
    if evidence:
        sections.append(f"参考根拠: {', '.join(evidence[:3])}。")
    sections.append("肌が敏感なときや治療中の場合は、新しい成分は少ない頻度でパッチテストから始めると安全です。")

    sources: list[str] = []
    for match in matches:
        row = translated_all.get(str(match.record.get("id", "")).strip())
        concern_ja = str((row or {}).get("target_concern") or "").strip()
        if not concern_ja:
            continue
        label = f"YoPalette 成分・効能分析: {concern_ja}"
        if label not in sources:
            sources.append(label)
    return " ".join(sections), sources


@lru_cache(maxsize=1)
def _ja_answers() -> dict[str, dict[str, str]]:
    """한국어 코퍼스와 **id 로 1:1 대응**하는 일본어 번역본.

    본문(answer)은 개인화된 산문이라 사전으로 못 옮긴다(8,341건 · 약 300만 자).
    별도 파일로 두고 id 로 붙인다 — 원본을 건드리지 않으므로 한국어 쪽 재생성과
    번역 작업이 서로를 막지 않는다. 파일이 없으면 빈 dict 다(기능은 그대로 돈다).
    """
    configured = get_settings().skincare_ingredient_knowledge_path_ja
    path = Path(configured)
    if not path.is_absolute():
        path = get_settings().project_root / path
    if not path.is_file():
        return {}
    out: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            key = str(row.get("id", "")).strip()
            if key:
                out[key] = row
    return out


def build_skincare_recommendation_hint(
    message: str, context: dict | None = None, lang: str = "ko"
) -> str:
    knowledge = get_skincare_ingredient_knowledge()

    if lang == "ja":
        # 번역된 레코드 안에서만 고른다. 전체 1등을 뽑고 번역 유무를 나중에 보면,
        # 번역이 있는 차선책을 두고도 문단이 빠진다(코퍼스 커버리지가 그대로 노출
        # 커버리지가 된다). 후보를 먼저 좁혀 같은 번역량으로 노출을 끌어올린다.
        available = _ja_answers()
        if not available:
            return ""
        matches = knowledge.search(message, context, limit=1, allowed_ids=set(available))
        if not matches or matches[0].score < 2:
            return ""
        # ⚠ 그래도 못 찾으면 **한국어를 대신 보여주지 않고 문단을 생략한다.**
        #   일본 사용자에게 한국어 의학 안내가 나가는 것이 정보가 하나 없는 것보다 나쁘다.
        translated = available.get(str(matches[0].record.get("id", "")).strip())
        if not translated:
            return ""
        concern = str(translated.get("target_concern") or "肌悩み")
        answer = str(translated.get("answer", "")).strip()
        if not answer:
            return ""
        if len(answer) > 360:
            answer = answer[:357].rstrip() + "..."
        return f"成分の根拠: {concern}には{answer}"

    matches = knowledge.search(message, context, limit=1)
    if not matches or matches[0].score < 2:
        return ""
    best = matches[0].record
    concern = str(best.get("target_concern", "피부 고민"))
    answer = str(best.get("answer", "")).strip()
    if len(answer) > 360:
        answer = answer[:357].rstrip() + "..."
    return f"성분 근거 참고: {concern}에는 {answer}"


def concern_targets_for_record(record: dict[str, Any]) -> set[str]:
    terms = query_terms(
        " ".join(
            [
                str(record.get("target_concern", "")),
                str(record.get("question", "")),
                " ".join(str(item) for item in record.get("skin_concerns", []) or []),
            ]
        )
    )
    targets: set[str] = set()
    for term in terms:
        targets.update(CONCERN_TARGETS.get(term, set()))
    return targets


def skincare_recommendation_context(
    message: str,
    context: dict | None = None,
) -> tuple[SkincareKnowledgeMatch | None, set[str], str]:
    matches = get_skincare_ingredient_knowledge().search(message, context, limit=1)
    if not matches or matches[0].score < 2:
        return None, set(), ""
    match = matches[0]
    targets = concern_targets_for_record(match.record)
    concern = str(match.record.get("target_concern", "피부 고민"))
    answer = str(match.record.get("answer", "")).strip()
    if len(answer) > 220:
        answer = answer[:217].rstrip() + "..."
    note = f"{concern} 성분 근거: {answer}"
    return match, targets, note

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import get_settings


WORD_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")
MEDICAL_TERMS = (
    "레이저",
    "IPL",
    "치료",
    "처방",
    "스테로이드",
    "피부염",
    "아토피",
    "주사 피부",
    "켈로이드",
)
ALIASES = {
    "여드름": ("여드름", "트러블", "면포", "화농성"),
    "홍조": ("홍조", "붉은기", "붉은 기", "주사"),
    "민감성": ("민감성", "민감", "자극", "화끈거림"),
    "아토피": ("아토피",),
    "색소침착": ("색소침착", "잡티", "기미", "주근깨"),
    "모공": ("모공",),
    "노화": ("노화", "주름", "탄력"),
    "지루성": ("지루성", "피부염"),
    "모세혈관": ("모세혈관", "혈관 확장"),
    "켈로이드": ("켈로이드",),
}
CONTEXT_LABELS = {
    "10s": "10대",
    "20s": "20대",
    "30s": "30대",
    "40s": "40대",
    "50s": "50대 이상",
    "female": "여성",
    "male": "남성",
    "dry": "건성",
    "oily": "지성",
    "combination": "복합성",
    "normal": "중성",
    "sensitive": "민감성",
}


@dataclass(frozen=True)
class KnowledgeMatch:
    record: dict[str, Any]
    score: float


def normalize(value: str) -> str:
    return " ".join(WORD_PATTERN.findall(value.lower()))


def query_terms(value: str) -> set[str]:
    normalized = normalize(value)
    terms = set(normalized.split())
    for canonical, aliases in ALIASES.items():
        if any(alias.lower() in normalized for alias in aliases):
            terms.add(canonical)
            terms.update(alias.lower().replace(" ", "") for alias in aliases)
    return {term for term in terms if len(term) >= 2}


def context_text(context: dict | None) -> str:
    if not context:
        return ""
    parts: list[str] = []
    survey = context.get("survey")
    if isinstance(survey, dict):
        for key in ("skin_type", "age_group", "gender"):
            value = survey.get(key)
            if value:
                parts.append(CONTEXT_LABELS.get(str(value), str(value)))
        for key in ("concerns", "makeup_concerns", "area_concerns", "male_extras"):
            values = survey.get(key)
            if isinstance(values, list):
                parts.extend(str(value) for value in values)
    scores = context.get("scores")
    if isinstance(scores, dict):
        labels = {
            "acne": "여드름 트러블",
            "pore": "모공",
            "wrinkle": "노화 주름",
            "redness": "홍조 민감성",
            "pigmentation": "색소침착 기미",
            "oiliness": "유분 지성",
        }
        ranked = sorted(scores.items(), key=lambda item: float(item[1]), reverse=True)[:2]
        parts.extend(labels.get(name, name) for name, _ in ranked)
    return " ".join(parts)


class ProblemSkinKnowledge:
    def __init__(self, index_path: str | Path | None = None) -> None:
        configured = index_path or get_settings().problem_skin_knowledge_path
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
        problem = normalize(str(record.get("skin_problem", "")))
        question = normalize(str(record.get("question", "")))
        metadata = normalize(
            " ".join(
                str(record.get(key, ""))
                for key in (
                    "skin_condition",
                    "skin_brightness",
                    "makeup_focus",
                    "makeup_purpose",
                    "recommended_ingredients",
                    "avoid_ingredients",
                )
            )
        )
        return record, problem, question, query_terms(f"{problem} {question} {metadata}")

    def search(self, message: str, context: dict | None = None, limit: int = 3) -> list[KnowledgeMatch]:
        query = f"{message} {context_text(context)}"
        terms = query_terms(query)
        normalized_query = normalize(query)
        matches: list[KnowledgeMatch] = []
        for record, problem, question, record_terms in self._indexed:
            overlap = terms.intersection(record_terms)
            score = float(len(overlap))
            if problem and problem in normalized_query:
                score += 8.0
            for canonical, aliases in ALIASES.items():
                if canonical in terms and any(alias.lower() in problem for alias in aliases):
                    score += 6.0
            score += min(3.0, sum(1 for term in terms if term in question) * 0.35)
            if score > 0:
                matches.append(KnowledgeMatch(record=record, score=score))
        return sorted(matches, key=lambda item: item.score, reverse=True)[:limit]


@lru_cache(maxsize=1)
def get_problem_skin_knowledge() -> ProblemSkinKnowledge:
    return ProblemSkinKnowledge()


def build_knowledge_answer(matches: list[KnowledgeMatch]) -> tuple[str, list[str]]:
    if not matches:
        return "", []
    best = matches[0].record
    problem = str(best.get("skin_problem", "문제성 피부"))
    answer = _remove_case_specific_demographics(str(best.get("answer", "")).strip(), best)
    if len(answer) > 1000:
        answer = answer[:997].rstrip() + "..."

    sections = [f"AI Hub의 유사한 {problem} 상담 사례를 참고하면, {answer}"]
    recommended = str(best.get("recommended_ingredients", "")).strip()
    avoided = str(best.get("avoid_ingredients", "")).strip()
    if recommended:
        sections.append(f"사례의 추천 성분: {recommended}.")
    if avoided:
        sections.append(f"피하도록 제시된 성분: {avoided}.")
    combined = " ".join(sections)
    if any(term.lower() in combined.lower() for term in MEDICAL_TERMS):
        combined += " 치료나 질환 판단이 필요한 내용은 화장품 조언과 구분해 피부과 전문의와 상담해 주세요."
    combined += " 개인차가 있으므로 새 제품은 좁은 부위에 먼저 테스트해 주세요."

    sources = []
    for match in matches:
        record = match.record
        titles = record.get("source_titles") or []
        label = str(titles[0]) if titles else f"AI Hub 문제성 피부 상담 {record.get('id', '')}".strip()
        if label not in sources:
            sources.append(label)
    return combined, sources


def _remove_case_specific_demographics(answer: str, record: dict[str, Any]) -> str:
    case_values = {
        str(record.get("age", "")).strip(),
        str(record.get("gender", "")).strip(),
        str(record.get("skin_brightness", "")).strip(),
    }
    case_values.discard("")
    sentences = re.split(r"(?<=[.!?])\s+", answer)
    cleaned = [
        sentence
        for sentence in sentences
        if not (
            any(value in sentence for value in case_values)
            and any(marker in sentence for marker in ("여성", "남성", "피부 톤", "피부톤"))
        )
    ]
    return " ".join(cleaned).strip() or answer

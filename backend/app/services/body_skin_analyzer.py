from __future__ import annotations

from io import BytesIO

from PIL import Image

from app.ai.body_skin_model import BodySkinClassifier
from app.core.config import get_settings
from app.schemas.api import BodyConditionScore


BODY_LABELS = {
    "atopic_dermatitis": "아토피 피부염",
    "contact_dermatitis": "접촉성 피부염",
    "eczema": "습진",
    "scabies": "옴",
    "seborrheic_dermatitis": "지루성 피부염",
    "tinea_corporis": "체부백선",
}

_classifier: BodySkinClassifier | None = None


def _get_classifier() -> BodySkinClassifier:
    global _classifier
    if _classifier is None:
        _classifier = BodySkinClassifier(get_settings().resolved_body_skin_model_path)
    return _classifier


class BodySkinAnalyzer:
    def analyze(self, image_bytes: bytes) -> tuple[list[BodyConditionScore], bool, str]:
        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        predictions = _get_classifier().predict(image)
        if predictions is None:
            return (
                [],
                False,
                "몸 피부 모델이 아직 학습되지 않았습니다. 데이터 준비 후 학습을 실행해 주세요.",
            )

        conditions = [
            BodyConditionScore(
                condition=name,
                label=BODY_LABELS.get(name, name),
                probability=probability,
            )
            for name, probability in predictions[:3]
        ]
        top = conditions[0]
        gap = top.probability - (conditions[1].probability if len(conditions) > 1 else 0)
        confidence_note = (
            "상위 범주 간 차이가 작아 사진을 추가해 다시 확인하는 것이 좋습니다. "
            if top.probability < 50 or gap < 10
            else ""
        )
        summary = (
            f"몸 피부 이미지 분류 결과는 {top.label} 가능성 {top.probability:.1f}%로 나타났습니다. "
            f"{confidence_note}"
            "이는 6개 피부질환 범주 사이의 비교 결과이며 확정 진단이 아닙니다."
        )
        return conditions, True, summary

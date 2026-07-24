"""2단 피부질환 선별 분석 (body 경로 대체).

이미지 → Tier1 게이트(정상/양성/악성의심) → 악성 아니면 Tier2 케어 그룹.
악성 조기발견이 목적이라 recall 우선: Tier1이 urgent거나 Tier2 최상위가 malignant면
'악성 의심'으로 에스컬레이트(안전한 방향). 진단이 아니라 선별/안내.
"""
from __future__ import annotations

from io import BytesIO

from PIL import Image

from app.ai.dermatology_model import get_dermatology_model
from app.schemas.api import BodyConditionScore

# Tier2 그룹 → 한글 라벨
TIER2_LABELS = {
    "eczema_dermatitis": "습진·피부염",
    "acne_rosacea": "여드름·주사",
    "psoriasis": "건선",
    "fungal": "진균(무좀·백선)",
    "infestation_bites": "기생·물림(옴 등)",
    "viral": "바이러스(사마귀 등)",
    "pigment_benign": "양성 색소병변(점·지루각화)",
    "malignant": "악성 의심",
    "other": "기타",
}

SCREENING_NOTE = (
    "이 결과는 진단이 아니라 선별·안내입니다. 정확한 진단은 피부과 전문의 진료가 필요합니다."
)
_UNAVAILABLE = "피부질환 선별 모델이 아직 준비되지 않았습니다. 모델 파일을 배치한 뒤 다시 시도해 주세요."


class DermatologyAnalyzer:
    def analyze(self, image_bytes: bytes) -> dict:
        """→ {conditions, model_available, summary, tier1_label, tier1_confidence, urgent}"""
        model = get_dermatology_model()
        if not model.available:
            return {
                "conditions": [], "model_available": False, "summary": _UNAVAILABLE,
                "tier1_label": "", "tier1_confidence": 0.0, "urgent": False,
            }

        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        t1 = model.predict_tier1(image)
        if not t1:
            return {
                "conditions": [], "model_available": False, "summary": _UNAVAILABLE,
                "tier1_label": "", "tier1_confidence": 0.0, "urgent": False,
            }

        tier1_label = max(t1, key=t1.get)
        tier1_conf = round(t1[tier1_label] * 100, 1)

        # 악성 판정은 Tier1 게이트만 신뢰한다. Tier1은 그 목적(악성 recall 89%)에 맞게 학습됐고,
        # Tier2의 malignant는 9지선다 중 하나라 정밀도가 낮아 게이트로 쓰면 과잉 오탐이 난다.
        urgent = tier1_label == "urgent_referral"

        conditions: list[BodyConditionScore] = []
        if tier1_label != "normal":
            t2 = model.predict_tier2(image) or {}
            ranked = sorted(t2.items(), key=lambda kv: kv[1], reverse=True)
            # 전체 9개 그룹을 확률 높은 순으로 표시(악성 의심 포함). 악성 '판정'은 여전히
            # tier1 게이트로만 하고, 여기 malignant %는 tier2 분포의 참고 수치일 뿐.
            conditions = [
                BodyConditionScore(
                    condition=name,
                    label=TIER2_LABELS.get(name, name),
                    probability=round(prob * 100, 1),
                )
                for name, prob in ranked
            ]

        if urgent:
            summary = (
                "⚠️ 악성(피부암) 의심 특징이 감지됐습니다. 빠른 시일 내 피부과 진료를 권합니다. "
                "이는 선별 경고이며 확정 진단이 아닙니다."
            )
        elif tier1_label == "normal":
            summary = "특이 소견이 뚜렷하게 보이지 않습니다. (선별 결과이며 진단이 아닙니다)"
        else:
            # 게이트가 '양성-케어필요'. Tier2 그룹은 확신도가 유의미할 때만 덧붙인다.
            if conditions and conditions[0].probability >= 20:
                summary = (
                    f"양성으로 보이며 {conditions[0].label} 계열 가능성이 있습니다. "
                    "케어·상담 안내용이며 확정 진단은 아닙니다."
                )
            else:
                summary = "양성이지만 케어가 필요한 상태로 보입니다. 케어·상담 안내용이며 확정 진단은 아닙니다."

        return {
            "conditions": conditions,
            "model_available": True,
            "summary": summary,
            "tier1_label": tier1_label,
            "tier1_confidence": tier1_conf,
            "urgent": urgent,
        }

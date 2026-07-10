"""피부질환(Tier2) → 적합 성분/케어 매핑.

2단 모델이 판정한 질환 그룹에 맞는 '성분'으로 추천을 몬다. 우리 상품 DB는 화장품
액티브(세라마이드·살리실산·아젤라산 등)만 있어, 화장품으로 다룰 수 있는 병은 실제
제품을 추천하고(PRODUCTS), 약이 필요한 병(무좀=항진균제, 옴=퍼메트린 등)은 가짜
제품 대신 성분·상담 안내만 한다(GUIDE_ONLY). 악성 의심은 진료 안내(REFERRAL).

주의: 진단·처방이 아니라 참고용 안내. 실제 약은 약사/피부과와 상담해야 한다.
"""
from __future__ import annotations

PRODUCTS = "products"      # DB 화장품 제품 추천 가능
GUIDE_ONLY = "guide_only"  # 약/관찰 필요 — 제품 대신 안내
REFERRAL = "referral"      # 악성 의심 — 진료 안내


# tier2 그룹 → 케어 정의
CONDITION_CARE: dict[str, dict] = {
    "eczema_dermatitis": {
        "kind": PRODUCTS,
        "label": "습진·피부염",
        # 장벽 진정·회복. 자극성 액티브는 피한다.
        "ingredients": ["Centella Asiatica", "Panthenol", "Ceramide", "Hyaluronic Acid"],
        "avoid": ["Retinol", "Salicylic Acid", "Glycolic Acid", "Lactic Acid", "Vitamin C", "Azelaic Acid"],
        "guide": "습진·피부염엔 자극 성분을 피하고 세라마이드·판테놀·센텔라로 장벽을 진정·회복하는 제품이 도움이 됩니다. 증상이 심하거나 지속되면 스테로이드 등은 피부과 상담이 필요합니다.",
    },
    "acne_rosacea": {
        "kind": PRODUCTS,
        "label": "여드름·주사",
        "ingredients": ["Salicylic Acid", "Azelaic Acid", "Niacinamide", "Zinc", "Green Tea"],
        "avoid": [],
        "guide": "여드름·주사엔 살리실산(BHA)·아젤라산·나이아신아마이드 성분이 도움이 됩니다. 화농성이 심하면 벤조일퍼옥사이드·아다팔렌 등은 약국·피부과 상담을 권합니다.",
    },
    "psoriasis": {
        "kind": PRODUCTS,
        "label": "건선",
        "ingredients": ["Salicylic Acid", "Ceramide", "Hyaluronic Acid"],
        "avoid": [],
        "guide": "건선은 각질 완화(살리실산)와 보습이 보조가 되지만, 근본 치료는 칼시포트리올·국소 스테로이드 등 처방이 필요합니다. 피부과 상담을 권합니다.",
    },
    "other": {
        "kind": PRODUCTS,
        "label": "기타 피부 이상",
        "ingredients": ["Ceramide", "Panthenol", "Hyaluronic Acid"],
        # 미분류 피부 이상엔 안전하게 강한 액티브를 배제하고 순한 보습·진정만.
        "avoid": ["Retinol", "Salicylic Acid", "Glycolic Acid", "Lactic Acid"],
        "guide": "정확한 분류가 어려워 우선 순한 보습·진정 관리를 권합니다. 증상이 지속·악화되면 피부과 상담을 받아보세요.",
    },
    "fungal": {
        "kind": GUIDE_ONLY,
        "label": "진균 감염(무좀·백선)",
        "ingredients": [],
        "guide": "무좀·백선 등 진균 감염은 보습제가 아니라 항진균 성분(테르비나핀·클로트리마졸·미코나졸 등)이 필요합니다. 약국 OTC 항진균제 또는 피부과 상담을 권합니다.",
    },
    "infestation_bites": {
        "kind": GUIDE_ONLY,
        "label": "기생·물림(옴 등)",
        "ingredients": [],
        "guide": "옴 등은 퍼메트린 크림 같은 처방 치료가 필요합니다. 자가 제품보다 피부과 진료를 권합니다.",
    },
    "viral": {
        "kind": GUIDE_ONLY,
        "label": "바이러스(사마귀·헤르페스)",
        "ingredients": [],
        "guide": "사마귀는 살리실산 각질용해제·냉동치료(병원), 헤르페스는 아시클로버 등 항바이러스제가 필요합니다. 약국·피부과 상담을 권합니다.",
    },
    "pigment_benign": {
        "kind": GUIDE_ONLY,
        "label": "양성 색소병변(점·지루각화)",
        "ingredients": [],
        "guide": "점·지루각화 같은 양성 색소병변은 바르는 제품으로 없어지지 않습니다. 자외선차단으로 짙어짐을 예방하고, 크기·색·모양 변화가 있으면 피부과에서 확인하세요.",
    },
    "malignant": {
        "kind": REFERRAL,
        "label": "악성 의심",
        "ingredients": [],
        "guide": "악성(피부암) 의심 소견입니다. 제품 추천 대신, 빠른 시일 내 피부과 진료를 받으세요. 이는 선별 경고이며 확정 진단이 아닙니다.",
    },
}


def care_for(condition: str | None) -> dict:
    return CONDITION_CARE.get(condition or "", CONDITION_CARE["other"])


# ── OTC 의약품(약국 제품) 매핑 ────────────────────────────────────────────
# 병별 OTC 유효성분(제네릭명, OpenFDA 매칭용). 자가치료가 부적절한 병(옴·악성)은 제외.
# 이 성분들로 build_otc_drug_knowledge.py가 OpenFDA OTC 라벨에서 실제 제품 예시를 뽑는다.
# 주의: 미국 FDA OTC 기준. 국내 판매/제형은 다를 수 있고, 진단·처방이 아닌 참고용이다.
OTC_INGREDIENTS: dict[str, list[str]] = {
    "fungal": ["terbinafine", "clotrimazole", "miconazole", "ketoconazole", "tolnaftate", "butenafine"],
    "acne_rosacea": ["benzoyl peroxide", "adapalene", "salicylic acid"],
    "eczema_dermatitis": ["hydrocortisone"],
    "psoriasis": ["salicylic acid", "coal tar", "hydrocortisone"],
    "viral": ["salicylic acid", "docosanol"],
}


def _otc_knowledge_path():
    from pathlib import Path

    from app.core.config import get_settings
    settings = get_settings()
    raw = getattr(settings, "otc_drug_knowledge_path", "./data/rag/otc_drug_knowledge.jsonl")
    path = Path(raw)
    return path if path.is_absolute() else settings.project_root / path


def load_otc_examples(condition: str, limit: int = 4) -> list[dict]:
    """빌드된 OTC 지식(JSONL)에서 해당 병의 실제 OTC 제품 예시를 반환. 없으면 빈 리스트(폴백)."""
    import json
    from functools import lru_cache

    @lru_cache(maxsize=1)
    def _load() -> dict[str, list[dict]]:
        path = _otc_knowledge_path()
        by_condition: dict[str, list[dict]] = {}
        if not path.is_file():
            return by_condition
        with path.open(encoding="utf-8") as source:
            for line in source:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                by_condition.setdefault(record.get("condition", ""), []).append(record)
        return by_condition

    return _load().get(condition, [])[:limit]

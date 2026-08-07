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
        # 에몰리언트·오클루시브(페트롤라툼·글리세린·콜로이달오트밀)를 함께 둔다 — 아토피
        # 피부염 관리의 1차는 보습제이고, 얼굴용 액티브 4종만 보면 실제 바디 제품의 68%가
        # '성분 미상'으로 빠진다(실측).
        "ingredients": [
            "Ceramide", "Panthenol", "Centella Asiatica", "Hyaluronic Acid",
            "Petrolatum", "Glycerin", "Colloidal Oatmeal", "Shea Butter",
            "Squalane", "Allantoin", "Dimethicone",
        ],
        "avoid": ["Retinol", "Salicylic Acid", "Glycolic Acid", "Lactic Acid", "Vitamin C", "Azelaic Acid"],
        "guide": "습진·피부염엔 자극 성분을 피하고 세라마이드·판테놀·센텔라로 장벽을 진정·회복하는 제품이 도움이 됩니다. 증상이 심하거나 지속되면 스테로이드 등은 피부과 상담이 필요합니다.",
    },
    "acne_rosacea": {
        "kind": PRODUCTS,
        "label": "여드름·주사",
        # 유분 부담이 적은 보습만 더한다. 페트롤라툼·시어버터는 여드름엔 넣지 않는다.
        "ingredients": [
            "Salicylic Acid", "Azelaic Acid", "Niacinamide", "Zinc", "Green Tea",
            "Glycerin", "Squalane", "Allantoin",
        ],
        "avoid": [],
        "guide": "여드름·주사엔 살리실산(BHA)·아젤라산·나이아신아마이드 성분이 도움이 됩니다. 화농성이 심하면 벤조일퍼옥사이드·아다팔렌 등은 약국·피부과 상담을 권합니다.",
    },
    "psoriasis": {
        "kind": PRODUCTS,
        "label": "건선",
        # 각질 완화(살리실산·우레아) + 강한 폐색 보습.
        "ingredients": [
            "Salicylic Acid", "Urea", "Ceramide", "Hyaluronic Acid",
            "Petrolatum", "Glycerin", "Shea Butter",
        ],
        "avoid": [],
        "guide": "건선은 각질 완화(살리실산)와 보습이 보조가 되지만, 근본 치료는 칼시포트리올·국소 스테로이드 등 처방이 필요합니다. 피부과 상담을 권합니다.",
    },
    "other": {
        "kind": PRODUCTS,
        "label": "기타 피부 이상",
        "ingredients": [
            "Ceramide", "Panthenol", "Hyaluronic Acid",
            "Glycerin", "Squalane", "Allantoin", "Shea Butter",
        ],
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


# ── 일본어판 ────────────────────────────────────────────────────────────────
# 요약문은 label/guide 를 문장에 끼워 조립하므로 프론트 사전으로는 못 옮긴다(성분·상품명이
# 함께 들어간다). 그래서 서버가 두 벌을 만든다 — 얼굴 경로의 build_explanation_ja 와 같은 방식.
#
# ⚠ 키는 CONDITION_CARE 와 **정확히 같아야** 한다. 한쪽만 늘면 그 질환에서 일본 사용자에게
#   한국어 의학 안내가 나간다(성분 근거를 한국어로 안 내보내는 것과 같은 이유).
#   test_derma_pediatric_explanation_ja.py 가 키 일치를 강제한다.
# ⚠ guide 문장은 frontend/src/i18n.ts 에 이미 검수된 번역이 있다(예전엔 explanation 전체가
#   guide 와 **글자 그대로 같을 때만** 사전에 걸려 번역됐다 — 앞에 lead 가 붙거나 뒤에 OTC
#   예시가 붙으면 조회에 실패해 한국어가 그대로 나갔다. 그게 이번 제보다).
#   여기 문장은 그 사전 값과 **같은 문장**으로 둔다. 두 벌이 서로 다른 일본어가 되면
#   같은 안내가 화면마다 다르게 읽힌다.
CONDITION_CARE_JA: dict[str, dict[str, str]] = {
    "eczema_dermatitis": {
        "label": "湿疹・皮膚炎",
        "guide": "湿疹・皮膚炎では刺激成分を避け、セラミド・パンテノール・ツボクサでバリアを鎮静・"
                 "回復する製品が助けになります。症状が強い・続く場合、ステロイドなどは皮膚科への"
                 "相談が必要です。",
    },
    "acne_rosacea": {
        "label": "ニキビ・酒さ",
        "guide": "ニキビ・酒さにはサリチル酸（BHA）・アゼライン酸・ナイアシンアミドが役立ちます。"
                 "化膿がひどい場合、過酸化ベンゾイル・アダパレンなどは薬局・皮膚科への相談を"
                 "おすすめします。",
    },
    "psoriasis": {
        "label": "乾癬",
        "guide": "乾癬では角質ケア（サリチル酸）と保湿が補助になりますが、根本治療には"
                 "カルシポトリオール・外用ステロイドなどの処方が必要です。皮膚科への相談を"
                 "おすすめします。",
    },
    "other": {
        "label": "その他の肌トラブル",
        "guide": "正確な分類が難しいため、まずは低刺激の保湿・鎮静ケアをおすすめします。"
                 "症状が続く・悪化する場合は皮膚科にご相談ください。",
    },
    "fungal": {
        "label": "真菌感染（水虫・白癬）",
        "guide": "水虫・白癬などの真菌感染には保湿剤ではなく抗真菌成分（テルビナフィン・"
                 "クロトリマゾール・ミコナゾールなど）が必要です。薬局のOTC抗真菌薬または"
                 "皮膚科への相談をおすすめします。",
    },
    "infestation_bites": {
        "label": "寄生・虫刺され（疥癬など）",
        "guide": "疥癬などはペルメトリンクリームのような処方治療が必要です。"
                 "市販品より皮膚科の受診をおすすめします。",
    },
    "viral": {
        "label": "ウイルス性（いぼ・ヘルペス）",
        "guide": "いぼはサリチル酸の角質溶解剤・冷凍療法（医療機関）、ヘルペスはアシクロビルなどの"
                 "抗ウイルス薬が必要です。薬局・皮膚科への相談をおすすめします。",
    },
    "pigment_benign": {
        "label": "良性色素病変（ほくろ・脂漏性角化症）",
        "guide": "ほくろ・脂漏性角化症のような良性色素病変は、塗る製品では消えません。"
                 "日焼け止めで濃くなるのを防ぎ、大きさ・色・形に変化があれば皮膚科で確認してください。",
    },
    "malignant": {
        "label": "悪性の疑い",
        "guide": "悪性（皮膚がん）が疑われる所見です。製品のおすすめではなく、早めに皮膚科を"
                 "受診してください。これはスクリーニング警告であり、確定診断ではありません。",
    },
}

# 한/일 키가 어긋나면 그 질환에서 일본어판이 통째로 한국어로 폴백한다 — 임포트 시점에 잡는다.
assert set(CONDITION_CARE) == set(CONDITION_CARE_JA)


def care_for(condition: str | None) -> dict:
    return CONDITION_CARE.get(condition or "", CONDITION_CARE["other"])


def care_ja_for(condition: str | None) -> dict[str, str]:
    """`care_for` 의 일본어 라벨·안내문. 키가 없으면 'other' 로 폴백한다(한국어를 섞지 않는다)."""
    return CONDITION_CARE_JA.get(condition or "", CONDITION_CARE_JA["other"])


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

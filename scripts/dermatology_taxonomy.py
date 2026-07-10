"""통합 피부 taxonomy — 여러 데이터셋의 제각각 라벨을 2단 체계로 통일하는 단일 기준.

Tier1 (선별 게이트, 고-recall 조기발견 핵심):
    normal            : 정상/특이소견 없음
    benign_concern    : 양성이지만 케어 필요(염증·양성종양 등)
    urgent_referral   : 악성 의심(흑색종·기저세포암·편평세포암·광선각화증) → 강한 진료 권고

Tier2 (케어 안내용 질환 그룹, normal은 tier2 없음):
    eczema_dermatitis / acne_rosacea / psoriasis / fungal / infestation_bites /
    viral / pigment_benign / malignant / other

설계 원칙:
- Tier1의 '악성/양성' 지도학습은 라벨이 깨끗한 소스만 신뢰한다:
  PAD-UFES-20(암 100% 조직검사 확진) + Fitzpatrick17k(three_partition_label) + normal.
- DermNet은 클래스 폭(Tier2)이 넓지만, 흑색종+모반이 한 폴더에 섞인 것처럼
  Tier1 신호가 애매한 폴더가 있어, 그런 폴더는 tier1=None으로 두어 게이트 학습에서 제외한다.
"""
from __future__ import annotations

TIER1 = ("normal", "benign_concern", "urgent_referral")
TIER2 = (
    "eczema_dermatitis",
    "acne_rosacea",
    "psoriasis",
    "fungal",
    "infestation_bites",
    "viral",
    "pigment_benign",
    "malignant",
    "other",
)

# 악성/전암 → 항상 urgent. 이 tier2를 가지면 tier1은 urgent로 강제한다.
_URGENT_TIER2 = {"malignant"}


# ── PAD-UFES-20 : metadata.csv의 diagnostic 코드 ──────────────────────────
# 6클래스. 암(MEL/BCC/SCC)+전암(ACK)=urgent, 양성(NEV/SEK)=benign 색소병변.
PAD_UFES = {
    "MEL": ("urgent_referral", "malignant"),   # melanoma
    "BCC": ("urgent_referral", "malignant"),   # basal cell carcinoma
    "SCC": ("urgent_referral", "malignant"),   # squamous cell carcinoma
    "ACK": ("urgent_referral", "malignant"),   # actinic keratosis (전암)
    "NEV": ("benign_concern", "pigment_benign"),   # nevus
    "SEK": ("benign_concern", "pigment_benign"),   # seborrheic keratosis
}


# ── DermNet : 23개 폴더명(소문자 부분일치) → (tier1|None, tier2) ───────────
# tier1=None 은 '게이트 학습 제외'(라벨이 섞여 신뢰 불가). tier2는 폭 확보용으로 사용.
DERMNET = [
    ("acne and rosacea", ("benign_concern", "acne_rosacea")),
    ("actinic keratosis basal cell carcinoma", ("urgent_referral", "malignant")),
    ("atopic dermatitis", ("benign_concern", "eczema_dermatitis")),
    ("bullous disease", (None, "other")),
    ("cellulitis impetigo", (None, "other")),               # 세균감염, 급성이라 게이트 애매
    ("eczema", ("benign_concern", "eczema_dermatitis")),
    ("exanthems and drug eruptions", (None, "other")),
    ("hair loss", (None, "other")),
    ("herpes hpv", ("benign_concern", "viral")),
    ("light diseases and disorders of pigmentation", ("benign_concern", "pigment_benign")),
    ("lupus", (None, "other")),
    ("melanoma skin cancer nevi and moles", (None, "pigment_benign")),  # 흑색종+모반 혼재→게이트 제외
    ("nail fungus", ("benign_concern", "fungal")),
    ("poison ivy", ("benign_concern", "eczema_dermatitis")),  # contact dermatitis
    ("psoriasis pictures lichen planus", ("benign_concern", "psoriasis")),
    ("scabies lyme disease", ("benign_concern", "infestation_bites")),
    ("seborrheic keratoses and other benign tumors", ("benign_concern", "pigment_benign")),
    ("systemic disease", (None, "other")),
    ("tinea ringworm candidiasis", ("benign_concern", "fungal")),
    ("urticaria hives", ("benign_concern", "other")),
    ("vascular tumors", (None, "other")),
    ("vasculitis", (None, "other")),
    ("warts molluscum", ("benign_concern", "viral")),
]


# ── Fitzpatrick17k : three_partition_label → tier1 ────────────────────────
FITZ_THREE_TO_TIER1 = {
    "malignant": "urgent_referral",
    "non-neoplastic": "benign_concern",   # 염증성 등 (양성 케어)
    "benign": "benign_concern",
}
# nine_partition_label → tier2 (거친 매핑; 없으면 other)
FITZ_NINE_TO_TIER2 = {
    "inflammatory": "eczema_dermatitis",
    "malignant epidermal": "malignant",
    "malignant melanoma": "malignant",
    "malignant dermal": "malignant",
    "malignant cutaneous lymphoma": "malignant",
    "benign melanocyte": "pigment_benign",
    "benign epidermal": "pigment_benign",
    "benign dermal": "other",
    "genodermatoses": "other",
}


# ── SkinDisNet(기존 6종) → 전부 benign_concern ───────────────────────────
SKINDISNET = {
    "atopic_dermatitis": ("benign_concern", "eczema_dermatitis"),
    "contact_dermatitis": ("benign_concern", "eczema_dermatitis"),
    "eczema": ("benign_concern", "eczema_dermatitis"),
    "seborrheic_dermatitis": ("benign_concern", "eczema_dermatitis"),
    "scabies": ("benign_concern", "infestation_bites"),
    "tinea_corporis": ("benign_concern", "fungal"),
}


def dermnet_lookup(folder_name: str) -> tuple[str | None, str] | None:
    """DermNet 폴더명(부분일치) → (tier1|None, tier2). 못 찾으면 None."""
    text = folder_name.lower()
    for needle, mapping in DERMNET:
        if needle in text:
            return mapping
    return None


def enforce(tier1: str | None, tier2: str) -> tuple[str | None, str]:
    """악성 tier2면 tier1을 urgent로 강제(라벨 일관성 보정)."""
    if tier2 in _URGENT_TIER2:
        return "urgent_referral", tier2
    return tier1, tier2

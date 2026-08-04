from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import colorsys

import numpy as np
from PIL import Image, ImageOps

from app.ai.aihub_pc_model import AihubLabSeasonClassifier
from app.ai.personal_color_model import SEASON_TONE, EfficientNetSeasonClassifier
from app.core.config import get_settings
from app.schemas.api import PersonalColorMakeup, PersonalColorResponse

# 학습된 계절 분류기(있으면 웜/쿨을 모델로). 최초 사용 시 1회 로드해 재사용.
_season_classifier: EfficientNetSeasonClassifier | None = None
_aihub_classifier: AihubLabSeasonClassifier | None = None


def _get_season_classifier() -> EfficientNetSeasonClassifier:
    global _season_classifier
    if _season_classifier is None:
        _season_classifier = EfficientNetSeasonClassifier(get_settings().resolved_personal_color_model_path)
    return _season_classifier


def _get_aihub_classifier() -> AihubLabSeasonClassifier:
    global _aihub_classifier
    if _aihub_classifier is None:
        settings = get_settings()
        _aihub_classifier = AihubLabSeasonClassifier(
            settings.resolved_aihub_pc_ensemble_paths, tta=settings.aihub_pc_tta
        )
    return _aihub_classifier


@dataclass(frozen=True)
class PersonalColorProfile:
    label: str
    season: str
    tone: str
    subtype: str
    palette: list[str]
    makeup: PersonalColorMakeup
    advice: list[str]


PROFILES: dict[tuple[str, str], PersonalColorProfile] = {
    ("warm", "light"): PersonalColorProfile(
        label="봄 웜 라이트",
        season="spring",
        tone="warm",
        subtype="light",
        palette=["#FFD9C7", "#FFE9A8", "#B9E6D3", "#F7B7A3"],
        makeup=PersonalColorMakeup(
            lip=["코랄 핑크", "피치 베이지"],
            blush=["살구 코랄", "라이트 피치"],
            eye=["샴페인 베이지", "라이트 브라운"],
            base=["아이보리 베이지", "옐로우 베이스"],
            nail=["코랄", "피치", "살구 베이지"],
        ),
        advice=["맑고 밝은 코랄, 피치 계열이 잘 어울립니다.", "탁한 회색기와 너무 어두운 컬러는 얼굴을 무겁게 보일 수 있습니다."],
    ),
    ("warm", "deep"): PersonalColorProfile(
        label="가을 웜 딥",
        season="autumn",
        tone="warm",
        subtype="deep",
        palette=["#9A5A2F", "#C47A3A", "#6E7F45", "#B85C38"],
        makeup=PersonalColorMakeup(
            lip=["브릭 레드", "테라코타"],
            blush=["시나몬 베이지", "웜 로즈"],
            eye=["카멜 브라운", "카키 브라운"],
            base=["웜 베이지", "내추럴 베이지"],
            nail=["브릭", "테라코타", "카멜 브라운"],
        ),
        advice=["브라운, 브릭, 테라코타처럼 깊이 있는 웜 컬러가 안정적입니다.", "차가운 핑크나 형광기 있는 컬러는 피하는 편이 좋습니다."],
    ),
    ("warm", "soft"): PersonalColorProfile(
        label="가을 웜 뮤트",
        season="autumn",
        tone="warm",
        subtype="soft",
        palette=["#D2A679", "#B98968", "#A3A86B", "#C0846A"],
        makeup=PersonalColorMakeup(
            lip=["누드 코랄", "로즈 브라운"],
            blush=["베이지 코랄", "소프트 살구"],
            eye=["뮤트 브라운", "올리브 베이지"],
            base=["뉴트럴 웜 베이지", "샌드 베이지"],
            nail=["누드 베이지", "로즈 브라운", "카키 브라운"],
        ),
        advice=["부드럽고 차분한 웜 베이지, 코랄 브라운 계열이 좋습니다.", "너무 쨍한 컬러보다 한 톤 낮춘 색이 자연스럽습니다."],
    ),
    ("cool", "light"): PersonalColorProfile(
        label="여름 쿨 라이트",
        season="summer",
        tone="cool",
        subtype="light",
        palette=["#F2DDE8", "#D9E9F7", "#C9C7EA", "#E7BFD2"],
        makeup=PersonalColorMakeup(
            lip=["로즈 핑크", "쿨 핑크"],
            blush=["라벤더 핑크", "맑은 로즈"],
            eye=["모브 베이지", "쿨 브라운"],
            base=["핑크 베이스", "라이트 베이지"],
            nail=["로즈 핑크", "라벤더 핑크", "쿨 핑크"],
        ),
        advice=["밝고 부드러운 쿨 핑크, 라벤더, 로즈 계열이 잘 어울립니다.", "노란기가 강한 오렌지 계열은 얼굴 톤을 답답하게 만들 수 있습니다."],
    ),
    ("cool", "deep"): PersonalColorProfile(
        label="겨울 쿨 딥",
        season="winter",
        tone="cool",
        subtype="deep",
        palette=["#1F2A44", "#8A1745", "#D9DCE8", "#3E4A89"],
        makeup=PersonalColorMakeup(
            lip=["버건디", "체리 레드"],
            blush=["쿨 로즈", "플럼 핑크"],
            eye=["차콜 브라운", "딥 네이비"],
            base=["쿨 베이지", "핑크 뉴트럴"],
            nail=["버건디", "체리 레드", "딥 플럼"],
        ),
        advice=["선명하고 깊은 쿨 컬러가 인상을 또렷하게 만듭니다.", "누런 베이지나 탁한 오렌지 브라운은 피하는 편이 좋습니다."],
    ),
    ("cool", "bright"): PersonalColorProfile(
        label="겨울 쿨 브라이트",
        season="winter",
        tone="cool",
        subtype="bright",
        palette=["#F7F8FF", "#2B59C3", "#E72C75", "#101820"],
        makeup=PersonalColorMakeup(
            lip=["체리 핑크", "클리어 레드"],
            blush=["맑은 핑크", "쿨 핑크"],
            eye=["블랙 브라운", "실버 베이지"],
            base=["쿨 아이보리", "핑크 베이지"],
            nail=["체리 핑크", "클리어 레드", "푸시아 핑크"],
        ),
        advice=["대비감 있고 맑은 컬러가 장점을 살립니다.", "회색기가 많은 뮤트 컬러는 생기를 줄일 수 있습니다."],
    ),
    ("cool", "soft"): PersonalColorProfile(
        label="여름 쿨 뮤트",
        season="summer",
        tone="cool",
        subtype="soft",
        palette=["#C8B7C9", "#A9B6CF", "#D8C8D2", "#8E9BB0"],
        makeup=PersonalColorMakeup(
            lip=["말린 장미", "모브 로즈"],
            blush=["더스티 핑크", "로즈 베이지"],
            eye=["그레이 브라운", "모브 브라운"],
            base=["뉴트럴 핑크", "라이트 쿨 베이지"],
            nail=["말린 장미", "모브", "더스티 로즈"],
        ),
        advice=["차분한 로즈, 모브, 그레이시 톤이 자연스럽습니다.", "강한 형광색보다 부드러운 저채도 컬러를 추천합니다."],
    ),
}


# 색블렌드가 도움이 되는(아시아) 마켓. 그 외(글로벌/서구)는 model 단독 쪽으로 기울인다.
_BLEND_FULL_MARKETS = {"kr", "jp", "kor", "jpn", "kor_kr", "asia"}


# ── 촬영 조명 게이트 ───────────────────────────────────────────────────────────
#
# 왜 필요한가: 어두운 곳에서 찍은 사진은 **색 신호가 무의미하다.**
# AI-Hub 분광측색계 대조 실측 — WB 성공 시 픽셀 b* 와 실측의 상관 r=0.64,
# 실패 시 r=0.09. 그런데 예전에는 실패해도 색 가중치만 절반으로 낮춰 **답을 냈다.**
# 사용자 제보(어두운 실내에서 촬영 → 결과가 자기 퍼스널컬러와 다름)가 정확히 이 경우다.
#
# 문턱 근거(2026-08-04 실측):
#   AI-Hub 4조명 × 60장 = 240장
#     5000lux 3200K   WB 100%  밝기 0.608~0.867
#     5000lux 5600K   WB 100%  밝기 0.590~0.824
#      500lux 3200K   WB   0%  밝기 0.196~0.303
#      500lux 5600K   WB   0%  밝기 0.248~0.327
#   → WB 성공/실패가 **조도로 완전히 갈린다**(색온도와 무관). 이 지표 하나가 사실상 판정이다.
#
#   실기기(폰) 실내 사진 12장  → 통과 75%, 밝기 0.495~0.592
#     같은 사진을 60% 밝기로 낮추면 통과 0% (클럽 상황이 이 구간)
#
# ⚠ **밝기 상한은 두지 않는다.** 기존 안내 문턱(0.76)을 게이트로 쓰면 AI-Hub 좋은 조명
#   (최대 0.867)이 막힌다. 과노출은 밝기 평균이 아니라 '하얗게 날아간 비율'로 봐야 한다.
_GATE_BRIGHTNESS_MIN = 0.38
# 과노출: 얼굴 픽셀이 거의 흰색이면 색 정보가 사라진다. AI-Hub 에는 이 구간이 없어
# (5000lux 가 최대) 가상 성형 품질 게이트에서 실측한 값을 쓴다.
_GATE_CLIPPED_MAX = 0.15


class UnusablePhotoError(ValueError):
    """조명 때문에 판정할 수 없는 사진. 메시지는 사용자에게 그대로 보여줄 안내다."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def usable_for_color(reading: dict) -> bool:
    """이 한 장으로 퍼스널컬러를 판정해도 되는가.

    ⚠ **AI-Hub 모델을 쓴 경우는 통과시킨다.** 그 모델은 조명 보정을 내장하도록 학습돼
    (그 문제를 풀려고 만든 모델이다) 색 휴리스틱과 달리 WB 실패에 덜 취약하다.
    여기서 막으면 모델을 쓰는 의미가 없어진다.
    """
    if reading.get("model_season_probs"):
        return True
    if not reading.get("white_balanced"):
        return False
    brightness = float(reading.get("brightness") or 0.0)
    if brightness < _GATE_BRIGHTNESS_MIN:
        return False
    return float(reading.get("clipped") or 0.0) <= _GATE_CLIPPED_MAX


def unusable_reason(readings: list[dict]) -> str:
    """왜 못 쓰는지 + 어떻게 하면 되는지. 이유 없이 막으면 사용자는 같은 사진을 다시 올린다."""
    if not readings:
        return "사진을 읽지 못했습니다. 다른 사진으로 다시 시도해 주세요."
    if not any(r.get("face_detected") for r in readings):
        return "사진에서 얼굴을 찾지 못했습니다. 정면 얼굴이 또렷하게 나온 사진으로 다시 시도해 주세요."

    dark = sum(1 for r in readings if float(r.get("brightness") or 0.0) < _GATE_BRIGHTNESS_MIN)
    if dark >= len(readings) / 2:
        return (
            "사진이 어두워 피부색을 정확히 읽을 수 없습니다. "
            "창가나 밝은 조명 아래에서 다시 찍어 주세요."
        )
    return (
        "조명이 피부색을 왜곡하고 있어 퍼스널컬러를 판정할 수 없습니다. "
        "색이 있는 조명(주점·무대 조명 등)을 피하고, 창가나 흰 조명 아래에서 다시 찍어 주세요."
    )


class PersonalColorAnalyzer:
    @staticmethod
    def resolve_blend_scale(region: str | None) -> float:
        """마켓(쇼핑 로케일)별 color 블렌드 배율. kr/jp=현행(full), 글로벌=축소.
        region 미지정 시 설정 기본값(현행 동작 보존)."""
        settings = get_settings()
        if region is None:
            return float(settings.personal_color_color_blend_scale)
        normalized = region.strip().lower()
        if not normalized or normalized == "auto" or normalized in _BLEND_FULL_MARKETS:
            return float(settings.personal_color_color_blend_scale)
        return float(settings.personal_color_global_blend_scale)

    def analyze(self, image_bytes: bytes, color_scale: float = 1.0) -> PersonalColorResponse:
        return self._build_response(self._read_one(image_bytes, color_scale), samples=1)

    def analyze_many(self, images: list[bytes], color_scale: float = 1.0) -> PersonalColorResponse:
        """여러 장을 각각 읽어 피부 지표·계절 확률(softmax)을 평균낸다.
        한 장의 메이크업/조명/각도 노이즈로 여름쿨↔겨울쿨이 흔들리는 문제를,
        다중 샘플 평균(앙상블)으로 눌러 안정화한다.

        ⚠ 조명이 판정 가능한 장만 평균에 넣는다(`usable_for_color`). 못 쓰는 장을 섞으면
        평균이 그쪽으로 끌려가 결과가 틀어진다 — 여러 장을 받는 이유가 사라진다.
        """
        readings = [self._read_one(b, color_scale) for b in images if b]
        if not readings:
            raise ValueError("no valid images")

        usable = [r for r in readings if usable_for_color(r)]
        if not usable:
            # 한 장도 못 쓰면 **판정하지 않는다.** 실측(AI-Hub 분광측색 대조)에서 WB 실패 시
            # 픽셀 색상과 실측의 상관이 0.09 로 사실상 무의미했다 — 답을 내면 틀린 답이다.
            raise UnusablePhotoError(unusable_reason(readings))

        if len(usable) == 1:
            return self._build_response(usable[0], samples=1, screened=len(readings) - 1)
        return self._build_response(
            self._combine_readings(usable), samples=len(usable), screened=len(readings) - len(usable)
        )

    def _read_one(self, image_bytes: bytes, color_scale: float = 1.0) -> dict:
        """한 장에서 피부 지표 + 계절 확률(있으면)을 뽑아 dict로 반환(평균 합성용)."""
        original_rgb = self._load_rgb(image_bytes)
        model_rgb, face_detected = self._face_crop(original_rgb)
        # 조명 색온도 캐스트 제거: 눈흰자(공막) 기준 색항상성. 같은 사람이 사진마다
        # 봄웜↔가을웜으로 뒤집히는 주원인(warmth 흔들림)을 줄인다. 눈흰자를 못 찾으면 원본 유지.
        balanced_rgb, white_balanced = self._white_balance(model_rgb)
        landmark_pixels, landmark_count = self._landmark_skin_pixels(balanced_rgb)
        skin_pixels = landmark_pixels if landmark_pixels.size else self._skin_pixels(balanced_rgb)
        if skin_pixels.size == 0:
            skin_pixels = self._center_pixels(balanced_rgb)

        color_vector = self._skin_color_vector(skin_pixels)
        mean_rgb = color_vector["mean_rgb"]
        # 계절 분류기: 2026-07-08에 EfficientNet+블렌드 → SKN16(LAB+RandomForest)으로 교체했으나,
        # 라벨 예제셋(28장) 실측에서 SKN16이 '가을웜'으로 붕괴(정확도 28%, 25/28을 autumn)하고
        # 얼굴검출 실패도 잦아, 2026-07-13에 EfficientNet+블렌드(try2_smooth, 43% + 4계절 균형)로
        # 복귀했다. SKN16 subtype은 라벨 산출에 쓰이지 않아(subtype은 밝기/채도 지표로 계산) 제거.
        skn_subtype = ""
        # AI-Hub 다인종 분류기(사진 → 분광측색 참Lab → 계절). 조명 보정을 모델이 내장하므로
        # 색 휴리스틱과 섞지 않는다(섞으면 서로 다른 원리가 충돌한다). 켜져 있고 로드되면 이 경로.
        aihub_probs = None
        if get_settings().personal_color_use_aihub:
            aihub_probs = _get_aihub_classifier().predict_season_probs(model_rgb)
        model_season_probs = aihub_probs if aihub_probs else self._predict_season_probs(model_rgb)
        color_season_probs = self._color_season_probs(color_vector)
        # 조명 게이팅: WB 실패(따뜻한 실내광 등 캐스트 미보정)면 색 추정이 실측과 무의미(r0.09)해
        # ground-truth 대조에서 확인 → 색 가중치를 낮춰 모델 쪽으로 기운다.
        effective_scale = color_scale
        if aihub_probs:
            # AI-Hub 분류기는 조명 보정을 내장한다. 색 휴리스틱은 조명 캐스트에 취약해
            # (그 문제를 풀려고 이 모델을 만들었다) 섞으면 되돌리는 셈이라 블렌드를 끈다.
            effective_scale = 0.0
        elif not white_balanced:
            effective_scale *= float(get_settings().personal_color_wb_fail_color_scale)
        season_probs = self._blend_season_probs(
            model_season_probs, color_season_probs, color_vector, effective_scale
        )
        return {
            "skn_subtype": skn_subtype,
            "brightness": float(np.mean(mean_rgb) / 255),
            "chroma": float((np.max(mean_rgb) - np.min(mean_rgb)) / 255),
            "warmth": float(color_vector["warmth"]),
            "redness": float((mean_rgb[0] - mean_rgb[1]) / 255),
            # 계절 확률은 WB 미적용 얼굴 crop으로 예측해 배경/옷/머리색 영향을 줄인다.
            "season_probs": season_probs,
            "model_season_probs": model_season_probs,
            "color_season_probs": color_season_probs,
            "color_vector": color_vector,
            "landmark_skin_samples": float(landmark_count),
            "white_balanced": white_balanced,
            "face_detected": face_detected,
            # 과노출 비율 — 얼굴 픽셀이 하얗게 날아가면 색 정보가 사라진다.
            # 밝기 평균으로는 못 잡는다(일부만 날아가도 평균은 정상으로 보인다).
            # ⚠ WB 적용 전(model_rgb)이 아니라 **원본 얼굴 crop** 을 봐야 한다 —
            #   WB 는 채널을 스케일해서 날아간 픽셀을 되살린 것처럼 보이게 만들 수 있다.
            "clipped": float((model_rgb.astype(np.float32).mean(axis=2) > 248).mean())
            if model_rgb.size
            else 0.0,
            "sample_weight": self._reading_weight(
                face_detected, white_balanced, season_probs, color_vector["quality"], landmark_count
            ),
        }

    def _combine_readings(self, readings: list[dict]) -> dict:
        """여러 장의 지표를 품질 가중 평균, 계절 확률은 확률이 있는 샷들만 앙상블 평균."""
        weights = [float(r.get("sample_weight", 1.0)) for r in readings]
        weight_sum = max(1e-6, sum(weights))
        combined: dict = {
            key: sum(r[key] * w for r, w in zip(readings, weights)) / weight_sum
            for key in ("brightness", "chroma", "warmth", "redness", "landmark_skin_samples")
        }
        combined["color_vector"] = self._combine_color_vectors(readings, weights, weight_sum)
        prob_items = [
            (r["season_probs"], float(r.get("sample_weight", 1.0)))
            for r in readings
            if r["season_probs"] is not None
        ]
        model_prob_items = [
            (r["model_season_probs"], float(r.get("sample_weight", 1.0)))
            for r in readings
            if r.get("model_season_probs") is not None
        ]
        color_prob_items = [
            (r["color_season_probs"], float(r.get("sample_weight", 1.0)))
            for r in readings
            if r.get("color_season_probs") is not None
        ]
        if prob_items:
            prob_weight_sum = max(1e-6, sum(w for _, w in prob_items))
            combined["season_probs"] = {
                season: sum(p[season] * w for p, w in prob_items) / prob_weight_sum
                for season in prob_items[0][0]
            }
            top_weights = {season: 0.0 for season in prob_items[0][0]}
            for probs, weight in prob_items:
                top_weights[max(probs, key=probs.get)] += weight
            combined["season_consistency"] = max(top_weights.values()) / prob_weight_sum
        else:
            combined["season_probs"] = None
            combined["season_consistency"] = 0.0
        combined["model_season_probs"] = self._weighted_probability_average(model_prob_items)
        combined["color_season_probs"] = self._weighted_probability_average(color_prob_items)
        combined["white_balanced"] = any(r["white_balanced"] for r in readings)
        combined["face_detected"] = any(r.get("face_detected") for r in readings)
        combined["sample_weight"] = weight_sum / len(readings)
        return combined

    def _build_response(
        self, reading: dict, samples: int = 1, screened: int = 0
    ) -> PersonalColorResponse:
        """screened = 조명 게이트에서 제외한 장 수. 사용자에게 '몇 장을 뺐는지' 알려야
        '5장 올렸는데 왜 결과가 다르지' 가 안 생긴다."""
        brightness = reading["brightness"]
        chroma = reading["chroma"]
        warmth = reading["warmth"]
        redness = reading["redness"]
        season_probs = reading["season_probs"]
        model_season_probs = reading.get("model_season_probs")
        color_season_probs = reading.get("color_season_probs")
        color_vector = reading.get("color_vector") or {}
        white_balanced = reading["white_balanced"]
        face_detected = bool(reading.get("face_detected", False))
        season_consistency = float(reading.get("season_consistency", 0.0))
        ordered_seasons = self._ordered_seasons(season_probs)
        alternate_profile: PersonalColorProfile | None = None
        alternate_season = ordered_seasons[1][0] if len(ordered_seasons) > 1 else None
        season_margin = (
            ordered_seasons[0][1] - ordered_seasons[1][1]
            if len(ordered_seasons) > 1
            else (ordered_seasons[0][1] if ordered_seasons else 0.0)
        )

        # 계절은 CNN 단독이 아니라 피부색 벡터(Lab/HSV)와 블렌딩한 확률로 결정한다.
        # subtype(밝기/선명도)은 측정 가능한 축이라 WB 보정 지표로 계산한다.
        if season_probs is not None:
            season = max(season_probs, key=season_probs.get)
            model_conf = season_probs[season]
            tone = SEASON_TONE[season]
            subtype = self._subtype_for_model_season(season, brightness, chroma)
            model_used = model_season_probs is not None
            if alternate_season:
                alternate_profile = self._profile_for_season(alternate_season, brightness, chroma)
        else:
            tone = "warm" if warmth >= 0.035 else "cool"
            subtype = self._subtype_from_metrics(brightness, chroma, tone)
            model_used = model_season_probs is not None

        profile = PROFILES.get((tone, subtype)) or PROFILES[(tone, "soft")]
        decision_note = self._decision_note(profile, alternate_profile, season_margin, samples, season_consistency)
        color_quality = float(color_vector.get("quality", 0.0))
        if season_probs is not None:
            if samples > 1:
                confidence = 0.5 * model_conf + 0.25 * season_consistency + 0.15 * color_quality + (0.1 if face_detected else 0.0)
                confidence = min(0.97, max(0.6, confidence))
            else:
                confidence = min(0.97, max(0.58, 0.78 * model_conf + 0.22 * color_quality))
        else:
            confidence = min(0.9, max(0.56, 0.62 + abs(warmth) * 1.8 + abs(brightness - 0.58) * 0.22 + chroma * 0.24))
        summary = self._summary(profile, brightness, chroma, warmth, redness, model_used)
        capture_advice = self._capture_advice(confidence, white_balanced, model_used, brightness, chroma)
        if samples <= 1:
            capture_advice = [
                "사진을 2~3장(다른 각도/조명) 함께 넣으면 여름쿨↔겨울쿨 같은 흔들림이 줄어 더 안정적으로 판정됩니다.",
                *capture_advice,
            ][:3]
        if screened > 0:
            # ⚠ **`[:3]` 자르기 뒤에** 붙여야 한다. 앞에서 넣었더니 아래 블록이 다른 문구를
            #   맨 앞에 끼워 넣고 3개로 잘라, 정작 이 안내가 밀려 사라질 수 있었다.
            #   사용자가 5장을 올렸는데 결과가 예상과 다르면 **이유를 먼저** 알아야 한다.
            capture_advice = [
                f"조명이 색을 왜곡한 사진 {screened}장은 판정에서 제외했습니다.",
                *capture_advice,
            ]

        # 경계선(borderline): 최상위 계절 확률이 임계값 미만이면 True.
        # 보정 실측(AI-Hub 60명, 전체 정확도 63.3%): 임계값 0.38 에서 확신군 75.0% vs 경계군 53.1%,
        # 0.45 로 올리면 확신군 93.3%(대신 75%가 경계). 경계군은 임계값과 무관하게 ~53%(진짜 애매).
        # 프론트/키오스크는 borderline 이면 alternate_season 을 동등 후보로 병기하면 된다.
        top_prob = ordered_seasons[0][1] if ordered_seasons else 0.0
        threshold = float(get_settings().personal_color_borderline_threshold)
        borderline = 1.0 if (season_probs is not None and top_prob < threshold) else 0.0

        return PersonalColorResponse(
            season=profile.season,
            tone=profile.tone,
            subtype=profile.subtype,
            label=profile.label,
            alternate_season=alternate_profile.season if alternate_profile else None,
            alternate_label=alternate_profile.label if alternate_profile else None,
            decision_note=decision_note,
            confidence=round(confidence, 2),
            skin_summary=summary,
            palette=profile.palette,
            makeup=profile.makeup,
            advice=[*profile.advice, *capture_advice],
            metrics={
                "brightness": round(brightness, 3),
                "chroma": round(chroma, 3),
                "warmth": round(warmth, 3),
                "redness": round(redness, 3),
                "white_balanced": 1.0 if white_balanced else 0.0,
                "face_detected": 1.0 if face_detected else 0.0,
                "model_used": 1.0 if model_used else 0.0,
                "capture_quality": round(
                    self._capture_quality(confidence, white_balanced, face_detected, model_used, brightness, chroma), 3
                ),
                "samples": float(samples),
                # 조명 게이트에서 제외한 장 수. 프론트가 '몇 장이 빠졌는지' 표시할 수 있게.
                "screened_out": float(screened),
                "sample_weight": round(float(reading.get("sample_weight", 1.0)), 3),
                "season_consistency": round(season_consistency, 3),
                "season_margin": round(season_margin, 3),
                "borderline": borderline,
                "color_vector_used": 1.0 if color_season_probs else 0.0,
                "landmark_skin_samples": round(float(reading.get("landmark_skin_samples", 0.0)), 1),
                **self._color_vector_metrics(color_vector),
                **self._season_probability_metrics(season_probs),
                **self._season_probability_metrics(model_season_probs, "model_prob"),
                **self._season_probability_metrics(color_season_probs, "color_prob"),
            },
        )

    def _subtype_from_metrics(self, brightness: float, chroma: float, tone: str) -> str:
        """밝기/채도(WB 보정)로 subtype(light/bright/deep/soft)을 정한다. 웜/쿨은 별도 결정."""
        if brightness >= 0.69:
            return "light"
        if chroma >= 0.18 and brightness >= 0.48:
            return "bright" if tone == "cool" else "light"
        if brightness <= 0.46:
            return "deep"
        return "soft"

    def _subtype_for_model_season(self, season: str, brightness: float, chroma: float) -> str:
        """모델이 맞힌 계절을 유지하면서 앱의 기존 subtype 프로필에 맞춘다."""
        if season == "spring":
            return "light"
        if season == "summer":
            return "light" if brightness >= 0.62 else "soft"
        if season == "autumn":
            return "deep" if brightness <= 0.46 else "soft"
        if season == "winter":
            return "deep" if brightness <= 0.46 else "bright"
        return self._subtype_from_metrics(brightness, chroma, SEASON_TONE.get(season, "warm"))

    def _profile_for_season(self, season: str, brightness: float, chroma: float) -> PersonalColorProfile:
        tone = SEASON_TONE.get(season, "warm")
        subtype = self._subtype_for_model_season(season, brightness, chroma)
        return PROFILES.get((tone, subtype)) or PROFILES[(tone, "soft")]

    def _ordered_seasons(self, season_probs: dict[str, float] | None) -> list[tuple[str, float]]:
        if not season_probs:
            return []
        return sorted(season_probs.items(), key=lambda item: item[1], reverse=True)

    def _season_probability_metrics(self, season_probs: dict[str, float] | None, prefix: str = "prob") -> dict[str, float]:
        if not season_probs:
            return {}
        return {f"{prefix}_{season}": round(float(prob), 4) for season, prob in season_probs.items()}

    def _weighted_probability_average(
        self, prob_items: list[tuple[dict[str, float] | None, float]]
    ) -> dict[str, float] | None:
        items = [(probs, weight) for probs, weight in prob_items if probs]
        if not items:
            return None
        weight_sum = max(1e-6, sum(weight for _, weight in items))
        return {
            season: sum(probs[season] * weight for probs, weight in items) / weight_sum
            for season in items[0][0]
        }

    def _blend_season_probs(
        self,
        model_probs: dict[str, float] | None,
        color_probs: dict[str, float] | None,
        color_vector: dict,
        color_scale: float = 1.0,
    ) -> dict[str, float] | None:
        if model_probs is None:
            return color_probs
        if color_probs is None:
            return model_probs
        # color_scale<=0: 색 휴리스틱 완전 배제(model 단독). 글로벌 마켓 게이팅의 극단값.
        if color_scale <= 0.0:
            return model_probs

        color_quality = float(color_vector.get("quality", 0.0))
        model_top = max(model_probs, key=model_probs.get)
        color_top = max(color_probs, key=color_probs.get)
        # 100%-color 하드 오버라이드는 색블렌드를 신뢰하는 마켓(scale이 충분히 큰 경우)에만 적용.
        # model 쪽으로 기운(scale<0.5) 글로벌 마켓에선 색이 파이프라인을 통째로 뒤집지 못하게 막는다.
        if color_scale >= 0.5:
            low_chroma_winter_shift = self._looks_like_low_chroma_winter_shift(model_top, color_top, color_vector)
            if low_chroma_winter_shift:
                return color_probs
            golden_autumn_shift = self._looks_like_golden_autumn_shift(model_top, color_top, color_vector)
            if golden_autumn_shift:
                return color_probs
        ordered = sorted(model_probs.values(), reverse=True)
        model_margin = ordered[0] - (ordered[1] if len(ordered) > 1 else 0.0)
        color_weight = 0.06 + 0.16 * min(1.0, max(0.0, color_quality))
        if model_margin < 0.08:
            color_weight += 0.05
        elif model_margin > 0.24:
            color_weight -= 0.08
        color_weight = min(0.24, max(0.04, color_weight))
        # 마켓 게이팅: 색 가중치에 배율 적용(1.0=현행, <1.0=model 쪽으로 축소).
        color_weight = min(0.99, max(0.0, color_weight * float(color_scale)))
        model_weight = 1.0 - color_weight
        blended = {
            season: model_probs[season] * model_weight + color_probs.get(season, 0.0) * color_weight
            for season in model_probs
        }
        total = max(1e-6, sum(blended.values()))
        return {season: value / total for season, value in blended.items()}

    def _looks_like_low_chroma_winter_shift(self, model_top: str, color_top: str, color_vector: dict) -> bool:
        """Cross-dataset faces often collapse to winter when the photo is low-chroma.
        In that narrow case, trust the Lab/HSV warm signal more strongly."""
        if model_top != "winter" or color_top not in {"spring", "autumn"}:
            return False
        return (
            float(color_vector.get("hsv_s", 1.0)) <= 0.15
            and float(color_vector.get("lab_a", 99.0)) <= 5.0
            and float(color_vector.get("lab_b", 99.0)) <= 18.0
        )

    def _looks_like_golden_autumn_shift(self, model_top: str, color_top: str, color_vector: dict) -> bool:
        """CNN often reads deep golden autumn skin as winter (autumn_as_winter is a
        top confusion). When the CNN says winter but the Lab yellow axis is clearly
        golden (high b*) and the color vector says autumn, trust the warm autumn read.
        Complementary to the low-chroma winter shift, which covers pale low-b* cases
        (lab_b <= 18); this one covers golden high-b* cases (lab_b >= 20)."""
        if model_top != "winter" or color_top != "autumn":
            return False
        return float(color_vector.get("lab_b", -99.0)) >= 20.0

    def _combine_color_vectors(self, readings: list[dict], weights: list[float], weight_sum: float) -> dict:
        keys = (
            "lab_l",
            "lab_a",
            "lab_b",
            "lab_chroma",
            "hsv_h",
            "hsv_s",
            "hsv_v",
            "warmth",
            "quality",
            "skin_density",
            "pixel_count",
        )
        combined = {
            key: sum(float(r["color_vector"].get(key, 0.0)) * w for r, w in zip(readings, weights)) / weight_sum
            for key in keys
        }
        combined["mean_rgb"] = sum(
            np.asarray(r["color_vector"].get("mean_rgb", np.zeros(3)), dtype=np.float32) * w
            for r, w in zip(readings, weights)
        ) / weight_sum
        return combined

    def _color_vector_metrics(self, color_vector: dict) -> dict[str, float]:
        if not color_vector:
            return {}
        return {
            "lab_l": round(float(color_vector.get("lab_l", 0.0)), 3),
            "lab_a": round(float(color_vector.get("lab_a", 0.0)), 3),
            "lab_b": round(float(color_vector.get("lab_b", 0.0)), 3),
            "lab_chroma": round(float(color_vector.get("lab_chroma", 0.0)), 3),
            "hsv_h": round(float(color_vector.get("hsv_h", 0.0)), 3),
            "hsv_s": round(float(color_vector.get("hsv_s", 0.0)), 3),
            "hsv_v": round(float(color_vector.get("hsv_v", 0.0)), 3),
            "skin_vector_quality": round(float(color_vector.get("quality", 0.0)), 3),
            "skin_density": round(float(color_vector.get("skin_density", 0.0)), 3),
            "skin_pixel_count": round(float(color_vector.get("pixel_count", 0.0)), 1),
        }

    def _decision_note(
        self,
        profile: PersonalColorProfile,
        alternate_profile: PersonalColorProfile | None,
        season_margin: float,
        samples: int,
        season_consistency: float,
    ) -> str | None:
        if alternate_profile is None:
            return None
        if season_margin < 0.08:
            return f"{profile.label}로 판정했지만 {alternate_profile.label}와 매우 가까운 경계 결과입니다."
        if season_margin < 0.16:
            return f"주 타입은 {profile.label}이며, 보조 경향은 {alternate_profile.label} 쪽에 가깝습니다."
        if samples > 1 and season_consistency < 0.72:
            return f"최종 타입은 {profile.label}입니다. 사진별 결과 흔들림이 있어 {alternate_profile.label} 경향도 함께 참고하세요."
        return None

    def _predict_season(self, rgb: np.ndarray) -> tuple[str, float] | None:
        """학습된 계절 분류기가 있으면 (계절, 신뢰도), 없으면 None(→휴리스틱)."""
        classifier = _get_season_classifier()
        if not classifier.available:
            return None
        try:
            return classifier.predict(Image.fromarray(rgb.astype(np.uint8)))
        except Exception:
            return None

    def _predict_season_probs(self, rgb: np.ndarray) -> dict[str, float] | None:
        """계절별 softmax 확률 dict(여러 장 앙상블 평균용) 또는 None(→휴리스틱)."""
        classifier = _get_season_classifier()
        if not classifier.available:
            return None
        try:
            return classifier.predict_probs(Image.fromarray(rgb.astype(np.uint8)))
        except Exception:
            return None

    def _skn16_season(self, original_rgb: np.ndarray) -> tuple[dict[str, float] | None, str]:
        """SKN16 팀 분류기로 계절 확률 + 세부톤을 예측한다. 얼굴검출 실패 시 (None, "")."""
        try:
            from app.ai.skn16_classifier import get_skn16_classifier
            clf = get_skn16_classifier()
            if not clf.available:
                return None, ""
            bgr = np.clip(original_rgb, 0, 255).astype(np.uint8)[:, :, ::-1].copy()  # RGB→BGR
            res = clf.predict(bgr)
            if not res:
                return None, ""
            return res["season_probs"], res.get("subtype", "")
        except Exception:
            return None, ""

    def _capture_quality(
        self,
        confidence: float,
        white_balanced: bool,
        face_detected: bool,
        model_used: bool,
        brightness: float,
        chroma: float,
    ) -> float:
        quality = 0.52 + confidence * 0.28
        quality += 0.08 if white_balanced else -0.06
        quality += 0.08 if face_detected else -0.1
        quality += 0.08 if model_used else -0.04
        if 0.38 <= brightness <= 0.76:
            quality += 0.06
        else:
            quality -= 0.08
        if chroma < 0.035:
            quality -= 0.05
        return min(0.96, max(0.0, quality))

    def _reading_weight(
        self,
        face_detected: bool,
        white_balanced: bool,
        season_probs: dict[str, float] | None,
        color_quality: float = 0.0,
        landmark_count: int = 0,
    ) -> float:
        weight = 1.0
        weight += 0.35 if face_detected else -0.25
        weight += 0.15 if white_balanced else -0.05
        weight += min(0.22, max(0.0, color_quality) * 0.22)
        weight += min(0.18, landmark_count / max(1, len(self._SKIN_SAMPLE_LANDMARKS)) * 0.18)
        if season_probs:
            ordered = sorted(season_probs.values(), reverse=True)
            margin = ordered[0] - (ordered[1] if len(ordered) > 1 else 0.0)
            weight += min(0.35, max(0.0, margin))
        return max(0.25, weight)

    def _capture_advice(
        self,
        confidence: float,
        white_balanced: bool,
        model_used: bool,
        brightness: float,
        chroma: float,
    ) -> list[str]:
        tips: list[str] = []
        if not model_used:
            tips.append("현재는 학습 모델 대신 조명 보정 기반 휴리스틱을 함께 사용했습니다. 최종 학습 모델을 적용하면 계절 분류 안정도가 올라갑니다.")
        if not white_balanced:
            tips.append("눈흰자 기준 조명 보정이 충분히 잡히지 않았습니다. 자연광에서 정면 사진을 다시 찍으면 정확도가 좋아집니다.")
        if brightness < 0.38:
            tips.append("사진이 어두운 편입니다. 얼굴에 그림자가 적게 드는 밝은 장소에서 재촬영을 권장합니다.")
        elif brightness > 0.76:
            tips.append("사진이 밝게 날아간 편입니다. 직접 조명보다 부드러운 간접광에서 촬영해 주세요.")
        if chroma < 0.035:
            tips.append("피부 색 차이가 약하게 잡혔습니다. 필터와 보정 앱을 끄고 원본 사진으로 분석하는 편이 좋습니다.")
        if confidence < 0.66:
            tips.append("이번 결과는 신뢰도가 낮은 편이라 팔레트는 참고용으로 보고, 다른 조명 사진과 비교해 보세요.")
        return tips[:3]

    def _white_balance(self, rgb: np.ndarray) -> tuple[np.ndarray, bool]:
        """공막(눈흰자) 기준 색항상성. 무채색이어야 할 눈흰자의 색을 조명색으로 보고 나눠,
        조명 색온도만 제거하고 피부 본연의 웜/쿨은 보존한다. 눈흰자 미검출 시 원본 반환."""
        illuminant = self._estimate_illuminant(rgb)
        if illuminant is None:
            return rgb, False
        gray = float(np.mean(illuminant))
        scale = gray / np.clip(illuminant, 1e-6, None)
        scale = np.clip(scale, 0.75, 1.33)  # 과보정 방지
        balanced = np.clip(rgb * scale.reshape(1, 1, 3), 0, 255).astype(np.float32)
        return balanced, True

    # mediapipe 눈 대표 랜드마크: (바깥, 안쪽, 위, 아래) — 눈 영역 바운딩 박스용.
    _EYE_LANDMARKS = ((33, 133, 159, 145), (362, 263, 386, 374))

    # 얼굴 외곽 + 이마/턱/양 볼 주요 랜드마크. crop은 옷/배경/염색모 영향 축소용이다.
    _FACE_CROP_LANDMARKS = (
        10, 152, 234, 454, 127, 356, 93, 323, 58, 288, 172, 397, 136, 365, 148, 377
    )

    # 뺨/이마/턱/코 주변의 피부 대표점. 입술, 눈썹, 머리카락 영역은 의도적으로 제외한다.
    _SKIN_SAMPLE_LANDMARKS = (
        10, 151, 9, 8, 168, 197, 195, 5, 4, 1,
        50, 101, 118, 187, 205, 36, 203, 177,
        280, 330, 347, 411, 425, 266, 423, 401,
        152, 175, 199, 200, 201, 421,
    )

    def _face_crop(self, rgb: np.ndarray) -> tuple[np.ndarray, bool]:
        try:
            import mediapipe as mp
        except Exception:
            return rgb, False
        for k in (0, 1, 3, 2):
            oriented = np.ascontiguousarray((np.rot90(rgb, k) if k else rgb).astype(np.uint8))
            crop = self._face_crop_from_oriented(oriented, mp)
            if crop is None:
                continue
            return np.ascontiguousarray(crop.astype(np.float32)), True
        return rgb, False

    def _face_crop_from_oriented(self, img: np.ndarray, mp) -> np.ndarray | None:
        h, w = img.shape[:2]
        try:
            with mp.solutions.face_mesh.FaceMesh(
                static_image_mode=True, max_num_faces=1, refine_landmarks=True, min_detection_confidence=0.5
            ) as mesh:
                result = mesh.process(img)
        except Exception:
            return None
        if not result.multi_face_landmarks:
            return self._face_detection_crop_from_oriented(img, mp)
        lm = result.multi_face_landmarks[0].landmark
        xs = [lm[i].x * w for i in self._FACE_CROP_LANDMARKS]
        ys = [lm[i].y * h for i in self._FACE_CROP_LANDMARKS]
        x1, x2 = max(0.0, min(xs)), min(float(w), max(xs))
        y1, y2 = max(0.0, min(ys)), min(float(h), max(ys))
        box_w = x2 - x1
        box_h = y2 - y1
        if box_w < 24 or box_h < 24:
            return None
        # 얼굴 옆 여백은 조금 주고, 위쪽 머리카락/아래쪽 의상은 과하게 들어오지 않게 제한한다.
        pad_x = box_w * 0.18
        top_pad = box_h * 0.12
        bottom_pad = box_h * 0.28
        cx1 = int(max(0, x1 - pad_x))
        cx2 = int(min(w, x2 + pad_x))
        cy1 = int(max(0, y1 - top_pad))
        cy2 = int(min(h, y2 + bottom_pad))
        if cx2 - cx1 < 24 or cy2 - cy1 < 24:
            return None
        return img[cy1:cy2, cx1:cx2]

    def _face_detection_crop_from_oriented(self, img: np.ndarray, mp) -> np.ndarray | None:
        h, w = img.shape[:2]
        try:
            with mp.solutions.face_detection.FaceDetection(
                model_selection=1, min_detection_confidence=0.35
            ) as detector:
                result = detector.process(img)
        except Exception:
            return None
        if not result.detections:
            return None
        detection = max(
            result.detections,
            key=lambda d: d.location_data.relative_bounding_box.width
            * d.location_data.relative_bounding_box.height,
        )
        box = detection.location_data.relative_bounding_box
        x1 = box.xmin * w
        y1 = box.ymin * h
        x2 = (box.xmin + box.width) * w
        y2 = (box.ymin + box.height) * h
        box_w = x2 - x1
        box_h = y2 - y1
        if box_w < 24 or box_h < 24:
            return None
        pad_x = box_w * 0.28
        top_pad = box_h * 0.18
        bottom_pad = box_h * 0.45
        cx1 = int(max(0, x1 - pad_x))
        cx2 = int(min(w, x2 + pad_x))
        cy1 = int(max(0, y1 - top_pad))
        cy2 = int(min(h, y2 + bottom_pad))
        if cx2 - cx1 < 24 or cy2 - cy1 < 24:
            return None
        return img[cy1:cy2, cx1:cx2]

    def _estimate_illuminant(self, rgb: np.ndarray) -> np.ndarray | None:
        """mediapipe 눈 랜드마크로 눈흰자(공막)를 찾아 그 평균색으로 조명색을 추정한다.
        휴대폰 사진이 90°/180° 회전된 경우도 있어 4방향을 시도한다(색 평균은 회전 무관).
        얼굴/눈흰자 미검출 시 None(→ WB 생략)."""
        try:
            import mediapipe as mp
        except Exception:
            return None
        for k in (0, 1, 3, 2):  # as-is, 90°CCW, 90°CW, 180°
            oriented = np.ascontiguousarray((np.rot90(rgb, k) if k else rgb).astype(np.uint8))
            illuminant = self._illuminant_from_oriented(oriented, mp)
            if illuminant is not None:
                return illuminant
        return None

    def _illuminant_from_oriented(self, img: np.ndarray, mp) -> np.ndarray | None:
        h, w = img.shape[:2]
        try:
            with mp.solutions.face_mesh.FaceMesh(
                static_image_mode=True, max_num_faces=1, refine_landmarks=True, min_detection_confidence=0.5
            ) as mesh:
                result = mesh.process(img)
        except Exception:
            return None
        if not result.multi_face_landmarks:
            return None
        lm = result.multi_face_landmarks[0].landmark

        neutral_chunks: list[np.ndarray] = []
        for idxs in self._EYE_LANDMARKS:
            xs = [lm[i].x * w for i in idxs]
            ys = [lm[i].y * h for i in idxs]
            x1, x2 = int(max(0, min(xs))), int(min(w, max(xs)))
            y1, y2 = int(max(0, min(ys))), int(min(h, max(ys)))
            if x2 - x1 < 3 or y2 - y1 < 2:
                continue
            patch = img[y1:y2, x1:x2].reshape(-1, 3).astype(np.float32)
            if patch.size == 0:
                continue
            maxc = patch.max(axis=1)
            minc = patch.min(axis=1)
            brightness = patch.mean(axis=1)
            saturation = (maxc - minc) / np.clip(maxc, 1e-6, None)
            mask = (brightness > 110) & (saturation < 0.28)  # 밝고 저채도 = 눈흰자 후보
            if mask.any():
                neutral_chunks.append(patch[mask])
        if not neutral_chunks:
            return None
        neutral = np.concatenate(neutral_chunks)
        if len(neutral) < 20:
            return None
        return neutral.mean(axis=0)

    def _load_rgb(self, image_bytes: bytes) -> np.ndarray:
        image = Image.open(BytesIO(image_bytes))
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((720, 720))
        return np.asarray(image, dtype=np.float32)

    def _landmark_skin_pixels(self, rgb: np.ndarray) -> tuple[np.ndarray, int]:
        try:
            import mediapipe as mp
        except Exception:
            return np.empty((0, 3), dtype=np.float32), 0
        img = np.ascontiguousarray(rgb.astype(np.uint8))
        h, w = img.shape[:2]
        try:
            with mp.solutions.face_mesh.FaceMesh(
                static_image_mode=True, max_num_faces=1, refine_landmarks=True, min_detection_confidence=0.5
            ) as mesh:
                result = mesh.process(img)
        except Exception:
            return np.empty((0, 3), dtype=np.float32), 0
        if not result.multi_face_landmarks:
            return np.empty((0, 3), dtype=np.float32), 0

        lm = result.multi_face_landmarks[0].landmark
        radius = max(3, int(min(h, w) * 0.018))
        chunks: list[np.ndarray] = []
        for idx in self._SKIN_SAMPLE_LANDMARKS:
            cx = int(np.clip(lm[idx].x * w, 0, w - 1))
            cy = int(np.clip(lm[idx].y * h, 0, h - 1))
            patch = rgb[max(0, cy - radius): min(h, cy + radius + 1), max(0, cx - radius): min(w, cx + radius + 1)]
            pixels = self._filter_skin_pixels(patch)
            if len(pixels) >= 8:
                chunks.append(pixels)
        if not chunks:
            return np.empty((0, 3), dtype=np.float32), 0
        pixels = np.concatenate(chunks).astype(np.float32)
        return self._trim_luminance_outliers(pixels), len(chunks)

    def _skin_pixels(self, rgb: np.ndarray) -> np.ndarray:
        height, width, _ = rgb.shape
        y1, y2 = int(height * 0.18), int(height * 0.82)
        x1, x2 = int(width * 0.2), int(width * 0.8)
        crop = rgb[y1:y2, x1:x2]
        pixels = self._filter_skin_pixels(crop)
        return self._trim_luminance_outliers(pixels)

    def _filter_skin_pixels(self, rgb: np.ndarray) -> np.ndarray:
        if rgb.size == 0:
            return np.empty((0, 3), dtype=np.float32)
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        maxc = np.max(rgb, axis=2)
        minc = np.min(rgb, axis=2)
        mask = (
            (r > 70)
            & (g > 45)
            & (b > 35)
            & ((maxc - minc) > 12)
            & (r > b * 0.95)
            & (r > g * 0.86)
            & (r < 245)
            & (g < 235)
            & (b < 230)
        )
        return rgb[mask].astype(np.float32)

    def _trim_luminance_outliers(self, pixels: np.ndarray) -> np.ndarray:
        if len(pixels) > 1800:
            luminance = pixels @ np.array([0.2126, 0.7152, 0.0722])
            lo, hi = np.percentile(luminance, [15, 85])
            pixels = pixels[(luminance >= lo) & (luminance <= hi)]
        return pixels

    def _skin_color_vector(self, pixels: np.ndarray) -> dict:
        pixels = pixels.reshape(-1, 3).astype(np.float32)
        if len(pixels) == 0:
            pixels = np.array([[160.0, 120.0, 105.0]], dtype=np.float32)
        mean_rgb = pixels.mean(axis=0)
        lab = self._rgb_to_lab(pixels)
        lab_mean = lab.mean(axis=0)
        hsv = self._rgb_to_hsv(pixels)
        hsv_mean = hsv.mean(axis=0)
        lab_chroma = float(np.sqrt(lab_mean[1] ** 2 + lab_mean[2] ** 2))
        warmth = float(((mean_rgb[0] - mean_rgb[2]) + 0.42 * (mean_rgb[1] - mean_rgb[2])) / 255)
        density = min(1.0, len(pixels) / 2600)
        luminance = pixels @ np.array([0.2126, 0.7152, 0.0722])
        spread = float(np.std(luminance) / 255)
        quality = min(1.0, max(0.18, 0.35 + density * 0.45 + (0.18 if spread < 0.14 else 0.06)))
        return {
            "mean_rgb": mean_rgb,
            "lab_l": float(lab_mean[0]),
            "lab_a": float(lab_mean[1]),
            "lab_b": float(lab_mean[2]),
            "lab_chroma": lab_chroma,
            "hsv_h": float(hsv_mean[0]),
            "hsv_s": float(hsv_mean[1]),
            "hsv_v": float(hsv_mean[2]),
            "warmth": warmth,
            "quality": quality,
            "skin_density": density,
            "pixel_count": float(len(pixels)),
        }

    def _color_season_probs(self, vector: dict) -> dict[str, float] | None:
        if not vector:
            return None
        lab_l = float(vector["lab_l"])
        lab_b = float(vector["lab_b"])
        lab_chroma = float(vector["lab_chroma"])
        hsv_s = float(vector["hsv_s"])
        hsv_v = float(vector["hsv_v"])
        warmth = float(vector["warmth"])

        warm_prob = self._clamp(0.5 + lab_b / 42 + warmth * 1.35, 0.08, 0.92)
        light_axis = self._clamp((lab_l - 42) / 34, 0.05, 0.95)
        vivid_axis = self._clamp(0.58 * hsv_s + 0.42 * (lab_chroma / 42), 0.05, 0.95)
        deep_axis = self._clamp(1.0 - (0.68 * light_axis + 0.32 * hsv_v), 0.05, 0.95)
        muted_axis = self._clamp(1.0 - vivid_axis, 0.05, 0.95)

        scores = {
            "spring": warm_prob * (0.6 * light_axis + 0.4 * vivid_axis),
            "autumn": warm_prob * (0.54 * deep_axis + 0.46 * muted_axis),
            "summer": (1.0 - warm_prob) * (0.58 * light_axis + 0.42 * muted_axis),
            "winter": (1.0 - warm_prob) * (0.52 * deep_axis + 0.48 * vivid_axis),
        }
        smoothed = {season: score + 0.035 for season, score in scores.items()}
        total = max(1e-6, sum(smoothed.values()))
        return {season: score / total for season, score in smoothed.items()}

    def _rgb_to_lab(self, pixels: np.ndarray) -> np.ndarray:
        rgb = np.clip(pixels / 255.0, 0.0, 1.0)
        linear = np.where(rgb > 0.04045, ((rgb + 0.055) / 1.055) ** 2.4, rgb / 12.92)
        xyz = linear @ np.array(
            [
                [0.4124564, 0.3575761, 0.1804375],
                [0.2126729, 0.7151522, 0.0721750],
                [0.0193339, 0.1191920, 0.9503041],
            ],
            dtype=np.float32,
        ).T
        xyz = xyz / np.array([0.95047, 1.0, 1.08883], dtype=np.float32)
        epsilon = 216 / 24389
        kappa = 24389 / 27
        f = np.where(xyz > epsilon, np.cbrt(xyz), (kappa * xyz + 16) / 116)
        l = 116 * f[:, 1] - 16
        a = 500 * (f[:, 0] - f[:, 1])
        b = 200 * (f[:, 1] - f[:, 2])
        return np.stack([l, a, b], axis=1)

    def _rgb_to_hsv(self, pixels: np.ndarray) -> np.ndarray:
        rgb = np.clip(pixels / 255.0, 0.0, 1.0)
        hsv = np.array([colorsys.rgb_to_hsv(float(r), float(g), float(b)) for r, g, b in rgb], dtype=np.float32)
        return hsv

    def _clamp(self, value: float, low: float, high: float) -> float:
        return min(high, max(low, float(value)))

    def _center_pixels(self, rgb: np.ndarray) -> np.ndarray:
        height, width, _ = rgb.shape
        y1, y2 = int(height * 0.35), int(height * 0.62)
        x1, x2 = int(width * 0.34), int(width * 0.66)
        return rgb[y1:y2, x1:x2].reshape(-1, 3)

    def _summary(
        self,
        profile: PersonalColorProfile,
        brightness: float,
        chroma: float,
        warmth: float,
        redness: float,
        model_used: bool,
    ) -> str:
        light_text = "밝은" if brightness >= 0.66 else "깊이 있는" if brightness <= 0.48 else "중간 밝기의"
        chroma_text = "선명한" if chroma >= 0.18 else "부드러운"
        if model_used:
            tone_text = "쿨 톤 얼굴 색 분포" if profile.tone == "cool" else "웜 톤 얼굴 색 분포"
            if redness > 0.08:
                return f"{light_text} 피부 밝기와 {chroma_text} 대비, {tone_text}와 로지한 혈색을 종합해 {profile.label} 타입으로 판정했습니다."
            return f"{light_text} 피부 밝기와 {chroma_text} 대비, {tone_text}를 종합해 {profile.label} 타입으로 판정했습니다."
        tone_text = "노란기와 따뜻함" if warmth >= 0.035 else "붉은기와 차가움"
        if redness > 0.08:
            tone_text += ", 로지한 혈색"
        return f"{light_text} 피부 밝기와 {chroma_text} 대비, {tone_text}이 감지되어 {profile.label} 경향으로 분석했습니다."


# ── 웹 계정에 저장된 퍼스널컬러 → 결과지 ──────────────────────────────────────────
# 웹 마이페이지의 8종 라벨을 앱의 PROFILES 키로 옮긴다. 사진 분석 없이 팔레트/메이크업
# 추천과 아이템매칭 검색어를 바로 만들기 위한 것이다(이미 아는 사람에게 다시 찍으라고
# 하지 않으려고). PROFILES 에는 봄이 하나뿐이라 spring_bright/spring_warm 이 같은 곳으로
# 간다 — 봄 계열은 라이트 하나로만 세분돼 있고, 없는 프로필을 지어내면 팔레트가 틀린다.
WEB_LABEL_TO_PROFILE_KEY: dict[str, tuple[str, str]] = {
    "spring_bright": ("warm", "light"),
    "spring_warm": ("warm", "light"),
    "summer_light": ("cool", "light"),
    "summer_mute": ("cool", "soft"),
    "autumn_warm": ("warm", "deep"),
    "autumn_mute": ("warm", "soft"),
    "winter_clear": ("cool", "bright"),
    "winter_deep": ("cool", "deep"),
}


def profile_from_web_label(web_label: str) -> PersonalColorProfile | None:
    """웹 라벨(spring_bright 등)에 해당하는 프로필. 모르는 라벨이면 None."""
    key = WEB_LABEL_TO_PROFILE_KEY.get((web_label or "").strip().lower())
    return PROFILES.get(key) if key else None


def declared_personal_color_result(web_label: str) -> PersonalColorResponse | None:
    """사진 없이, 사용자가 이미 아는 퍼스널컬러로 결과지를 만든다.

    측정한 값이 아니므로 metrics 는 비우고 confidence 는 1.0 으로 둔다 — 모델 확률이
    아니라 '본인이 신고한 값'이라는 뜻이다. 프론트는 이 결과를 분석 결과와 똑같이
    아이템매칭 검색어로 넘길 수 있다.
    """
    profile = profile_from_web_label(web_label)
    if profile is None:
        return None
    return PersonalColorResponse(
        season=profile.season,
        tone=profile.tone,
        subtype=profile.subtype,
        label=profile.label,
        decision_note="회원 정보에 저장된 퍼스널 컬러를 그대로 사용했습니다.",
        confidence=1.0,
        skin_summary=f"{profile.label} 기준으로 어울리는 색을 정리했습니다.",
        palette=list(profile.palette),
        makeup=profile.makeup,
        advice=list(profile.advice),
        metrics={},
    )

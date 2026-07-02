from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import numpy as np
from PIL import Image, ImageOps

from app.ai.personal_color_model import SEASON_TONE, EfficientNetSeasonClassifier
from app.core.config import get_settings
from app.schemas.api import PersonalColorMakeup, PersonalColorResponse

# 학습된 계절 분류기(있으면 웜/쿨을 모델로). 최초 사용 시 1회 로드해 재사용.
_season_classifier: EfficientNetSeasonClassifier | None = None


def _get_season_classifier() -> EfficientNetSeasonClassifier:
    global _season_classifier
    if _season_classifier is None:
        _season_classifier = EfficientNetSeasonClassifier(get_settings().resolved_personal_color_model_path)
    return _season_classifier


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
        ),
        advice=["차분한 로즈, 모브, 그레이시 톤이 자연스럽습니다.", "강한 형광색보다 부드러운 저채도 컬러를 추천합니다."],
    ),
}


class PersonalColorAnalyzer:
    def analyze(self, image_bytes: bytes) -> PersonalColorResponse:
        original_rgb = self._load_rgb(image_bytes)
        # 조명 색온도 캐스트 제거: 눈흰자(공막) 기준 색항상성. 같은 사람이 사진마다
        # 봄웜↔가을웜으로 뒤집히는 주원인(warmth 흔들림)을 줄인다. 눈흰자를 못 찾으면 원본 유지.
        balanced_rgb, white_balanced = self._white_balance(original_rgb)
        skin_pixels = self._skin_pixels(balanced_rgb)
        if skin_pixels.size == 0:
            skin_pixels = self._center_pixels(balanced_rgb)

        mean_rgb = skin_pixels.mean(axis=0)
        brightness = float(np.mean(mean_rgb) / 255)
        chroma = float((np.max(mean_rgb) - np.min(mean_rgb)) / 255)
        warmth = float(((mean_rgb[0] - mean_rgb[2]) + 0.42 * (mean_rgb[1] - mean_rgb[2])) / 255)
        redness = float((mean_rgb[0] - mean_rgb[1]) / 255)

        # 웜/쿨(계절)은 주관적이라 학습 모델이 있으면 모델로 결정, 없으면 warmth 휴리스틱.
        # subtype(밝기/선명도)은 측정 가능한 축이라 WB 보정 지표로 계산한다.
        season_pred = self._predict_season(original_rgb)
        if season_pred is not None:
            season, model_conf = season_pred
            tone = SEASON_TONE[season]
            subtype = self._subtype_for_model_season(season, brightness, chroma)
            model_used = True
        else:
            tone = "warm" if warmth >= 0.035 else "cool"
            subtype = self._subtype_from_metrics(brightness, chroma, tone)
            model_used = False

        profile = PROFILES.get((tone, subtype)) or PROFILES[(tone, "soft")]
        if model_used:
            confidence = min(0.97, max(0.6, model_conf))
        else:
            confidence = min(0.9, max(0.56, 0.62 + abs(warmth) * 1.8 + abs(brightness - 0.58) * 0.22 + chroma * 0.24))
        summary = self._summary(profile, brightness, chroma, warmth, redness)
        capture_advice = self._capture_advice(confidence, white_balanced, model_used, brightness, chroma)

        return PersonalColorResponse(
            season=profile.season,
            tone=profile.tone,
            subtype=profile.subtype,
            label=profile.label,
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
                "model_used": 1.0 if model_used else 0.0,
                "capture_quality": round(self._capture_quality(confidence, white_balanced, model_used, brightness, chroma), 3),
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

    def _predict_season(self, rgb: np.ndarray) -> tuple[str, float] | None:
        """학습된 계절 분류기가 있으면 (계절, 신뢰도), 없으면 None(→휴리스틱)."""
        classifier = _get_season_classifier()
        if not classifier.available:
            return None
        try:
            return classifier.predict(Image.fromarray(rgb.astype(np.uint8)))
        except Exception:
            return None

    def _capture_quality(
        self,
        confidence: float,
        white_balanced: bool,
        model_used: bool,
        brightness: float,
        chroma: float,
    ) -> float:
        quality = 0.52 + confidence * 0.28
        quality += 0.08 if white_balanced else -0.06
        quality += 0.08 if model_used else -0.04
        if 0.38 <= brightness <= 0.76:
            quality += 0.06
        else:
            quality -= 0.08
        if chroma < 0.035:
            quality -= 0.05
        return min(1.0, max(0.0, quality))

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

    def _skin_pixels(self, rgb: np.ndarray) -> np.ndarray:
        height, width, _ = rgb.shape
        y1, y2 = int(height * 0.18), int(height * 0.82)
        x1, x2 = int(width * 0.2), int(width * 0.8)
        crop = rgb[y1:y2, x1:x2]
        r, g, b = crop[..., 0], crop[..., 1], crop[..., 2]
        maxc = np.max(crop, axis=2)
        minc = np.min(crop, axis=2)
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
        pixels = crop[mask]
        if len(pixels) > 1800:
            luminance = pixels @ np.array([0.2126, 0.7152, 0.0722])
            lo, hi = np.percentile(luminance, [15, 85])
            pixels = pixels[(luminance >= lo) & (luminance <= hi)]
        return pixels

    def _center_pixels(self, rgb: np.ndarray) -> np.ndarray:
        height, width, _ = rgb.shape
        y1, y2 = int(height * 0.35), int(height * 0.62)
        x1, x2 = int(width * 0.34), int(width * 0.66)
        return rgb[y1:y2, x1:x2].reshape(-1, 3)

    def _summary(self, profile: PersonalColorProfile, brightness: float, chroma: float, warmth: float, redness: float) -> str:
        light_text = "밝은" if brightness >= 0.66 else "깊이 있는" if brightness <= 0.48 else "중간 밝기의"
        chroma_text = "선명한" if chroma >= 0.18 else "부드러운"
        tone_text = "노란기와 따뜻함" if warmth >= 0.035 else "붉은기와 차가움"
        if redness > 0.08:
            tone_text += ", 로지한 혈색"
        return f"{light_text} 피부 밝기와 {chroma_text} 대비, {tone_text}이 감지되어 {profile.label} 경향으로 분석했습니다."

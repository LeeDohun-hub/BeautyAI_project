"""SKN16 부트캠프 팀(SKN16-FINAL-4Team) 퍼스널컬러 분류기 래퍼.

OpenCV 얼굴검출 + Gray-World 화이트밸런스(5%) + 볼/이마/턱 LAB 중앙값 특징 →
RandomForest 4계절 모델 + 규칙 기반 세부톤. 사용자 요청으로 기존 EfficientNet+블렌드를
이 분류기로 전면 교체한다(2026-07-08).

analyzer가 기대하는 season_probs({spring,summer,autumn,winter}) 형태로 노출한다.
"""
from __future__ import annotations

import io
import contextlib
from typing import Any

import numpy as np

SEASONS = ("spring", "summer", "autumn", "winter")
_KO2EN = {"봄": "spring", "여름": "summer", "가을": "autumn", "겨울": "winter"}
# 세부톤(한글) → 앱 subtype(light/bright/deep/soft)
_SUBTYPE_KO2EN = {
    "라이트": "light", "브라이트": "bright", "클리어": "bright",
    "딥": "deep", "소프트": "soft", "뮤트": "soft", "트루": "soft",
}


class SKN16SeasonClassifier:
    """SKN16 RobustLandmarkClassifier 래퍼. BGR uint8 이미지 → season_probs/subtype."""

    def __init__(self) -> None:
        self._clf: Any | None = None
        self._ready: bool | None = None

    def load(self) -> bool:
        if self._ready is not None:
            return self._ready
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                from app.ai.skn16.landmark_classifier import RobustLandmarkClassifier
                self._clf = RobustLandmarkClassifier()
            self._ready = self._clf is not None and getattr(self._clf, "season_model", None) is not None
        except Exception:
            self._clf = None
            self._ready = False
        return self._ready

    @property
    def available(self) -> bool:
        return self.load()

    def predict(self, image_bgr: np.ndarray) -> dict | None:
        """BGR uint8 이미지 한 장 → {season_probs, subtype, tone} 또는 None(얼굴 실패)."""
        if not self.load() or self._clf is None:
            return None
        clf = self._clf
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                dfes = clf.detect_face_and_extract_skin(image_bgr)
                if isinstance(dfes, tuple) and len(dfes) >= 2:
                    skin, masks = dfes[0], dfes[1]
                else:
                    return None
                if skin is None or masks is None:
                    return None
                feats = clf.extract_robust_lab_features(skin, masks)
                a = float(feats["a_median"])
                b = float(feats["b_median"])
                chroma = float(feats["chroma"])
                L = float(feats["L_cheek_raw"])
                proba = clf.season_model.predict_proba([[a, b, chroma, L]])[0]
                classes = list(clf.season_model.classes_)
        except Exception:
            return None

        season_probs = {s: 0.0 for s in SEASONS}
        for cls, p in zip(classes, proba):
            en = _KO2EN.get(str(cls).strip())
            if en:
                season_probs[en] = float(p)
        total = sum(season_probs.values())
        if total <= 0:
            return None
        season_probs = {k: v / total for k, v in season_probs.items()}

        season_en = max(season_probs, key=season_probs.get)
        season_ko = {v: k for k, v in _KO2EN.items()}[season_en]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                subtype_ko = clf.classify_subtype_relative(L, a, b, season_ko)
        except Exception:
            subtype_ko = ""
        subtype = _SUBTYPE_KO2EN.get(str(subtype_ko).strip(), "")
        tone = "warm" if season_en in ("spring", "autumn") else "cool"
        return {"season_probs": season_probs, "subtype": subtype, "tone": tone,
                "lab": {"L": L, "a": a, "b": b, "chroma": chroma}}


_skn16_classifier: SKN16SeasonClassifier | None = None


def get_skn16_classifier() -> SKN16SeasonClassifier:
    global _skn16_classifier
    if _skn16_classifier is None:
        _skn16_classifier = SKN16SeasonClassifier()
    return _skn16_classifier

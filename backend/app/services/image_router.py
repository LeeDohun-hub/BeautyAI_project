from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class ImageRoute:
    analysis_mode: str
    reason: str
    face_count: int = 0
    largest_face_ratio: float = 0.0


class SkinImageRouter:
    def __init__(self) -> None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self.face_cascade = cv2.CascadeClassifier(cascade_path)

    def route(self, image_bytes: bytes) -> ImageRoute:
        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        frame = np.asarray(image)
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        faces = self.face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.08,
            minNeighbors=5,
            minSize=(48, 48),
        )
        if len(faces) == 0:
            return ImageRoute(
                analysis_mode="body",
                reason="얼굴이 뚜렷하게 검출되지 않아 바디 피부 케어 분석으로 처리했습니다.",
            )

        image_area = max(1, frame.shape[0] * frame.shape[1])
        largest_face_ratio = max((w * h) / image_area for (_x, _y, w, h) in faces)
        if largest_face_ratio >= 0.025:
            return ImageRoute(
                analysis_mode="face",
                reason="얼굴 영역이 충분히 검출되어 얼굴 피부 케어 분석으로 처리했습니다.",
                face_count=len(faces),
                largest_face_ratio=round(largest_face_ratio, 4),
            )

        return ImageRoute(
            analysis_mode="body",
            reason="검출된 얼굴 영역이 작아 바디 피부 케어 분석으로 처리했습니다.",
            face_count=len(faces),
            largest_face_ratio=round(largest_face_ratio, 4),
        )


_router: SkinImageRouter | None = None


def get_skin_image_router() -> SkinImageRouter:
    global _router
    if _router is None:
        _router = SkinImageRouter()
    return _router


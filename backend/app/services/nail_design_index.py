"""네일 디자인 리트리벌 — 검출·대표색·임베딩·최근접 검색 (설계문서 B안).

**이 모듈이 알고리즘의 원본이다.** `scripts/build_nail_design_index.py`(인덱스 빌드)와
`scripts/query_nail_design.py`(CLI 질의)가 여기서 import 해 쓴다. 빌드와 서빙이 서로 다른
구현을 쓰면 같은 사진에서 다른 색·임베딩이 나와 검색 품질이 조용히 망가진다.

무거운 의존성(torch·ultralytics)은 요청 시점에 지연 임포트하고, 없거나 모델 파일이 빠지면
예외 대신 `available=False` 로 떨어뜨린다(다른 AI 모듈과 동일한 규약).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.core.config import get_settings

EMBED_SIZE = 128        # 인덱스를 만든 입력 크기 — 바꾸면 인덱스를 다시 만들어야 한다
MIN_CROP_PX = 32        # 새끼발톱·초점흐림 크롭은 임베딩이 무의미하다
DEFAULT_CONF = 0.4


# --------------------------------------------------------------------------- 색

def dominant_color(crop: np.ndarray) -> tuple[list[float], str]:
    """크롭 중앙부의 대표색을 (Lab, hex) 로. 반사 하이라이트는 제외한다.

    젤네일은 정반사가 커서 그냥 평균내면 대표색이 흰색으로 쏠린다 → L 상위 15% 제거.
    """
    import cv2

    h, w = crop.shape[:2]
    y0, y1 = int(h * 0.2), max(int(h * 0.8), int(h * 0.2) + 1)
    x0, x1 = int(w * 0.2), max(int(w * 0.8), int(w * 0.2) + 1)
    center = crop[y0:y1, x0:x1].reshape(-1, 3).astype(np.float32)
    if len(center) < 8:
        center = crop.reshape(-1, 3).astype(np.float32)

    lab = cv2.cvtColor(center.reshape(-1, 1, 3).astype(np.uint8), cv2.COLOR_BGR2LAB)
    lab = lab.reshape(-1, 3).astype(np.float32)
    keep = lab[:, 0] <= np.percentile(lab[:, 0], 85)
    if keep.sum() >= 8:
        lab, center = lab[keep], center[keep]

    from sklearn.cluster import KMeans

    k = min(3, max(1, len(lab) // 50))
    if k > 1:
        km = KMeans(n_clusters=k, n_init=3, random_state=0).fit(lab)
        biggest = int(np.argmax(np.bincount(km.labels_)))
        lab_mean = km.cluster_centers_[biggest]
        bgr_mean = center[km.labels_ == biggest].mean(axis=0)
    else:
        lab_mean = lab.mean(axis=0)
        bgr_mean = center.mean(axis=0)

    b, g, r = (int(np.clip(v, 0, 255)) for v in bgr_mean)
    # OpenCV Lab(uint8) → 실제 Lab 스케일
    L, A, B = float(lab_mean[0]) * 100 / 255, float(lab_mean[1]) - 128, float(lab_mean[2]) - 128
    return [round(L, 2), round(A, 2), round(B, 2)], f"#{r:02x}{g:02x}{b:02x}"


# --------------------------------------------------------------------------- 임베딩

class Embedder:
    """EfficientNet-B0 penultimate feature(1280d, L2 정규화).

    가중치는 **로컬 체크포인트**에서 읽는다(런타임 다운로드 금지). 인덱스를 만든 가중치와
    같아야 하므로, 체크포인트가 없으면 조용히 다른 가중치로 대체하지 않고 실패시킨다.
    """

    def __init__(self, weights_path: str | Path | None = None) -> None:
        settings = get_settings()
        raw = Path(weights_path or settings.nail_embedder_model_path)
        self.weights_path = raw if raw.is_absolute() else settings.project_root / raw
        self._net = None
        self._tf = None

    @property
    def available(self) -> bool:
        return self.weights_path.exists()

    def _ensure(self) -> bool:
        if self._net is not None:
            return True
        if not self.available:
            return False
        try:
            import torch
            from torchvision import models, transforms
        except ImportError:
            return False

        net = models.efficientnet_b0(weights=None)
        net.classifier = torch.nn.Identity()
        state = torch.load(str(self.weights_path), map_location="cpu")
        net.load_state_dict(state["model_state_dict"] if "model_state_dict" in state else state)
        net.eval()
        self._net = net
        self._torch = torch
        self._tf = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])
        return True

    def __call__(self, crops: list[np.ndarray]) -> np.ndarray:
        import cv2

        if not self._ensure():
            raise RuntimeError(f"임베딩 가중치를 찾을 수 없습니다: {self.weights_path}")
        torch = self._torch
        batch = [
            self._tf(cv2.cvtColor(cv2.resize(c, (EMBED_SIZE, EMBED_SIZE)), cv2.COLOR_BGR2RGB))
            for c in crops
        ]
        with torch.no_grad():
            feat = self._net(torch.stack(batch)).cpu().numpy().astype(np.float32)
        return feat / np.clip(np.linalg.norm(feat, axis=1, keepdims=True), 1e-8, None)


# --------------------------------------------------------------------------- 인덱스

@dataclass(frozen=True)
class DesignMatch:
    design_id: str
    region: str
    similarity: float
    color_hex: str
    delta_e: float
    thumbnail_path: str | None


class NailDesignIndex:
    """임베딩·메타·썸네일을 담은 리트리벌 인덱스. 파일이 없으면 available=False."""

    def __init__(self, index_dir: str | Path | None = None) -> None:
        settings = get_settings()
        raw = Path(index_dir or settings.nail_index_dir)
        self.dir = raw if raw.is_absolute() else settings.project_root / raw
        self._emb: np.ndarray | None = None
        self._meta: list[dict] | None = None
        self._labs: np.ndarray | None = None

    @property
    def available(self) -> bool:
        return (self.dir / "embeddings.npy").exists() and (self.dir / "meta.json").exists()

    def load(self) -> bool:
        if self._emb is not None:
            return True
        if not self.available:
            return False
        emb = np.load(self.dir / "embeddings.npy")
        meta = json.loads((self.dir / "meta.json").read_text(encoding="utf-8"))
        if len(emb) != len(meta):
            # 인덱스가 반쯤 갱신된 상태 — 조용히 잘못된 결과를 내느니 비활성이 낫다.
            return False
        self._emb, self._meta = emb, meta
        self._labs = np.array([m["color_lab"] for m in meta], dtype=np.float32)
        return True

    @property
    def size(self) -> int:
        return 0 if self._meta is None else len(self._meta)

    def search(self, vec: np.ndarray, lab: list[float], top_k: int,
               color_weight: float, exclude_design: str | None = None) -> list[DesignMatch]:
        if not self.load():
            return []
        scores = self._emb @ vec
        if color_weight:
            scores = scores - color_weight * (
                np.linalg.norm(self._labs - np.asarray(lab, dtype=np.float32), axis=1) / 100.0
            )
        if exclude_design:
            scores = np.where(
                np.array([m["design_id"] for m in self._meta]) == exclude_design, -np.inf, scores
            )
        top = np.argsort(scores)[::-1][:top_k]
        out = []
        for i in top:
            m = self._meta[int(i)]
            thumb = self.dir / "thumbs" / f"{m['id']}.png"
            out.append(DesignMatch(
                design_id=m["design_id"],
                region=m["region"],
                similarity=round(float(scores[int(i)]), 4),
                color_hex=m["color_hex"],
                delta_e=round(float(np.linalg.norm(np.asarray(m["color_lab"]) - np.asarray(lab))), 2),
                thumbnail_path=str(thumb) if thumb.exists() else None,
            ))
        return out


@lru_cache(maxsize=1)
def get_index() -> NailDesignIndex:
    return NailDesignIndex()


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    return Embedder()


@lru_cache(maxsize=1)
def _get_detector():
    """YOLOv8 세그 모델. 없으면 None(기능 비활성)."""
    settings = get_settings()
    raw = Path(settings.nail_seg_model_path)
    path = raw if raw.is_absolute() else settings.project_root / raw
    if not path.exists():
        return None
    try:
        from ultralytics import YOLO
    except ImportError:
        return None
    return YOLO(str(path))


def detect_nails(image_bgr: np.ndarray, conf: float = DEFAULT_CONF) -> list[tuple[tuple[int, int, int, int], float]]:
    """(bbox, confidence) 목록. 큰 것부터 — 엄지·검지가 보통 가장 선명하다."""
    model = _get_detector()
    if model is None:
        return []
    res = model.predict(image_bgr, conf=conf, verbose=False)[0]
    if res.boxes is None or len(res.boxes) == 0:
        return []
    boxes = res.boxes.xyxy.cpu().numpy().astype(int)
    confs = [float(c) for c in res.boxes.conf]
    rows = [((int(x1), int(y1), int(x2), int(y2)), c) for (x1, y1, x2, y2), c in zip(boxes, confs)]
    rows.sort(key=lambda r: (r[0][2] - r[0][0]) * (r[0][3] - r[0][1]), reverse=True)
    return rows


def feature_available() -> bool:
    return _get_detector() is not None and get_embedder().available and get_index().available

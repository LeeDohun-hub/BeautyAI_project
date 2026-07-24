"""AI-Hub 글로벌 다인종 데이터로 만든 퍼스널컬러 분류기 (조명 불변 Lab 회귀 방식).

기존 분류기(사진 픽셀 → 계절 직행)와 원리가 다르다.

배경:
  AI-Hub '글로벌 다인종 피부색 데이터'는 같은 인물을 2x2 조명({500,5000}lux x {3200,5600}K)으로
  4장씩 찍고, 피부색은 사진이 아니라 **분광측색기(CM26d)로 직접 측정**해 두었다.
  동일인 4장은 육안으로 서로 다른 계절처럼 보인다(조명이 사진 속 피부색을 지배한다).
  그래서 사진에서 계절을 바로 배우면 조명을 배우게 된다.

설계(2단):
  1) 사진 → **참 피부 Lab 회귀**. 정답이 기계 실측이라 조명과 무관하고, 같은 인물의 서로 다른
     조명 사진이 **같은 정답**을 가지므로 조명 불변성이 손실로 강제된다.
  2) 참 Lab → 계절 규칙. 퍼스널컬러의 웜/쿨은 '깊이를 보정한 뒤의 언더톤'이므로 b* 를 ITA 로
     회귀한 **잔차 부호**를 웜/쿨로, ITA 중앙값을 깊이 경계로 쓴다.

실측(동북아 646명, 인물 단위 분리, val 129명 / GALAXY 24 Ultra 촬영):
  - ΔE(예측 Lab vs 분광측색 실측) 2.655   (평균만 찍기 3.2)
  - **조명 일치도 85.3%** — 같은 사람의 조명만 다른 사진이 같은 계절로 나오는 비율
  - 계절 정확도 55.0% (예측Lab→규칙 vs 실측Lab→규칙, 4지선다 찍기 25%)

⚠️ 한계(정직하게):
  - 학습 데이터는 **동북아 + GALAXY 24 Ultra + 스튜디오 조명**이다. 다른 기기/환경은 미검증.
  - **5000lux 사진은 피부가 포화(클리핑)** 된다(피부 픽셀의 4~17%가 255). 정보가 파괴돼 복원 불가라
    과노출 사진에서는 성능이 떨어진다. 위 수치는 클리핑 없는 500lux 기준.
  - 계절 라벨은 **분광측색 실측 피부색에서 규칙으로 유도**한 값이다. 사람이 진단한 퍼스널컬러와
    일치하는지는 이 데이터만으로 확인할 수 없다(AI-Hub 에 진단 라벨이 없음).
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

SEASONS = ["spring", "summer", "autumn", "winter"]

# 계절 규칙 상수 — 동북아 train 인물 517명으로 적합(scripts/eval_aihub_pc.py 참고).
# b* = SLOPE·ITA + INTERCEPT 가 '깊이에 따라 기대되는 노란기'. 잔차가 양수면 웜.
UNDERTONE_SLOPE = -0.1496
UNDERTONE_INTERCEPT = 20.53
DEPTH_ITA_BOUNDARY = 35.04


def ita_from_lab(lab_l: float, lab_b: float) -> float:
    """Individual Typology Angle — 피부 깊이(밝기) 표준 지표."""
    return math.degrees(math.atan2(lab_l - 50.0, lab_b))


def season_from_lab(lab_l: float, lab_b: float) -> str:
    ita = ita_from_lab(lab_l, lab_b)
    warm = lab_b - (UNDERTONE_SLOPE * ita + UNDERTONE_INTERCEPT) > 0
    light = ita > DEPTH_ITA_BOUNDARY
    if warm:
        return "spring" if light else "autumn"
    return "summer" if light else "winter"


class AihubLabSeasonClassifier:
    """사진 → 참 피부 Lab → 계절. 모델 파일이 없으면 비활성(호출부가 폴백).

    앙상블: 여러 체크포인트의 예측 Lab 평균 + 좌우반전 TTA 로 예측을 안정화한다.
    v1(3차원 얼굴평균 Lab)과 v3(9차원=3부위xLab)를 함께 받는다 — 후자는 얼굴평균으로 환산한다.
    실측(val 129명): 프레임정확도 55.4→57.6%, 조명일치도 50.4→61.2%, ΔE 2.642→2.586.
    """

    def __init__(self, model_paths: str | list[str], tta: bool = True) -> None:
        if isinstance(model_paths, str):
            model_paths = [model_paths]
        self.model_paths = [Path(p) for p in model_paths]
        self.tta = tta
        # 로드된 모델들: 각 (net, head, out_dim, mean, std)
        self.members: list[tuple[Any, Any, int, Any, Any]] = []
        self.transform: Any | None = None
        self.torch: Any | None = None

    @property
    def available(self) -> bool:
        return any(p.exists() for p in self.model_paths)

    def load(self) -> bool:
        if self.members:
            return True
        if not self.available:
            return False
        try:
            import numpy as np
            import torch
            from torchvision import models, transforms
        except ImportError:
            return False

        for path in self.model_paths:
            if not path.exists():
                continue
            ck = torch.load(path, map_location="cpu", weights_only=False)
            net = models.efficientnet_b0(weights=None)
            dim = net.classifier[1].in_features
            net.classifier = torch.nn.Identity()
            net.load_state_dict(ck["feat"])
            net.eval()
            # 출력 차원은 체크포인트 head 가중치에서 읽는다(v1=3, v3=9).
            out_dim = int(ck["head"]["weight"].shape[0])
            head = torch.nn.Linear(dim, out_dim)
            head.load_state_dict(ck["head"])
            head.eval()
            mean = np.asarray(ck.get("target_mean", ck.get("lab_mean")), dtype=np.float32)
            std = np.asarray(ck.get("target_std", ck.get("lab_std")), dtype=np.float32)
            self.members.append((net, head, out_dim, mean, std))

        if not self.members:
            return False
        self.torch = torch
        self.transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])
        return True

    @staticmethod
    def _as_pil(image_rgb):
        """PIL 이미지 또는 numpy(H,W,3) 둘 다 받는다(호출부가 numpy 로 넘긴다)."""
        from PIL import Image

        if isinstance(image_rgb, Image.Image):
            return image_rgb.convert("RGB")
        import numpy as np

        arr = np.asarray(image_rgb)
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        return Image.fromarray(arr).convert("RGB")

    def predict_lab(self, image_rgb) -> tuple[float, float, float] | None:
        """이미지(PIL 또는 numpy RGB) → 예측 참 피부 Lab (L*, a*, b*).

        앙상블 멤버 × TTA(원본/좌우반전)의 얼굴평균 Lab 를 평균한다.
        """
        if not self.load():
            return None
        import numpy as np

        x = self.transform(self._as_pil(image_rgb)).unsqueeze(0)
        views = [x, self.torch.flip(x, dims=[3])] if self.tta else [x]
        labs = []
        with self.torch.no_grad():
            for net, head, out_dim, mean, std in self.members:
                for v in views:
                    out = head(net(v)).numpy()[0] * std + mean
                    if out_dim == 9:  # 3부위 x Lab → 얼굴평균
                        out = out.reshape(3, 3).mean(0)
                    labs.append(out)
        lab = np.mean(labs, axis=0)
        return float(lab[0]), float(lab[1]), float(lab[2])

    def predict_season(self, image_rgb) -> tuple[str, dict[str, float]] | None:
        """RGB PIL 이미지 → (계절, 부가 측정값)."""
        lab = self.predict_lab(image_rgb)
        if lab is None:
            return None
        L, a, b = lab
        ita = ita_from_lab(L, b)
        return season_from_lab(L, b), {
            "pred_lab_l": round(L, 2),
            "pred_lab_a": round(a, 2),
            "pred_lab_b": round(b, 2),
            "pred_ita": round(ita, 2),
            # 경계까지의 여유. 0 에 가까우면 계절이 뒤집히기 쉬운 애매한 얼굴이다.
            "undertone_margin": round(b - (UNDERTONE_SLOPE * ita + UNDERTONE_INTERCEPT), 3),
            "depth_margin": round(ita - DEPTH_ITA_BOUNDARY, 2),
        }

    def predict_season_probs(self, image_rgb) -> dict[str, float] | None:
        """RGB PIL 이미지 → 4계절 확률.

        이 분류기의 계절은 **웜/쿨 × 밝기/깊이 2x2** 로 정의되므로, 각 축을 독립 확률로 보고
        곱해서 4계절 확률을 만든다(하드 라벨보다 경계 근처를 정직하게 표현하고, 프론트의
        top-2 표시가 그대로 동작한다). 축별 시그모이드 스케일은 동북아 실측 산포:
          - 언더톤 잔차 표준편차 ≈ 1.56
          - ITA 표준편차 ≈ 9.2
        """
        lab = self.predict_lab(image_rgb)
        if lab is None:
            return None
        L, _a, b = lab
        ita = ita_from_lab(L, b)
        undertone_margin = b - (UNDERTONE_SLOPE * ita + UNDERTONE_INTERCEPT)
        depth_margin = ita - DEPTH_ITA_BOUNDARY

        def sigmoid(x: float) -> float:
            return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, x))))

        p_warm = sigmoid(undertone_margin / 1.56)
        p_light = sigmoid(depth_margin / 9.2)
        return {
            "spring": p_warm * p_light,
            "autumn": p_warm * (1.0 - p_light),
            "summer": (1.0 - p_warm) * p_light,
            "winter": (1.0 - p_warm) * (1.0 - p_light),
        }

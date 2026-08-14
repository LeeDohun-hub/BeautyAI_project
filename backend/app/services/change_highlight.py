"""바뀐 자리 찾기 — 시뮬레이션 전/후를 비교해 '어디가' 달라졌는지 좌표로 돌려준다.

왜 필요한가(사용자 지적 2026-08-14): 가상성형·피부 시뮬레이션 결과 이미지를 아무리 잘 만들어도
**엄청 자세히 보지 않으면 어디가 변했는지 모른다.** 설명 문구는 '턱끝 폭을 12% 정리했습니다'
라고 말하는데, 정작 사진에는 그 자리가 표시돼 있지 않다.

화면에 오버레이를 **서버가 구워 내리지 않는** 이유: 이미지에 박아 버리면 끄고 켤 수 없고,
확대해도 같이 뭉개진다. 좌표(0~1 정규화)만 돌려주면 프론트가 원하는 크기로 선명하게 그리고,
사용자가 토글할 수 있다.

돌려주는 것: [{x, y, w, h, strength}] — 이미지 좌상단 기준 0~1 비율.
"""

from __future__ import annotations

import cv2
import numpy as np


def _merge(boxes: list[tuple[int, int, int, int]], gap: int) -> list[tuple[int, int, int, int]]:
    """가까운 상자를 합친다. 잘게 쪼개진 표시는 '어디'를 알려주는 게 아니라 노이즈가 된다."""
    merged: list[list[int]] = []
    for x, y, w, h in sorted(boxes, key=lambda b: -b[2] * b[3]):
        placed = False
        for m in merged:
            if x < m[0] + m[2] + gap and m[0] < x + w + gap and y < m[1] + m[3] + gap and m[1] < y + h + gap:
                nx, ny = min(m[0], x), min(m[1], y)
                m[2] = max(m[0] + m[2], x + w) - nx
                m[3] = max(m[1] + m[3], y + h) - ny
                m[0], m[1] = nx, ny
                placed = True
                break
        if not placed:
            merged.append([x, y, w, h])
    return [(m[0], m[1], m[2], m[3]) for m in merged]


def change_regions(
    before: np.ndarray,
    after: np.ndarray,
    top_k: int = 5,
    min_area_ratio: float = 0.0008,
    # 그 사진의 최대 변화 대비 몇 %부터 '바뀐 것'으로 볼지. 실측 스윕(가상성형):
    #   0.34 → 2덩어리(놓침) / 0.25 → 3 / **0.18 → 4(면적 1.7%)** / 0.12 → 8(노이즈)
    threshold_ratio: float = 0.18,
) -> list[dict]:
    """전/후 이미지에서 실제로 바뀐 영역을 찾는다.

    보정은 대개 **넓고 옅게** 퍼진다(피부결·붉은기). 픽셀 차이를 그대로 임계하면 아무것도
    안 잡히므로, 블러로 뭉쳐서 '면'으로 만든 뒤 상대 임계를 쓴다.
    """
    if before is None or after is None or before.shape != after.shape:
        return []

    h, w = before.shape[:2]
    a = cv2.cvtColor(before, cv2.COLOR_RGB2LAB).astype(np.float32)
    b = cv2.cvtColor(after, cv2.COLOR_RGB2LAB).astype(np.float32)
    # L(명도)보다 a/b(색)의 변화가 눈에 덜 띄므로 가중치를 더 준다.
    diff = np.sqrt(
        (a[:, :, 0] - b[:, :, 0]) ** 2
        + 1.6 * (a[:, :, 1] - b[:, :, 1]) ** 2
        + 1.6 * (a[:, :, 2] - b[:, :, 2]) ** 2
    )
    k = max(3, int(min(h, w) * 0.02) | 1)
    diff = cv2.GaussianBlur(diff, (k, k), 0)

    peak = float(diff.max())
    if peak < 1.5:                      # 눈으로 못 알아볼 정도면 표시하지 않는다
        return []
    # 절대 임계는 사진마다 다르게 걸린다 — 그 사진의 최대 변화 대비로 자른다.
    thresh = max(1.0, peak * threshold_ratio)
    mask = (diff >= thresh).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = h * w * min_area_ratio
    boxes = [cv2.boundingRect(c) for c in contours if cv2.contourArea(c) >= min_area]
    if not boxes:
        return []

    boxes = _merge(boxes, gap=int(min(h, w) * 0.04))
    boxes.sort(key=lambda box: -box[2] * box[3])

    regions: list[dict] = []
    for x, y, bw, bh in boxes[:top_k]:
        patch = diff[y:y + bh, x:x + bw]
        regions.append({
            "x": round(x / w, 4),
            "y": round(y / h, 4),
            "w": round(bw / w, 4),
            "h": round(bh / h, 4),
            # 0~1. 프론트가 표시 진하기를 정하는 데 쓴다.
            "strength": round(float(np.clip(patch.mean() / max(peak, 1e-6), 0, 1)), 3),
        })
    return regions

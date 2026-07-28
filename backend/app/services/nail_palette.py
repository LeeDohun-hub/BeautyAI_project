"""네일 색상 ↔ 퍼스널컬러 시즌 브리지.

`personal_color_analyzer.PROFILES` 의 `makeup.nail` 은 **한국어 색이름**뿐이라(라이브 검색
키워드용) 사진에서 뽑은 실제 색과 기계적으로 비교할 수 없다. 이 모듈이 그 이름에 hex 를 붙여
Lab 으로 바꿔주고, 색 하나가 어느 시즌에 얼마나 맞는지 점수화한다.

용도 두 갈래:
  - 사진 속 네일 디자인 색 → 어느 시즌에 어울리는지 (`rank_seasons`)
  - 사용자의 시즌 → 그 시즌에 맞는 디자인/상품 고르기 (`nail_color_fit`)

⚠️ HEX 값은 색이름을 사람이 보고 정한 **근사치**다(측색값 아님). 시즌 판정의 최종 근거로 쓰지
말고, 색 유사도 정렬·필터 용도로만 쓴다. 이름 자체는 PROFILES 가 원본이며 여기서 바꾸지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass

# PROFILES 의 makeup.nail 에 등장하는 21개 이름 전부에 대응한다.
# (누락 시 test_nail_palette.py 가 잡는다 — 이름이 추가되면 여기도 채워야 한다.)
NAIL_SHADE_HEX: dict[str, str] = {
    # 봄 웜 라이트
    "코랄": "#FF7F5F",
    "피치": "#FFB59E",
    "살구 베이지": "#EBC1A4",
    # 가을 웜 딥
    "브릭": "#9E3B2E",
    "테라코타": "#C46B4E",
    "카멜 브라운": "#A97448",
    # 가을 웜 뮤트
    "누드 베이지": "#D9B79C",
    "로즈 브라운": "#A9736B",
    "카키 브라운": "#7A6A4F",
    # 여름 쿨 라이트
    "로즈 핑크": "#E8A0B4",
    "라벤더 핑크": "#D9A7C7",
    "쿨 핑크": "#E38FA8",
    # 겨울 쿨 딥
    "버건디": "#6E1A2E",
    "체리 레드": "#B3122F",
    "딥 플럼": "#5A2440",
    # 겨울 쿨 브라이트
    "체리 핑크": "#E43D6B",
    "클리어 레드": "#DD1F35",
    "푸시아 핑크": "#D9318A",
    # 여름 쿨 뮤트
    "말린 장미": "#B5717A",
    "모브": "#A87CA0",
    "더스티 로즈": "#C39098",
}


@dataclass(frozen=True)
class ShadeMatch:
    name: str
    hex: str
    delta_e: float
    score: float  # 0~100, 높을수록 잘 맞음


# --------------------------------------------------------------------------- 색공간

def hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def rgb_to_lab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    """sRGB(0~255) → CIE L*a*b* (D65). cv2 없이 계산해 백엔드 의존성을 늘리지 않는다."""
    def _linear(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (_linear(c) for c in rgb)
    # sRGB → XYZ (D65)
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    # D65 백색점으로 정규화
    x, y, z = x / 0.95047, y / 1.00000, z / 1.08883

    def _f(t: float) -> float:
        return t ** (1 / 3) if t > 216 / 24389 else (841 / 108) * t + 4 / 29

    fx, fy, fz = _f(x), _f(y), _f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def hex_to_lab(value: str) -> tuple[float, float, float]:
    return rgb_to_lab(hex_to_rgb(value))


def delta_e76(lab1, lab2) -> float:
    """CIE76 색차. 지각 균일성이 필요해지면 CIEDE2000 으로 교체할 것."""
    return sum((a - b) ** 2 for a, b in zip(lab1, lab2)) ** 0.5


def _score_from_delta(delta: float) -> float:
    """ΔE → 0~100 점수. ΔE 50 이상이면 0점으로 본다(전혀 다른 색)."""
    return round(max(0.0, min(100.0, 100.0 - 2.0 * delta)), 1)


# --------------------------------------------------------------------------- 시즌 팔레트

def _profiles():
    # 순환 import 회피 — analyzer 가 무거워 함수 안에서 늦게 부른다.
    from app.services.personal_color_analyzer import PROFILES

    return PROFILES


def season_nail_shades(tone: str, subtype: str) -> list[tuple[str, str]]:
    """(이름, hex) 목록. hex 가 없는 이름은 조용히 건너뛰지 않고 예외로 드러낸다."""
    profiles = _profiles()
    profile = profiles.get((tone, subtype)) or profiles[(tone, "soft")]
    out = []
    for name in profile.makeup.nail:
        hex_value = NAIL_SHADE_HEX.get(name)
        if hex_value is None:
            raise KeyError(f"NAIL_SHADE_HEX 에 '{name}' 이 없습니다 — PROFILES 에 색이름을 추가했다면 여기도 채우세요.")
        out.append((name, hex_value))
    return out


def nail_color_fit(lab: tuple[float, float, float], tone: str, subtype: str) -> ShadeMatch:
    """색 하나가 해당 시즌 네일 팔레트에 얼마나 맞는지 — 가장 가까운 색조로 판정."""
    best: ShadeMatch | None = None
    for name, hex_value in season_nail_shades(tone, subtype):
        delta = delta_e76(lab, hex_to_lab(hex_value))
        if best is None or delta < best.delta_e:
            best = ShadeMatch(name=name, hex=hex_value, delta_e=round(delta, 2),
                              score=_score_from_delta(delta))
    assert best is not None  # PROFILES 의 nail 은 항상 비어있지 않다
    return best


def rank_seasons(lab: tuple[float, float, float]) -> list[tuple[str, str, str, ShadeMatch]]:
    """색 하나에 대해 (label, tone, subtype, 최적색조)를 잘 맞는 순으로 정렬해 돌려준다."""
    rows = []
    for (tone, subtype), profile in _profiles().items():
        rows.append((profile.label, tone, subtype, nail_color_fit(lab, tone, subtype)))
    rows.sort(key=lambda r: r[3].delta_e)
    return rows

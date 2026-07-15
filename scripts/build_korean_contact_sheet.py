"""한국 연예인 얼굴크롭을 육안 검수용 self-contained HTML로 빌드.

크롭 매니페스트(korean_celebrity_face_crop_manifest.csv)의 로컬 이미지를 base64로 인라인.
셀럽 이름은 크롭 파일명 접두(<이름>_<idx>_<hash>...)에서 파싱. 계절별로 묶음.

실행(BeautyAI_project에서):
    & backend\\.venv\\Scripts\\python.exe scripts/build_korean_contact_sheet.py
출력:
    data/korean_celebrity_contact_sheet.html
"""

from __future__ import annotations

import base64
import csv
import html
from collections import Counter, defaultdict
from pathlib import Path

MANIFEST = Path("data/manifests/korean_celebrity_face_crop_manifest.csv")
OUT = Path("data/korean_celebrity_contact_sheet.html")
SEASON_ORDER = ["spring", "summer", "autumn", "winter"]
SEASON_COLOR = {"spring": "#e8a23d", "summer": "#5aa9d6", "autumn": "#b5651d", "winter": "#6c5ce7"}


def data_uri(path: Path) -> str | None:
    try:
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except OSError:
        return None


def main() -> int:
    by_season: dict[str, list[tuple[str, str]]] = defaultdict(list)  # season -> [(name, uri)]
    with MANIFEST.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            p = Path(row["image_path"])
            name = p.name.split("_")[0]
            uri = data_uri(p)
            if uri:
                by_season[row["season"]].append((name, uri))

    parts = [
        "<style>",
        "body{background:#14161a;color:#e6e6e6;font-family:system-ui,'Segoe UI',sans-serif;margin:0;padding:24px}",
        "h1{font-size:20px}h2{margin-top:32px;text-transform:capitalize}",
        ".note{color:#9aa0a6;font-size:13px;line-height:1.6;max-width:820px}",
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:10px;margin-top:12px}",
        ".card{background:#1e2127;border-radius:8px;overflow:hidden}",
        ".card img{width:100%;height:120px;object-fit:cover;display:block}",
        ".meta{padding:5px 7px;font-size:12px;color:#d0d3d8}",
        "</style>",
        "<h1>한국 연예인 컨센서스 라벨 — 얼굴크롭 검수 (경로 A / Track 2)</h1>",
        "<p class='note'>19명 컨센서스 × 네이버 이미지검색 → 얼굴크롭(프로덕션 검출기). "
        "계절 = 2매체+ 일치 라벨. Pexels 컨택트시트와 비교해보세요 — 실제 한국 얼굴에 "
        "라벨이 조명/검색어가 아니라 <b>전문가 진단 컨센서스</b>로 붙었습니다. "
        "다만 무대조명·메이크업·필터 섞임은 남아있으니 그 정도를 직접 확인하세요.</p>",
    ]
    for season in SEASON_ORDER:
        cards = by_season.get(season, [])
        names = Counter(n for n, _ in cards)
        head = ", ".join(f"{n}({c})" for n, c in names.items())
        parts.append(f"<h2 style='color:{SEASON_COLOR[season]}'>{season} · {len(cards)}장 · {head}</h2>")
        parts.append("<div class='grid'>")
        for name, uri in cards:
            parts.append(
                f"<div class='card'><img loading='lazy' src='{uri}'>"
                f"<div class='meta'>{html.escape(name)}</div></div>"
            )
        parts.append("</div>")

    OUT.write_text("\n".join(parts), encoding="utf-8")
    total = sum(len(v) for v in by_season.values())
    print(f"{total}장 임베드 → {OUT.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

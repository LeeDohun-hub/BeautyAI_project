"""수집한 Pexels 후보를 육안 검수용 self-contained HTML 컨택트시트로 빌드.

썸네일을 다운받아 base64 data URI로 인라인 → 파일 하나만 열면 오프라인에서도 보임.
계절(추정 라벨)별로 묶고, 'asian face' 명시 쿼리에서 온 것은 테두리로 구분.

실행:
    & backend\\.venv\\Scripts\\python.exe scripts/build_pexels_contact_sheet.py
출력:
    data/pexels_contact_sheet.html
"""

from __future__ import annotations

import base64
import html
import json
from pathlib import Path

import requests

SRC = Path("data/pexels_personal_color_candidates.json")
OUT = Path("data/pexels_contact_sheet.html")
THUMB = "?auto=compress&cs=tinysrgb&fit=crop&w=240&h=240"
SEASON_ORDER = ["spring", "summer", "autumn", "winter"]
SEASON_COLOR = {"spring": "#e8a23d", "summer": "#5aa9d6", "autumn": "#b5651d", "winter": "#6c5ce7"}


def thumb_data_uri(original_url: str) -> str | None:
    try:
        resp = requests.get(original_url + THUMB, timeout=20)
        resp.raise_for_status()
        b64 = base64.b64encode(resp.content).decode("ascii")
        ctype = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
        return f"data:{ctype};base64,{b64}"
    except requests.RequestException:
        return None


def main() -> int:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    print(f"{len(data)}장 썸네일 다운로드 중...")

    by_season: dict[str, list[dict]] = {s: [] for s in SEASON_ORDER}
    ok, fail = 0, 0
    for i, img in enumerate(data, 1):
        uri = thumb_data_uri(img["original_url"])
        if uri is None:
            fail += 1
            continue
        img["_uri"] = uri
        by_season.setdefault(img["candidate_label"], []).append(img)
        ok += 1
        if i % 40 == 0:
            print(f"  {i}/{len(data)}")
    print(f"완료: {ok}장 임베드, {fail}장 실패")

    parts = [
        "<style>",
        "body{background:#14161a;color:#e6e6e6;font-family:system-ui,'Segoe UI',sans-serif;margin:0;padding:24px}",
        "h1{font-size:20px}h2{margin-top:36px;text-transform:capitalize}",
        ".note{color:#9aa0a6;font-size:13px;line-height:1.6;max-width:820px}",
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;margin-top:12px}",
        ".card{background:#1e2127;border-radius:8px;overflow:hidden;border:2px solid transparent}",
        ".card.asian{border-color:#39d353}",
        ".card img{width:100%;height:150px;object-fit:cover;display:block}",
        ".meta{padding:6px 8px;font-size:11px;color:#b8bcc2;line-height:1.35}",
        ".q{color:#e6e6e6}.tag{color:#39d353;font-weight:600}",
        "</style>",
        "<h1>Pexels 퍼스널컬러 후보 — 육안 검수</h1>",
        "<p class='note'>계절 = <b>검색어 기반 추정 라벨</b>(candidate_label). "
        "초록 테두리 = 'asian face' 명시 쿼리에서 온 것(전체의 19%). "
        "흑백·노인·아이·가려진 얼굴·눈만 클로즈업·비아시아인이 섞여 있는지, "
        "그리고 라벨(계절)이 실제 얼굴 톤과 무관하게 조명/검색어로 붙었는지 직접 확인하세요.</p>",
    ]
    for season in SEASON_ORDER:
        cards = by_season.get(season, [])
        parts.append(f"<h2 style='color:{SEASON_COLOR[season]}'>{season} · {len(cards)}장</h2>")
        parts.append("<div class='grid'>")
        for img in cards:
            is_asian = img["query"].startswith("asian face")
            cls = "card asian" if is_asian else "card"
            q = html.escape(img["query"])
            who = html.escape(str(img.get("photographer", "")))
            tag = "<span class='tag'>[asian]</span> " if is_asian else ""
            parts.append(
                f"<a class='{cls}' href='{html.escape(img['page_url'])}' target='_blank' style='text-decoration:none'>"
                f"<img loading='lazy' src='{img['_uri']}'>"
                f"<div class='meta'>{tag}<span class='q'>{q}</span><br>{who}</div></a>"
            )
        parts.append("</div>")

    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"저장: {OUT.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

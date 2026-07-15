"""Cool-season (summer/winter) focused review set from a weak-label manifest.

The weak-labeler's model & color votes are warm/winter-biased, so cool consensus is
scarce (the real labeling bottleneck). The balanced `rule` vote (warmth-median split)
is the least-biased warm/cool signal, so faces the rule calls COOL are the candidate
pool an expert should confirm. Cards are ranked by `cool_votes` (how many of the 3
methods say cool) so the strongest cool candidates come first; summer(light-cool) and
winter(deep-cool) are split so the expert judges depth.

No inference — reads the existing weaklabels CSV.

Run (from BeautyAI_project):
    backend/.venv/Scripts/python.exe scripts/build_cool_review_sheet.py --tag fairface_asian
Outputs:
    data/manifests/<tag>_cool_review.csv      (+ empty expert_season column to fill)
    data/<tag>_cool_review_contact_sheet.html
"""
from __future__ import annotations

import argparse
import base64
import csv
import html
from collections import Counter
from pathlib import Path

COOL = {"summer", "winter"}
SEASON_COLOR = {"summer": "#5aa9d6", "winter": "#6c5ce7"}


def data_uri(path: Path) -> str | None:
    try:
        return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="fairface_asian")
    args = ap.parse_args()

    src = Path(f"data/manifests/{args.tag}_weaklabels.csv")
    rows = list(csv.DictReader(src.open(encoding="utf-8")))

    # If the manifest carries a quality gate, only review faces that pass it
    # (color-based cool/warm reads are invalid on cast/blurred/occluded photos).
    gated = [r for r in rows if r.get("quality_ok") == "1"]
    if gated:
        print(f"quality gate present: reviewing {len(gated)}/{len(rows)} gated faces only")
        rows = gated

    pool = []
    for r in rows:
        if r["rule_season"] not in COOL:
            continue
        cool_votes = sum(1 for k in ("model_season", "color_season", "rule_season") if r[k] in COOL)
        r["cool_votes"] = cool_votes
        pool.append(r)
    # strongest cool first, then coolest by warmth
    pool.sort(key=lambda r: (-r["cool_votes"], float(r["warmth"])))

    out_csv = Path(f"data/manifests/{args.tag}_cool_review.csv")
    fields = ["image_path", "expert_season", "rule_season", "cool_votes",
              "model_season", "color_season", "warmth", "brightness", "chroma",
              "lab_b", "margin", "race", "gender", "age"]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in pool:
            w.writerow({"expert_season": "", **r})

    _sheet(pool, args.tag)

    strong = sum(1 for r in pool if r["cool_votes"] >= 2)
    by_rule = Counter(r["rule_season"] for r in pool)
    print(f"cool-candidate pool: {len(pool)}  (rule summer={by_rule['summer']} winter={by_rule['winter']})")
    print(f"  cool_votes>=2 (strong cool): {strong}  |  cool_votes==3: {sum(1 for r in pool if r['cool_votes']==3)}")
    print(f"manifest -> {out_csv}")
    return 0


def _sheet(pool: list[dict], tag: str) -> None:
    parts = [
        "<style>",
        "body{background:#14161a;color:#e6e6e6;font-family:system-ui,'Segoe UI',sans-serif;margin:0;padding:24px}",
        "h1{font-size:20px}h2{margin-top:28px}",
        ".note{color:#9aa0a6;font-size:13px;line-height:1.6;max-width:900px}",
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(132px,1fr));gap:10px;margin-top:12px}",
        ".card{background:#1e2127;border-radius:8px;overflow:hidden}",
        ".card img{width:100%;height:132px;object-fit:cover;display:block}",
        ".meta{padding:5px 7px;font-size:11px;color:#d0d3d8;line-height:1.4}",
        ".s3{outline:2px solid #3fbf6f}.s2{outline:2px solid #b7c23f}",
        ".v{color:#8a93a0}",
        "</style>",
        "<h1>쿨 계절 집중 검수 (여름/겨울 병목)</h1>",
        "<p class='note'>자동 약라벨은 웜만 잘 잡음 → 쿨은 여기서 전문가가 확정. 풀 = <b>rule(균형)이 쿨로 본 얼굴</b>. "
        "테두리 초록=3표 모두 쿨, 노랑=2표 쿨(강한 쿨 후보). <b>summer=밝은 쿨 / winter=어두운·선명한 쿨</b>로 뎁스 판단. "
        "각 카드 <span class='v'>m</span>모델 <span class='v'>c</span>색 <span class='v'>r</span>규칙 투표 + w=warmth b=brightness. "
        "라벨은 <code>_cool_review.csv</code>의 <b>expert_season</b> 칸에 봄/여름/가을/겨울(또는 spring/summer/autumn/winter)로 채우세요.</p>",
    ]
    for season in ("summer", "winter"):
        cards = [r for r in pool if r["rule_season"] == season]
        s3 = sum(1 for r in cards if r["cool_votes"] == 3)
        s2 = sum(1 for r in cards if r["cool_votes"] == 2)
        label = "여름(밝은 쿨)" if season == "summer" else "겨울(어두운·선명한 쿨)"
        parts.append(f"<h2 style='color:{SEASON_COLOR[season]}'>{label} · {len(cards)}장 · 3표쿨 {s3} · 2표쿨 {s2}</h2>")
        parts.append("<div class='grid'>")
        for r in cards:
            uri = data_uri(Path(r["image_path"]))
            if not uri:
                continue
            cls = "card s3" if r["cool_votes"] == 3 else ("card s2" if r["cool_votes"] == 2 else "card")
            m, c, rr = (html.escape(str(r[k])[:3]) for k in ("model_season", "color_season", "rule_season"))
            parts.append(
                f"<div class='{cls}'><img loading='lazy' src='{uri}'>"
                f"<div class='meta'><span class='v'>m</span>{m} <span class='v'>c</span>{c} "
                f"<span class='v'>r</span>{rr}<br>w{float(r['warmth']):.2f} b{float(r['brightness']):.2f}</div></div>"
            )
        parts.append("</div>")
    out = Path(f"data/{tag}_cool_review_contact_sheet.html")
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"contact sheet -> {out.resolve()}")


if __name__ == "__main__":
    raise SystemExit(main())

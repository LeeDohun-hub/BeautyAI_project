"""Prepare the quality-gated faces for EXPERT personal-color labeling.

Takes only quality_ok==1 faces from a weaklabels manifest and lays them out as a
comparison-friendly labeling task: sorted into 4 warmth bands (warm -> relatively
cool), and within each band by brightness (light -> deep). Personal color is a
comparative judgment, so the gradient helps an expert place season boundaries.

The biased model/color votes are intentionally NOT shown as a prominent hint (to
avoid anchoring); only the WB-corrected warmth/brightness are shown as aids. The
expert fills `expert_season` in the CSV, keyed by the `idx` printed on each card.

Run (from BeautyAI_project):
    backend/.venv/Scripts/python.exe scripts/build_expert_labeling_set.py --tag fairface_asian
Outputs:
    data/manifests/<tag>_expert_labeling.csv     (idx, image_path, expert_season[blank], aids...)
    data/<tag>_expert_labeling.html              (numbered contact sheet, warmth bands)
"""
from __future__ import annotations

import argparse
import base64
import csv
from pathlib import Path

BAND_LABELS = [
    ("warm", "가장 웜 (봄/가을 후보)", "#e8a23d"),
    ("warm_neutral", "웜-중립", "#c98b4a"),
    ("neutral", "중립", "#9aa0a6"),
    ("rel_cool", "상대적 쿨 (여름/겨울 후보)", "#5aa9d6"),
]


def data_uri(path: Path) -> str | None:
    try:
        return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="fairface_asian")
    args = ap.parse_args()

    rows = list(csv.DictReader(Path(f"data/manifests/{args.tag}_weaklabels.csv").open(encoding="utf-8")))
    gated = [r for r in rows if r.get("quality_ok") == "1"]
    if not gated:
        raise SystemExit("no quality_ok==1 faces; run weak_label_personal_color.py with the gate first")

    # Sort by warmth desc (warm -> relatively cool); split into 4 equal warmth bands.
    gated.sort(key=lambda r: -float(r["warmth"]))
    n = len(gated)
    for i, r in enumerate(gated):
        band = min(3, i * 4 // n)
        r["_band"] = BAND_LABELS[band][0]
    # within band, brightness desc (light -> deep)
    order = []
    for band_key, _, _ in BAND_LABELS:
        order.extend(sorted((r for r in gated if r["_band"] == band_key),
                            key=lambda r: -float(r["brightness"])))
    for idx, r in enumerate(order, 1):
        r["_idx"] = idx

    # Expert manifest.
    out_csv = Path(f"data/manifests/{args.tag}_expert_labeling.csv")
    fields = ["idx", "image_path", "expert_season", "band", "warmth", "brightness",
              "lab_b", "hint_weak", "race", "gender", "age"]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in order:
            w.writerow({
                "idx": r["_idx"], "image_path": r["image_path"], "expert_season": "",
                "band": r["_band"], "warmth": r["warmth"], "brightness": r["brightness"],
                "lab_b": r["lab_b"], "hint_weak": r.get("consensus_season", ""),
                "race": r.get("race", ""), "gender": r.get("gender", ""), "age": r.get("age", ""),
            })

    _sheet(order, args.tag, n)
    print(f"expert labeling set: {n} gated faces -> {out_csv}")
    print(f"  fill 'expert_season' (spring/summer/autumn/winter or 봄/여름/가을/겨울) keyed by idx")
    return 0


def _sheet(order: list[dict], tag: str, n: int) -> None:
    parts = [
        "<style>",
        "body{background:#14161a;color:#e6e6e6;font-family:system-ui,'Segoe UI',sans-serif;margin:0;padding:24px}",
        "h1{font-size:20px}h2{margin-top:26px}",
        ".note{color:#9aa0a6;font-size:13px;line-height:1.6;max-width:920px}",
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:10px;margin-top:12px}",
        ".card{background:#1e2127;border-radius:8px;overflow:hidden;position:relative}",
        ".card img{width:100%;height:120px;object-fit:cover;display:block}",
        ".idx{position:absolute;top:3px;left:4px;background:rgba(0,0,0,.6);color:#fff;font-size:12px;"
        "font-weight:700;padding:1px 5px;border-radius:4px}",
        ".meta{padding:4px 6px;font-size:10px;color:#c0c4c9}",
        "</style>",
        "<h1>퍼스널컬러 전문가 라벨링 — FairFace 아시아 clean 484장</h1>",
        "<p class='note'>품질게이트(정면·자연광·미가림) 통과분만. <b>warmth 그라디언트로 웜→상대쿨 4밴드</b>, 밴드 내 <b>밝기순(라이트→딥)</b>으로 배열했습니다. "
        "퍼스널컬러는 비교판단이라 밴드 경계 근처를 유심히 보세요. <b>주의: 밴드는 시작 가설일 뿐</b> — 아시아는 대부분 웜-중립이고 절대 쿨은 드무니, "
        "얼굴(피부·머리·눈·대비)을 직접 보고 판정하세요. 각 카드 좌상단 <b>번호(idx)</b> = CSV 행. "
        "<code>_expert_labeling.csv</code>의 <b>expert_season</b>에 봄/여름/가을/겨울 기입. 애매하면 비워두거나 '?'.</p>",
    ]
    band_name = {k: (nm, col) for k, nm, col in BAND_LABELS}
    seen = set()
    for band_key, nm, col in BAND_LABELS:
        cards = [r for r in order if r["_band"] == band_key]
        if not cards:
            continue
        parts.append(f"<h2 style='color:{col}'>{nm} · {len(cards)}장</h2>")
        parts.append("<div class='grid'>")
        for r in cards:
            uri = data_uri(Path(r["image_path"]))
            if not uri:
                continue
            parts.append(
                f"<div class='card'><span class='idx'>{r['_idx']}</span>"
                f"<img loading='lazy' src='{uri}'>"
                f"<div class='meta'>w{float(r['warmth']):.2f} b{float(r['brightness']):.2f} · "
                f"{r.get('gender','')[:1]}{r.get('age','')}</div></div>"
            )
        parts.append("</div>")
    out = Path(f"data/{tag}_expert_labeling.html")
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"contact sheet -> {out.resolve()}")


if __name__ == "__main__":
    raise SystemExit(main())

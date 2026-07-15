"""Weak personal-color labels for an unlabeled face set (bootstrap for human review).

Reads a manifest with an `image_path` column (e.g. fairface_asian_raw_manifest.csv),
runs the production analyzer, and for each face emits THREE independent votes:
  - model_season : EfficientNet argmax (winter-biased, per eval)
  - color_season : Lab/HSV heuristic argmax (warm/spring-biased, per eval)
  - rule_season  : balanced 2x2 from warmth(warm/cool) x brightness(light/deep),
                   split at the SET's own medians so it is not base-rate degenerate.
`consensus_season` = majority of the three (>=2). Rows without a majority, or with a
low model margin, are flagged needs_review=1.

Because model & color are oppositely biased and rule is balanced-by-construction, the
3-way agreement is a useful weak signal: agree_count==3 rows are strong auto-seed
candidates; the rest go to an expert. Nothing here is a final label — it feeds review.

Run (from BeautyAI_project):
    backend/.venv/Scripts/python.exe scripts/weak_label_personal_color.py \
        --manifest data/manifests/fairface_asian_raw_manifest.csv --tag fairface_asian
Outputs:
    data/manifests/<tag>_weaklabels.csv
    data/<tag>_weaklabel_contact_sheet.html   (grouped by consensus, votes shown)
"""
from __future__ import annotations

import argparse
import base64
import csv
import html
import os
import statistics
import sys
from collections import Counter, defaultdict
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

from app.ai.personal_color_model import EfficientNetSeasonClassifier  # noqa: E402
from app.services import personal_color_analyzer as analyzer_module  # noqa: E402
from app.services.personal_color_analyzer import PersonalColorAnalyzer  # noqa: E402

SEASONS = ("spring", "summer", "autumn", "winter")
SEASON_COLOR = {"spring": "#e8a23d", "summer": "#5aa9d6", "autumn": "#b5651d", "winter": "#6c5ce7"}


def argmax_season(probs: dict | None) -> str | None:
    if not probs:
        return None
    return max(probs, key=probs.get)


def rule_season(warm: bool, light: bool) -> str:
    if warm:
        return "spring" if light else "autumn"
    return "summer" if light else "winter"


def image_quality(raw: bytes) -> tuple[float, float]:
    """(sharpness = Laplacian variance, cast = max relative channel imbalance)."""
    im = Image.open(BytesIO(raw)).convert("RGB")
    rgb = np.asarray(im, dtype=float)
    g = rgb.mean(axis=2)
    lap = 4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    means = rgb.reshape(-1, 3).mean(0)
    m = float(means.mean())
    cast = float(np.abs(means - m).max() / (m + 1e-6))
    return float(lap.var()), cast


def data_uri(path: Path) -> str | None:
    try:
        return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--tag", default="weaklabel")
    ap.add_argument("--model-path", default="", help="Candidate .pt (default: app settings model).")
    ap.add_argument("--margin-review", type=float, default=0.08,
                    help="Flag needs_review when model season_margin < this.")
    # Quality gate (color-based PC labels are only valid on frontal, neutral-lit faces).
    ap.add_argument("--gate-require-wb", type=int, default=1,
                    help="Require sclera white-balance success (eyes-open/frontal/correctable light).")
    ap.add_argument("--gate-min-landmarks", type=float, default=8.0)
    ap.add_argument("--gate-cast-max", type=float, default=0.30,
                    help="Reject strong ambient color cast (corrupts lab_b undertone).")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if args.model_path:
        mp = Path(args.model_path)
        mp = mp if mp.is_absolute() else ROOT / mp
        if not mp.exists():
            raise SystemExit(f"model not found: {mp}")
        analyzer_module._season_classifier = EfficientNetSeasonClassifier(str(mp))

    manifest = Path(args.manifest)
    with manifest.open(encoding="utf-8-sig", newline="") as f:
        src = list(csv.DictReader(f))
    if args.limit:
        src = src[: args.limit]

    analyzer = PersonalColorAnalyzer()

    # Pass 1: extract raw signals.
    recs = []
    for i, row in enumerate(src, 1):
        ip = Path(row["image_path"])
        if not ip.is_absolute():
            ip = ROOT / ip
        if not ip.exists():
            continue
        raw = ip.read_bytes()
        try:
            r = analyzer._read_one(raw, 1.0)
            sharp, cast = image_quality(raw)
        except Exception:
            continue
        cv = r.get("color_vector") or {}
        recs.append({
            "image_path": ip,
            "meta": row,
            "model_season": argmax_season(r.get("model_season_probs")),
            "color_season": argmax_season(r.get("color_season_probs")),
            "warmth": float(r.get("warmth", 0.0)),
            "brightness": float(r.get("brightness", 0.0)),
            "chroma": float(r.get("chroma", 0.0)),
            "lab_b": float(cv.get("lab_b", 0.0)),
            "model_top1": max((r.get("model_season_probs") or {"x": 0.0}).values()),
            "margin": _margin(r.get("model_season_probs")),
            # quality-gate signals
            "white_balanced": int(bool(r.get("white_balanced"))),
            "landmarks": float(r.get("landmark_skin_samples", 0.0)),
            "skin_quality": float(cv.get("quality", 0.0)),
            "sharpness": round(sharp, 1),
            "cast": round(cast, 3),
        })
        if i % 50 == 0:
            print(f"  ...{i}/{len(src)}", flush=True)

    if not recs:
        raise SystemExit("no readable images")

    # Set-median thresholds -> balanced 2x2 rule labels (avoids base-rate degeneracy).
    warm_thr = statistics.median(x["warmth"] for x in recs)
    bright_thr = statistics.median(x["brightness"] for x in recs)
    print(f"medians: warmth={warm_thr:.4f} brightness={bright_thr:.4f}  (rule split points)")

    for x in recs:
        x["rule_season"] = rule_season(x["warmth"] >= warm_thr, x["brightness"] >= bright_thr)
        votes = [x["model_season"], x["color_season"], x["rule_season"]]
        tally = Counter(v for v in votes if v)
        top, n = tally.most_common(1)[0]
        x["agree_count"] = n
        x["consensus_season"] = top if n >= 2 else ""
        # Quality gate: color-based labels only trustworthy on frontal, neutral-lit faces.
        gate_reasons = []
        if args.gate_require_wb and not x["white_balanced"]:
            gate_reasons.append("no-wb")
        if x["landmarks"] < args.gate_min_landmarks:
            gate_reasons.append("few-landmarks")
        if x["cast"] > args.gate_cast_max:
            gate_reasons.append("color-cast")
        x["quality_ok"] = int(not gate_reasons)
        x["gate_fail"] = ",".join(gate_reasons)
        x["needs_review"] = int(
            n < 2 or x["margin"] < args.margin_review or not x["consensus_season"] or not x["quality_ok"]
        )

    # Write weak-label manifest.
    out_manifest = Path(f"data/manifests/{args.tag}_weaklabels.csv")
    fields = [
        "image_path", "season", "consensus_season", "agree_count", "needs_review",
        "quality_ok", "gate_fail",
        "model_season", "color_season", "rule_season",
        "warmth", "brightness", "chroma", "lab_b", "model_top1", "margin",
        "white_balanced", "landmarks", "skin_quality", "sharpness", "cast",
        "race", "gender", "age", "partition",
    ]
    with out_manifest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for x in recs:
            m = x["meta"]
            # A weak label is only assigned when it passes the quality gate.
            weak = x["consensus_season"] if x["quality_ok"] else ""
            w.writerow({
                "image_path": x["image_path"].as_posix(),
                "season": weak,  # gated weak label (blank if no majority or gate-failed)
                "consensus_season": x["consensus_season"],
                "agree_count": x["agree_count"],
                "needs_review": x["needs_review"],
                "quality_ok": x["quality_ok"], "gate_fail": x["gate_fail"],
                "model_season": x["model_season"], "color_season": x["color_season"],
                "rule_season": x["rule_season"],
                "warmth": round(x["warmth"], 4), "brightness": round(x["brightness"], 4),
                "chroma": round(x["chroma"], 4), "lab_b": round(x["lab_b"], 3),
                "model_top1": round(x["model_top1"], 4), "margin": round(x["margin"], 4),
                "white_balanced": x["white_balanced"], "landmarks": round(x["landmarks"]),
                "skin_quality": round(x["skin_quality"], 3),
                "sharpness": x["sharpness"], "cast": x["cast"],
                "race": m.get("race", ""), "gender": m.get("gender", ""), "age": m.get("age", ""),
                "partition": "weak" if (x["quality_ok"] and not x["needs_review"]) else "review",
            })

    _write_contact_sheet(recs, args.tag)

    # Summary.
    cons = Counter(x["consensus_season"] or "REVIEW" for x in recs)
    strong = sum(1 for x in recs if x["agree_count"] == 3)
    gated = [x for x in recs if x["quality_ok"]]
    gate_fail = Counter(fr for x in recs if not x["quality_ok"] for fr in (x["gate_fail"].split(",")))
    gated_cons = Counter(x["consensus_season"] or "REVIEW" for x in gated)
    print(f"\nlabeled {len(recs)} faces -> {out_manifest}")
    print(f"  consensus dist (all): {dict(cons)}")
    print(f"  3-way agreement (strong seed): {strong}  |  needs_review: {sum(x['needs_review'] for x in recs)}")
    print(f"\n  QUALITY GATE: {len(gated)}/{len(recs)} pass ({len(gated)*100//max(1,len(recs))}%). "
          f"fail reasons: {dict(gate_fail)}")
    print(f"  gated consensus dist: {dict(gated_cons)}")
    print(f"  gated 3-way strong seeds: {sum(1 for x in gated if x['agree_count']==3)}")
    return 0


def _margin(probs: dict | None) -> float:
    if not probs:
        return 0.0
    vals = sorted(probs.values(), reverse=True)
    return float(vals[0] - (vals[1] if len(vals) > 1 else 0.0))


def _write_contact_sheet(recs: list[dict], tag: str) -> None:
    groups: dict[str, list[dict]] = defaultdict(list)
    for x in recs:
        groups[x["consensus_season"] or "REVIEW"].append(x)
    parts = [
        "<style>",
        "body{background:#14161a;color:#e6e6e6;font-family:system-ui,'Segoe UI',sans-serif;margin:0;padding:24px}",
        "h1{font-size:20px}h2{margin-top:28px;text-transform:capitalize}",
        ".note{color:#9aa0a6;font-size:13px;line-height:1.6;max-width:900px}",
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(132px,1fr));gap:10px;margin-top:12px}",
        ".card{background:#1e2127;border-radius:8px;overflow:hidden}",
        ".card img{width:100%;height:132px;object-fit:cover;display:block}",
        ".meta{padding:5px 7px;font-size:11px;color:#d0d3d8;line-height:1.4}",
        ".strong{outline:2px solid #3fbf6f}",
        ".v{color:#8a93a0}",
        "</style>",
        "<h1>FairFace 아시아 얼굴 — 퍼스널컬러 약라벨 검수</h1>",
        "<p class='note'>3표 투표: <b>m</b>=모델(winter편향) · <b>c</b>=색휴리스틱(warm편향) · "
        "<b>r</b>=규칙 2×2(warmth×brightness, 셋 중앙값 분할=균형). consensus=2표 이상 다수결. "
        "초록 테두리=<b>3표 만장일치</b>(강한 시드 후보). 'REVIEW' 그룹과 각 계절 내 애매한 것은 "
        "전문가 확정 필요. 규칙 라벨은 균형이라 base-rate 붕괴는 없지만, warmth/brightness가 "
        "조명에 흔들리니 육안 확인 필수.</p>",
    ]
    order = list(SEASONS) + ["REVIEW"]
    for g in order:
        cards = groups.get(g, [])
        if not cards:
            continue
        color = SEASON_COLOR.get(g, "#9aa0a6")
        strong = sum(1 for x in cards if x["agree_count"] == 3)
        parts.append(f"<h2 style='color:{color}'>{g} · {len(cards)}장 · 만장일치 {strong}</h2>")
        parts.append("<div class='grid'>")
        for x in sorted(cards, key=lambda z: (-z["agree_count"], z["needs_review"])):
            uri = data_uri(x["image_path"])
            if not uri:
                continue
            cls = "card strong" if x["agree_count"] == 3 else "card"
            m = html.escape(str(x["model_season"])[:3])
            c = html.escape(str(x["color_season"])[:3])
            rr = html.escape(str(x["rule_season"])[:3])
            parts.append(
                f"<div class='{cls}'><img loading='lazy' src='{uri}'>"
                f"<div class='meta'><span class='v'>m</span>{m} "
                f"<span class='v'>c</span>{c} <span class='v'>r</span>{rr}<br>"
                f"w{x['warmth']:.2f} b{x['brightness']:.2f}</div></div>"
            )
        parts.append("</div>")
    out = Path(f"data/{tag}_weaklabel_contact_sheet.html")
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"contact sheet -> {out.resolve()}")


if __name__ == "__main__":
    raise SystemExit(main())

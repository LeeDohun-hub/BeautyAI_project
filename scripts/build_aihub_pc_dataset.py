"""AI-Hub 글로벌 다인종 피부색 데이터 → 퍼스널컬러 학습셋.

이 데이터의 고유한 구조:
  같은 인물을 **2x2 조명**({500, 5000} lux x {3200, 5600} K)으로 4장씩 찍고,
  피부색은 사진이 아니라 **분광측색기(CM26d)로 따로 측정**해 뒀다.
  → "조명 아래 사진" → "조명과 무관한 참 피부색" 쌍이 인물당 4개.

그래서 사진에서 계절을 바로 맞히지 않는다(사진의 피부색은 조명이 지배한다 —
동일인 4장이 육안으로 4계절처럼 보인다). 대신 2단으로 간다:
  1) 사진 → 참 Lab 회귀 (정답이 기계 실측이라 ΔE 로 객관 검증됨,
     같은 인물의 4조명이 같은 정답이므로 조명 불변성이 학습으로 강제된다)
  2) 참 Lab → 계절 규칙 (아래 season_from_lab)

계절 규칙: 퍼스널컬러의 웜/쿨은 "깊이를 보정한 뒤의 언더톤"이다. 어두운 피부일수록
b* 가 자연히 커지므로 b* 를 ITA 로 회귀한 **잔차 부호**를 웜/쿨로 쓴다(밝기 교란 제거).
깊이는 ITA 중앙값으로 가른다. 동북아 726명 기준 봄25.9/여름24.1/가을26.4/겨울23.6% 로 균형.

Usage:
  python scripts/build_aihub_pc_dataset.py --region 동북아시아 --max-side 512
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import median

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "manifests" / "aihub_skincolor_full_manifest.csv"
AIHUB = ROOT / "data" / "01.글로벌 다인종 피부색 데이터" / "3.개방데이터" / "1.데이터"
OUT_IMG = ROOT / "data" / "datasets" / "aihub_pc"
OUT_MF = ROOT / "data" / "manifests" / "aihub_pc_manifest.csv"

SEASONS = ["spring", "summer", "autumn", "winter"]


def parse_lighting(image_name: str) -> tuple[int, int] | None:
    """파일명이 조명을 인코딩한다: _5L32K = 500lux/3200K, _5KL56K = 5000lux/5600K."""
    m = re.search(r"_(5K?L)(32|56)K\.jpg$", image_name)
    if not m:
        return None
    lux = 5000 if m.group(1) == "5KL" else 500
    return lux, int(m.group(2)) * 100


def fit_undertone_line(people: list[dict]) -> tuple[float, float]:
    """b* 를 ITA 로 단순회귀 → (기울기, 절편). 잔차가 '깊이 보정된 언더톤'."""
    xs = [float(p["ita_avg"]) for p in people]
    ys = [float(p["lab_b"]) for p in people]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    slope = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / denom
    return slope, my - slope * mx


def season_from_lab(ita: float, lab_b: float, slope: float, inter: float, ita_median: float) -> str:
    warm = lab_b - (slope * ita + inter) > 0   # 깊이 보정 후에도 노란기가 남으면 웜
    light = ita > ita_median                   # ITA 클수록 밝은 피부
    if warm:
        return "spring" if light else "autumn"
    return "summer" if light else "winter"


def zip_index(region: str) -> dict[str, Path]:
    """image_name → 그 이미지가 든 TS zip 경로."""
    index: dict[str, Path] = {}
    for split in ("Training", "Validation"):
        src = AIHUB / split / "01.원천데이터"
        if not src.exists():
            continue
        for zp in src.glob("TS_*.zip"):
            if region not in zp.name:
                continue
            try:
                with zipfile.ZipFile(zp) as zf:
                    for name in zf.namelist():
                        if name.lower().endswith(".jpg"):
                            index[Path(name).name] = zp
            except zipfile.BadZipFile:
                print(f"  [손상 zip 건너뜀] {zp.name}")
    return index


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="동북아시아")
    ap.add_argument("--max-side", type=int, default=512)
    ap.add_argument("--limit", type=int, default=0, help="디버그용 인물 수 제한")
    args = ap.parse_args()

    rows = [r for r in csv.DictReader(MANIFEST.open(encoding="utf-8-sig"))
            if r["region"] == args.region and r.get("ita_avg") and r.get("lab_b")]
    people: dict[str, dict] = {}
    for r in rows:
        people.setdefault(r["uid"], r)
    plist = list(people.values())
    if args.limit:
        plist = plist[: args.limit]
        keep = {p["uid"] for p in plist}
        rows = [r for r in rows if r["uid"] in keep]
    print(f"{args.region}: {len(rows)}장 / 인물 {len(plist)}명")

    slope, inter = fit_undertone_line(plist)
    ita_med = median(float(p["ita_avg"]) for p in plist)
    print(f"언더톤 기준선 b* = {slope:.4f}·ITA + {inter:.2f}, 깊이 경계 ITA={ita_med:.2f}")

    uid_season = {
        p["uid"]: season_from_lab(float(p["ita_avg"]), float(p["lab_b"]), slope, inter, ita_med)
        for p in plist
    }
    dist = defaultdict(int)
    for s in uid_season.values():
        dist[s] += 1
    print("인물 기준 계절 분포:", dict(dist))

    print("zip 색인 작성 중...")
    zidx = zip_index(args.region)
    print(f"  zip 안 이미지 {len(zidx)}장")

    OUT_IMG.mkdir(parents=True, exist_ok=True)
    by_zip: dict[Path, list[dict]] = defaultdict(list)
    missing = 0
    for r in rows:
        zp = zidx.get(r["image_name"])
        if zp is None:
            missing += 1
            continue
        by_zip[zp].append(r)
    if missing:
        print(f"  [경고] zip 에서 못 찾은 이미지 {missing}장")

    out_rows: list[dict] = []
    for zp, items in by_zip.items():
        print(f"  추출 {zp.name} ({len(items)}장)")
        with zipfile.ZipFile(zp) as zf:
            inner = {Path(n).name: n for n in zf.namelist()}

            def work(r: dict) -> dict | None:
                lit = parse_lighting(r["image_name"])
                if lit is None:
                    return None
                try:
                    data = zf.read(inner[r["image_name"]])
                except Exception:
                    return None
                im = Image.open(io.BytesIO(data)).convert("RGB")
                # 원본이 90도 눕혀 저장돼 있다(4000x3000 가로). 세로로 돌린다.
                if im.width > im.height:
                    im = im.rotate(-90, expand=True)
                im.thumbnail((args.max_side, args.max_side))
                dst = OUT_IMG / r["image_name"]
                im.save(dst, quality=92)
                lux, kelvin = lit
                return {
                    "image_path": f"data/datasets/aihub_pc/{r['image_name']}",
                    "uid": r["uid"],
                    "lux": lux,
                    "kelvin": kelvin,
                    "lab_l": r["lab_l"],
                    "lab_a": r["lab_a"],
                    "lab_b": r["lab_b"],
                    "ita_avg": r["ita_avg"],
                    "season": uid_season[r["uid"]],
                    "gender": r.get("gender", ""),
                    "age": r.get("age", ""),
                }

            with ThreadPoolExecutor(max_workers=8) as pool:
                for res in pool.map(work, items):
                    if res:
                        out_rows.append(res)

    OUT_MF.parent.mkdir(parents=True, exist_ok=True)
    with OUT_MF.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print(f"\n완료: {len(out_rows)}장 → {OUT_MF}")
    print(f"이미지: {OUT_IMG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

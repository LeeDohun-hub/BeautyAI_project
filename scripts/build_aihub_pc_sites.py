"""aihub_pc_manifest.csv 에 **부위별 분광측색 실측 Lab** 을 붙인다(지도신호 3배).

왜:
  - 기존 매니페스트는 얼굴 3부위(이마/좌뺨/우뺨) **평균 Lab 하나**만 갖고 있어 회귀 타깃이 3차원이다.
    원본 라벨 JSON 에는 부위별로 따로 측정돼 있으므로 9차원(3부위 x Lab)으로 주면 지도신호가 3배가 된다.
  - **목(Neck)은 제외**한다. 촬영 시 검은 상의로 가려져 사진에 거의 안 나오는데 예측하라고 하면
    없는 정보를 지어내게 된다. 얼굴과 피부색도 다르다(실측 CH00223: 얼굴 L61.5 vs 목 L65.0).

  ⚠️ 기존 파이프라인의 불일치도 여기서 바로잡는다:
     매니페스트 `lab_*` = 얼굴 3부위 평균인데 `ita_avg` = **목 포함 4부위** 평균이었다.
     즉 계절 규칙이 서로 다른 두 측정을 섞어 쓰고 있었다. 여기서는 얼굴 3부위 평균으로
     ITA 를 직접 계산해(`ita_face`) 규칙 전체를 한 기준으로 통일한다.

Usage:
  python scripts/build_aihub_pc_sites.py
"""
from __future__ import annotations

import csv
import json
import math
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "manifests" / "aihub_pc_manifest.csv"
OUT = ROOT / "data" / "manifests" / "aihub_pc_sites_manifest.csv"
AIHUB = ROOT / "data" / "01.글로벌 다인종 피부색 데이터" / "3.개방데이터" / "1.데이터"

SITES = ["Forehead", "Left", "Right"]      # 목 제외 — 사진에 안 보인다


def parse_lab(value: str) -> list[float]:
    return [float(x) for x in value.split(",")]


def site_labs() -> dict[str, dict[str, list[float]]]:
    """uid → {부위: [L, a, b]}. TL zip 의 라벨 JSON 에서 읽는다."""
    out: dict[str, dict[str, list[float]]] = {}
    for split in ("Training", "Validation"):
        d = AIHUB / split / "02.라벨링데이터"
        if not d.exists():
            continue
        for zp in d.glob("TL_동북아시아*.zip"):
            try:
                zf = zipfile.ZipFile(zp)
            except zipfile.BadZipFile:
                print(f"  [손상 zip 건너뜀] {zp.name}")
                continue
            with zf:
                for name in zf.namelist():
                    if not name.endswith(".json"):
                        continue
                    uid = re.split(r"[_/]", Path(name).name)[0]
                    if uid in out:
                        continue          # 인물당 JSON 이 여러 개지만 Skin_info 는 동일
                    try:
                        skin = json.loads(zf.read(name))["Skin_info"]
                    except Exception:
                        continue
                    labs: dict[str, list[float]] = {}
                    for k, v in skin.items():
                        if "(Lab)" not in k:
                            continue
                        site = k.split()[0]
                        if site in SITES:
                            labs[site] = parse_lab(v)
                    if len(labs) == len(SITES):
                        out[uid] = labs
    return out


def main() -> int:
    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8")))
    labs = site_labs()
    print(f"라벨 JSON 에서 부위별 Lab 확보: {len(labs)}명")

    out_rows = []
    missing = 0
    for r in rows:
        s = labs.get(r["uid"])
        if not s:
            missing += 1
            continue
        face = [sum(s[k][i] for k in SITES) / len(SITES) for i in range(3)]
        ita_face = math.degrees(math.atan2(face[0] - 50.0, face[2]))
        row = dict(r)
        for site in SITES:
            for j, ch in enumerate("lab"):
                row[f"{site.lower()}_{ch}"] = round(s[site][j], 4)
        row["face_l"], row["face_a"], row["face_b"] = (round(x, 4) for x in face)
        row["ita_face"] = round(ita_face, 4)
        out_rows.append(row)
    if missing:
        print(f"  [경고] 라벨 못 찾은 이미지 {missing}장")

    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print(f"완료: {len(out_rows)}장 / 인물 {len({r['uid'] for r in out_rows})}명 → {OUT}")

    # 기존 ita_avg(목 포함 4부위)와 새 ita_face(얼굴 3부위)가 얼마나 다른지 — 규칙에 영향
    diffs = [abs(float(r["ita_avg"]) - float(r["ita_face"])) for r in out_rows]
    print(f"기존 ita_avg(목포함) vs 새 ita_face(얼굴만): 평균차 {sum(diffs)/len(diffs):.2f}도, 최대 {max(diffs):.2f}도")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

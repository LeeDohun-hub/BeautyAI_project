"""AI-Hub '글로벌 다인종 피부색 데이터' 라벨(JSON)에서 실측 Lab/ITA로 매니페스트를 만들고
퍼스널컬러 라벨을 '밝기 보정 언더톤'으로 유도한다.

핵심: 분광측색계 실측 Lab 은 조명 독립적 ground-truth 다. 단 b*(황-청)는 멜라닌/깊이가
깊을수록 함께 커져(=깊은 피부일수록 노래 보임) 언더톤과 깊이가 섞인다. 그래서 b* 를 깊이
지표(ITA)에 회귀시켜 남는 잔차(b_resid)를 '밝기(깊이) 보정 언더톤' 으로 쓴다.
  - b_resid > +thr  → warm
  - b_resid < -thr  → cool
  - 그 외          → neutral
깊이(depth)는 ITA 표준 구간으로 나눈다. season 은 (undertone × depth) 조합의 근사치.

이미지 압축해제 없이 라벨 zip 만 읽어 동작한다(라벨 유도용). image_name/zip 도 같이 남겨
후속 학습에서 원천 이미지와 매칭할 수 있게 한다.

Usage:
  python scripts/build_aihub_skincolor_manifest.py \
      --root "data/01.글로벌 다인종 피부색 데이터" \
      --out data/manifests/aihub_skincolor_full_manifest.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import zipfile
from pathlib import Path

import numpy as np

FITZ = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}
FACE_LAB_KEYS = (
    "Forehead Colorimeter Reading (Lab)",
    "Left Cheek Reading (Lab)",
    "Right Cheek Reading (Lab)",
)  # 목(Neck)은 얼굴 색과 달라 제외


def _parse_lab(s: str):
    try:
        parts = [float(x) for x in str(s).split(",")]
        if len(parts) == 3:
            return parts  # L, a, b
    except Exception:
        pass
    return None


def _face_lab(skin: dict):
    labs = [_parse_lab(skin.get(k, "")) for k in FACE_LAB_KEYS]
    labs = [x for x in labs if x is not None]
    if not labs:
        return None
    arr = np.array(labs, dtype=np.float64).mean(axis=0)
    return float(arr[0]), float(arr[1]), float(arr[2])


def _ita(skin: dict):
    try:
        return float(skin.get("ITA Avg.", ""))
    except Exception:
        return None


def depth_bin(ita: float) -> str:
    """ITA 표준 피부 깊이 구간 (Chardon)."""
    if ita >= 55:
        return "very_light"
    if ita >= 41:
        return "light"
    if ita >= 28:
        return "intermediate"
    if ita >= 10:
        return "tan"
    if ita >= -30:
        return "brown"
    return "dark"


def collect(root: Path):
    """모든 라벨 zip을 읽어 '인물' 레코드 리스트 반환.
    한 사람당 어노테이션 JSON이 여러 개(Q13_1, Q17_2 …)라 UID로 중복제거한다
    (실측 Lab/ITA 는 사람당 1값이라 첫 JSON만 취해도 동일)."""
    label_zips = sorted(root.rglob("*.zip"))
    label_zips = [z for z in label_zips if "라벨링데이터" in str(z)]
    recs = []
    seen_uid = set()
    for z in label_zips:
        partition = "train" if "Training" in str(z) else ("val" if "Validation" in str(z) else "other")
        try:
            zf = zipfile.ZipFile(z)
        except Exception as exc:  # noqa: BLE001
            print(f"[skip] {z.name}: {exc}", file=sys.stderr)
            continue
        with zf:
            for name in zf.namelist():
                if not name.lower().endswith(".json"):
                    continue
                try:
                    d = json.loads(zf.read(name).decode("utf-8"))
                except Exception:
                    continue
                skin = d.get("Skin_info", {})
                human = d.get("Human_info", {})
                shoot = d.get("Shoot_info", {})
                uid = str(human.get("UID", "")).strip()
                if uid and uid in seen_uid:
                    continue
                lab = _face_lab(skin)
                ita = _ita(skin)
                if lab is None or ita is None:
                    continue
                if uid:
                    seen_uid.add(uid)
                fitz = FITZ.get(str(skin.get("Fitzpatrick", "")).strip(), 0)
                images = [shoot.get(k) for k in shoot if "Image File Name" in k and shoot.get(k)]
                recs.append({
                    "partition": partition,
                    "region": str(human.get("Continent", "")).strip(),
                    "uid": str(human.get("UID", "")).strip(),
                    "gender": str(human.get("Gender", "")).strip(),
                    "age": str(human.get("Age", "")).strip(),
                    "country": str(human.get("Country of Birth", "")).strip(),
                    "fitzpatrick": fitz,
                    "ita_avg": round(ita, 3),
                    "lab_l": round(lab[0], 3),
                    "lab_a": round(lab[1], 3),
                    "lab_b": round(lab[2], 3),
                    "skin_tone": str(skin.get("Skin Tone", "")).strip(),
                    "images": images,
                    "zip": str(z.relative_to(root.parent.parent)) if root.parent.parent in z.parents else z.name,
                })
    return recs


def derive_labels(recs: list[dict]):
    """b*~ITA 회귀 잔차로 밝기 보정 언더톤 유도. 대륙 무관 전체 population 으로 회귀."""
    ita = np.array([r["ita_avg"] for r in recs], dtype=np.float64)
    b = np.array([r["lab_b"] for r in recs], dtype=np.float64)
    a = np.array([r["lab_a"] for r in recs], dtype=np.float64)
    # b* = m*ITA + c  (깊을수록 ITA 낮고 b* 큼 → 음의 기울기 예상)
    m, c = np.polyfit(ita, b, 1)
    b_pred = m * ita + c
    b_resid = b - b_pred
    thr = 0.75 * float(np.std(b_resid))  # ±0.75σ 를 warm/cool 경계로
    hue = np.degrees(np.arctan2(b, a))  # a*-b* 색상각(참고)
    for i, r in enumerate(recs):
        r["hue_ab"] = round(float(hue[i]), 2)
        r["b_resid"] = round(float(b_resid[i]), 3)
        if b_resid[i] >= thr:
            ut = "warm"
        elif b_resid[i] <= -thr:
            ut = "cool"
        else:
            ut = "neutral"
        r["undertone"] = ut
        r["depth"] = depth_bin(r["ita_avg"])
        light = r["ita_avg"] >= 41  # very_light/light = 밝음
        # season 근사: 밝음+웜=spring, 깊음+웜=autumn, 밝음+쿨=summer, 깊음+쿨=winter, neutral=제외
        if ut == "warm":
            r["season_derived"] = "spring" if light else "autumn"
        elif ut == "cool":
            r["season_derived"] = "summer" if light else "winter"
        else:
            r["season_derived"] = ""  # 뉴트럴은 단정 안 함(top-2 후보)
    return {"slope": round(float(m), 4), "intercept": round(float(c), 3),
            "resid_std": round(float(np.std(b_resid)), 3), "warm_cool_thr": round(thr, 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/01.글로벌 다인종 피부색 데이터")
    ap.add_argument("--out", default="data/manifests/aihub_skincolor_full_manifest.csv")
    args = ap.parse_args()

    project = Path(__file__).resolve().parents[1]
    root = (project / args.root).resolve()
    out = (project / args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"reading label zips under: {root}")
    recs = collect(root)
    print(f"persons with valid Lab/ITA: {len(recs)}")
    if not recs:
        return 1
    stats = derive_labels(recs)
    print("brightness-corrected undertone fit:", stats)

    # 인물 단위 요약
    from collections import Counter
    print("\n== 대륙 분포 ==")
    for k, n in Counter(r["region"] for r in recs).most_common():
        print(f"  {k}: {n}")
    print("\n== 유도 언더톤 분포 ==")
    for k, n in Counter(r["undertone"] for r in recs).most_common():
        print(f"  {k}: {n} ({n / len(recs) * 100:.1f}%)")
    print("\n== 유도 season 분포 (neutral 제외) ==")
    for k, n in Counter(r["season_derived"] for r in recs if r["season_derived"]).most_common():
        print(f"  {k}: {n}")
    print("\n== 동북아시아 언더톤 (한국시장 관심) ==")
    nea = [r for r in recs if r["region"] == "동북아시아"]
    for k, n in Counter(r["undertone"] for r in nea).most_common():
        print(f"  {k}: {n} ({n / max(1,len(nea)) * 100:.1f}%)")

    # 이미지 단위 매니페스트(1인 4장) 기록
    fields = ["partition", "region", "uid", "gender", "age", "country", "fitzpatrick",
              "ita_avg", "lab_l", "lab_a", "lab_b", "hue_ab", "b_resid",
              "undertone", "depth", "season_derived", "skin_tone", "image_name", "zip"]
    n_img = 0
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in recs:
            base = {k: r[k] for k in fields if k not in ("image_name",)}
            for img in (r["images"] or [""]):
                row = dict(base)
                row["image_name"] = img
                w.writerow(row)
                n_img += 1
    print(f"\nwrote {n_img} image rows ({len(recs)} persons) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

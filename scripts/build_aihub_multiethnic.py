"""AI-Hub **전 권역(다인종)** 퍼스널컬러 학습셋 구축 — zip 에서 바로 스트리밍(압축해제 불필요).

왜 필요한가:
  v4 실험(2026-07-21)에서 `a` 가중치 축소·결정변수 직접회귀 둘 다 실패했고, 로그가 원인을 말해줬다.
  **train loss 0.118→0.014(10배↓) 인데 val ΔE 는 2.65~2.94 에서 미동** = 용량이 아니라 **과적합**.
  동북아 646명은 너무 적다. 라벨(분광측색)은 6개 권역 전부에 있으므로 데이터를 3.5배로 늘린다.

조사 실측(zip 목록 스캔):
  동북아 646명/2,584장 · 동남아 610/2,440 · 기타 274/1,096 · 유럽 253/1,012 · 중동남아 149/160(손상zip)
  · 북미 79/316  → 합계 **2,257명 / 8,332장**(Train+Val). 파일명 규칙·라벨 포맷은 전 권역 동일.

원본 17.9GB 를 풀지 않고 zip 에서 읽어 256px 로 줄여 저장한다(≈90MB).

Usage:
  python scripts/build_aihub_multiethnic.py --max-side 256
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
AIHUB = ROOT / "data" / "01.글로벌 다인종 피부색 데이터" / "3.개방데이터" / "1.데이터"
OUT_IMG = ROOT / "data" / "datasets" / "aihub_pc_multi"
OUT_MANIFEST = ROOT / "data" / "manifests" / "aihub_pc_multi_manifest.csv"

SITES = ["Forehead", "Left", "Right"]          # 목 제외 — 검은 상의에 가려 사진에 없다
IMG_RE = re.compile(r"^(?P<uid>[A-Za-z]+\d+)_(?P<lux>5KL|5L)(?P<kel>32K|56K)\.jpg$", re.I)
REGION_RE = re.compile(r"^[TV][SL]_([^_]+)_")


def parse_lab(value: str) -> list[float]:
    return [float(x) for x in value.split(",")]


def region_of(zip_name: str) -> str:
    m = REGION_RE.match(zip_name)
    return m.group(1) if m else "?"


def site_labs() -> dict[str, dict]:
    """uid → {'labs': {부위:[L,a,b]}, 'region': 권역}. 전 권역 TL/VL zip 에서 읽는다."""
    out: dict[str, dict] = {}
    for split in ("Training", "Validation"):
        d = AIHUB / split / "02.라벨링데이터"
        if not d.exists():
            continue
        for zp in sorted(d.glob("*.zip")):
            region = region_of(zp.name)
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
                        continue                      # 인물당 JSON 여러 개지만 Skin_info 동일
                    try:
                        skin = json.loads(zf.read(name))["Skin_info"]
                    except Exception:
                        continue
                    labs = {}
                    for k, v in skin.items():
                        if "(Lab)" not in k:
                            continue
                        site = k.split()[0]
                        if site in SITES:
                            try:
                                labs[site] = parse_lab(v)
                            except ValueError:
                                pass
                    if len(labs) == len(SITES):
                        out[uid] = {"labs": labs, "region": region}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-side", type=int, default=256,
                    help="256=기본. 448 이면 피부 픽셀이 ~3배 → 색 회귀 신호 증가(대신 용량↑)")
    ap.add_argument("--face-crop", type=int, default=0,
                    help="1=mediapipe 로 얼굴만 타이트 크롭(배경·머리카락·옷 제거). 검출 실패 시 원본 유지")
    ap.add_argument("--out-dir", default="", help="기본 aihub_pc_multi. 예: aihub_pc_multi_face")
    ap.add_argument("--manifest-out", default="", help="기본 aihub_pc_multi_manifest.csv")
    ap.add_argument("--jobs", type=int, default=8)
    args = ap.parse_args()

    global OUT_IMG, OUT_MANIFEST
    if args.out_dir:
        OUT_IMG = ROOT / "data" / "datasets" / args.out_dir
    if args.manifest_out:
        OUT_MANIFEST = ROOT / "data" / "manifests" / args.manifest_out

    OUT_IMG.mkdir(parents=True, exist_ok=True)
    OUT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)

    labs = site_labs()
    by_region = defaultdict(int)
    for v in labs.values():
        by_region[v["region"]] += 1
    print(f"라벨 확보: {len(labs)}명  " + " ".join(f"{k}:{v}" for k, v in sorted(by_region.items())))

    # 이미지: 전 권역 TS/VS zip 에서 스트리밍 → 축소 저장
    tasks = []          # (zip_path, inner_name, uid, lux, kelvin)
    for split in ("Training", "Validation"):
        d = AIHUB / split / "01.원천데이터"
        if not d.exists():
            continue
        for zp in sorted(d.glob("*.zip")):
            try:
                zf = zipfile.ZipFile(zp)
            except zipfile.BadZipFile:
                print(f"  [손상 zip 건너뜀] {zp.name}")
                continue
            with zf:
                for name in zf.namelist():
                    m = IMG_RE.match(Path(name).name)
                    if not m:
                        continue
                    uid = m.group("uid")
                    if uid not in labs:               # 라벨 없는 인물은 학습에 못 쓴다
                        continue
                    tasks.append((zp, name, uid,
                                  5000 if m.group("lux").upper() == "5KL" else 500,
                                  3200 if m.group("kel").upper() == "32K" else 5600))
    print(f"라벨과 매칭된 이미지 {len(tasks)}장 → {args.max_side}px 축소 저장 중...", flush=True)

    # 얼굴 타이트 크롭 — 배경/머리카락/옷을 빼 피부 신호 비중을 높인다. 스레드마다 detector 를 따로 둔다.
    _local = __import__("threading").local()

    def face_box(im: Image.Image):
        if not args.face_crop:
            return None
        try:
            import mediapipe as mp
            import numpy as _np
        except ImportError:
            return None
        det = getattr(_local, "det", None)
        if det is None:
            # ⚠️ model_selection=0(근거리) 필수. 1(원거리)은 이 스튜디오 촬영본에서 0/5 검출 실패한다.
            det = mp.solutions.face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.5)
            _local.det = det
        # 원본이 4000x3000 이라 그대로 넣으면 느리다 → 축소본으로 검출하고 좌표는 비율로 되돌린다.
        small = im.copy()
        small.thumbnail((640, 640))
        res = det.process(_np.asarray(small))
        if not res.detections:
            return None
        W, H = im.size
        rb = res.detections[0].location_data.relative_bounding_box
        # 이마~턱이 들어가도록 여유를 준다(분광측색 부위: 이마·좌뺨·우뺨)
        mx, my = rb.width * 0.25, rb.height * 0.30
        x0 = max(0, int((rb.xmin - mx) * W)); y0 = max(0, int((rb.ymin - my) * H))
        x1 = min(W, int((rb.xmin + rb.width + mx) * W)); y1 = min(H, int((rb.ymin + rb.height + my) * H))
        return (x0, y0, x1, y1) if x1 - x0 > 32 and y1 - y0 > 32 else None

    def work(t):
        zp, inner, uid, lux, kel = t
        dst_name = f"{uid}_{'5KL' if lux == 5000 else '5L'}{'32K' if kel == 3200 else '56K'}.jpg"
        dst = OUT_IMG / dst_name
        if not dst.exists():
            try:
                with zipfile.ZipFile(zp) as zf:
                    im = Image.open(io.BytesIO(zf.read(inner))).convert("RGB")
            except Exception:
                return None
            box = face_box(im)
            if box:
                im = im.crop(box)
            im.thumbnail((args.max_side, args.max_side))
            im.save(dst, quality=92)
        return (dst_name, uid, lux, kel)

    done = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for i, r in enumerate(pool.map(work, tasks)):
            if r:
                done.append(r)
            if (i + 1) % 1000 == 0:
                print(f"  {i+1}/{len(tasks)}", flush=True)
    print(f"  저장 완료 {len(done)}장 (실패 {len(tasks)-len(done)})")

    # 매니페스트
    rows = []
    for dst_name, uid, lux, kel in sorted(done):
        info = labs[uid]
        s = info["labs"]
        face = [sum(s[k][i] for k in SITES) / len(SITES) for i in range(3)]
        # ⚠️ 경로는 반드시 실제 출력 폴더(OUT_IMG)를 따라가야 한다. 하드코딩하면 --out-dir 로
        #    폴더를 바꿨을 때 매니페스트가 옛 폴더를 가리켜 학습이 FileNotFoundError 로 죽는다.
        row = {
            "image_path": f"data/datasets/{OUT_IMG.name}/{dst_name}",
            "uid": uid, "region": info["region"], "lux": lux, "kelvin": kel,
        }
        for site in SITES:
            for j, ch in enumerate("lab"):
                row[f"{site.lower()}_{ch}"] = round(s[site][j], 4)
        row["face_l"], row["face_a"], row["face_b"] = (round(x, 4) for x in face)
        row["ita_face"] = round(math.degrees(math.atan2(face[0] - 50.0, face[2])), 4)
        rows.append(row)

    with OUT_MANIFEST.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    per = defaultdict(lambda: [0, set()])
    for r in rows:
        per[r["region"]][0] += 1
        per[r["region"]][1].add(r["uid"])
    print(f"\n완료: {len(rows)}장 / 인물 {len({r['uid'] for r in rows})}명 → {OUT_MANIFEST}")
    for reg, (n, uids) in sorted(per.items()):
        print(f"   {reg:<14} {len(uids):>5}명 {n:>6}장")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

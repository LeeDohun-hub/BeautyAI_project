# -*- coding: utf-8 -*-
"""범용 파인튜닝용 인물-분리(identity-disjoint) 결합 매니페스트 빌더.

train = 유럽(Deep Armocromia) train + 글로벌 셀럽 train 인물
val   = 글로벌 셀럽 val 인물 (체크포인트 선택)
test  = 글로벌 셀럽 test 인물 (누수0 홀드아웃) — 학습 매니페스트에 미포함, 별도 eval

인물은 글로벌 크롭 파일명(<name>_<idx>_<hash>_<hash>.jpg)의 <name>으로 식별.
경로는 forward-slash 상대경로로 정규화(RunPod 리눅스 호환).

출력:
    data/manifests/finetune_train_manifest.csv     (image_path,season,partition[train|validation])
    data/manifests/finetune_global_test_manifest.csv (image_path,season)  ← 홀드아웃 eval
"""
from __future__ import annotations
import csv, re, random
from collections import defaultdict, Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEASONS = ("spring", "summer", "autumn", "winter")
RNG = random.Random(42)
IDENT = re.compile(r"_\d{2}_")


def norm(p: str) -> str:
    return str(p).replace("\\", "/").strip()


def read_rows(path: Path):
    with (ROOT / path).open(encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f)


def identity(crop_path: str) -> str:
    return IDENT.split(Path(crop_path).name)[0]


def main() -> int:
    # --- 글로벌 크롭 → 인물별 그룹 ---
    by_ident: dict[str, list[tuple[str, str]]] = defaultdict(list)  # ident -> [(path, season)]
    ident_season: dict[str, str] = {}
    for r in read_rows(Path("data/manifests/global_face_crop_manifest.csv")):
        s = r["season"].strip().lower()
        if s not in SEASONS:
            continue
        ident = identity(r["image_path"])
        by_ident[ident].append((norm(r["image_path"]), s))
        ident_season[ident] = s

    # --- 인물 단위 계절층화 70/15/15 분할 ---
    idents_by_season = defaultdict(list)
    for ident, s in ident_season.items():
        idents_by_season[s].append(ident)
    split = {"train": [], "val": [], "test": []}
    for s in SEASONS:
        ids = idents_by_season[s][:]
        RNG.shuffle(ids)
        n = len(ids)
        ntr, nval = int(n * 0.70), int(n * 0.15)
        split["train"] += ids[:ntr]
        split["val"] += ids[ntr:ntr + nval]
        split["test"] += ids[ntr + nval:]

    ident_to_part = {i: p for p, ids in split.items() for i in ids}

    train_rows: list[tuple[str, str, str]] = []
    test_rows: list[tuple[str, str]] = []
    for ident, imgs in by_ident.items():
        part = ident_to_part[ident]
        for path, s in imgs:
            if part == "train":
                train_rows.append((path, s, "train"))
            elif part == "val":
                train_rows.append((path, s, "validation"))
            else:
                test_rows.append((path, s))

    # --- 유럽 train 추가(유럽 test 912는 홀드아웃으로 제외) ---
    euro_tr = 0
    for r in read_rows(Path("data/manifests/personal_color_manifest.csv")):
        s = (r.get("season") or "").strip().lower()
        if s not in SEASONS:
            continue
        if (r.get("partition") or "").strip().lower() != "train":
            continue
        train_rows.append((norm(r["image_path"]), s, "train"))
        euro_tr += 1

    # --- 저장 ---
    out_tr = ROOT / "data/manifests/finetune_train_manifest.csv"
    with out_tr.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(["image_path", "season", "partition"]); w.writerows(train_rows)
    out_te = ROOT / "data/manifests/finetune_global_test_manifest.csv"
    with out_te.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(["image_path", "season"]); w.writerows(test_rows)

    # --- 요약 ---
    def cnt(rows, i): return dict(Counter(r[i] for r in rows))
    print(f"글로벌 인물: train {len(split['train'])} / val {len(split['val'])} / test {len(split['test'])}")
    tr_train = [r for r in train_rows if r[2] == "train"]
    tr_val = [r for r in train_rows if r[2] == "validation"]
    print(f"train 이미지: {len(tr_train)} (유럽 {euro_tr} + 글로벌 {len(tr_train)-euro_tr}), 계절 {cnt(tr_train,1)}")
    print(f"val   이미지: {len(tr_val)} (글로벌), 계절 {cnt(tr_val,1)}")
    print(f"test  이미지(홀드아웃): {len(test_rows)}, 계절 {cnt(test_rows,1)}")
    print(f"저장: {out_tr.name}, {out_te.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

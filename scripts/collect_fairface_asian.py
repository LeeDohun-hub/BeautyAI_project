"""Download FairFace (HF `HuggingFaceM4/FairFace`) and keep the East/Southeast-Asian
adult faces as a general-public base for personal-color self-labeling.

FairFace has no PC label — this only harvests faces. Weak PC labels are added by
`scripts/weak_label_personal_color.py` for human review.

FairFace race ids: 0=East Asian 1=Indian 2=Black 3=White 4=Middle Eastern
5=Latino_Hispanic 6=Southeast Asian.  gender: 0=Male 1=Female.
age ids: 0:0-2 1:3-9 2:10-19 3:20-29 4:30-39 5:40-49 6:50-59 7:60-69 8:70+.

Run (from BeautyAI_project):
    backend/.venv/Scripts/python.exe scripts/collect_fairface_asian.py --limit 600
Outputs:
    data/datasets/fairface_asian_raw/<race>/ff_<split>_<idx>.jpg
    data/manifests/fairface_asian_raw_manifest.csv   (image_path,race,gender,age,partition)
"""
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

import pandas as pd
from huggingface_hub import hf_hub_download

RACE_NAMES = {
    0: "east_asian", 1: "indian", 2: "black", 3: "white",
    4: "middle_eastern", 5: "latino_hispanic", 6: "southeast_asian",
}
GENDER = {0: "male", 1: "female"}
AGE = {0: "0-2", 1: "3-9", 2: "10-19", 3: "20-29", 4: "30-39",
       5: "40-49", 6: "50-59", 7: "60-69", 8: "70+"}
SPLIT_FILES = {
    "validation": ["0.25/validation-00000-of-00001-951dbd63c8724ee1.parquet"],
    "train": [
        "0.25/train-00000-of-00002-d405faba4f4b9b85.parquet",
        "0.25/train-00001-of-00002-dd3cb68164727418.parquet",
    ],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="validation", choices=list(SPLIT_FILES))
    ap.add_argument("--races", default="0,6", help="Comma race ids (default East+SE Asian).")
    ap.add_argument("--min-age-idx", type=int, default=3, help="Keep age idx >= this (3=20-29+).")
    ap.add_argument("--limit", type=int, default=600, help="Max images kept.")
    ap.add_argument("--balance-gender", action="store_true", help="Equal male/female.")
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--out-tag", default="fairface_asian")
    args = ap.parse_args()

    races = {int(x) for x in args.races.split(",") if x.strip() != ""}
    frames = []
    for fn in SPLIT_FILES[args.split]:
        print(f"downloading {fn} ...", flush=True)
        path = hf_hub_download("HuggingFaceM4/FairFace", fn, repo_type="dataset")
        frames.append(pd.read_parquet(path, engine="pyarrow"))
    df = pd.concat(frames, ignore_index=True)
    print(f"loaded {len(df)} rows; filtering race in {sorted(races)} age>={args.min_age_idx}")

    df = df[df["race"].isin(races) & (df["age"] >= args.min_age_idx)].reset_index(drop=True)
    idx = list(range(len(df)))
    random.Random(args.seed).shuffle(idx)

    if args.balance_gender:
        per = args.limit // 2
        picked, counts = [], {0: 0, 1: 0}
        for i in idx:
            g = int(df.iloc[i]["gender"])
            if counts[g] < per:
                picked.append(i)
                counts[g] += 1
            if len(picked) >= args.limit:
                break
        idx = picked
    else:
        idx = idx[: args.limit]

    raw_root = Path(f"data/datasets/{args.out_tag}_raw")
    manifest = Path(f"data/manifests/{args.out_tag}_raw_manifest.csv")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for n, i in enumerate(idx):
        r = df.iloc[i]
        race_id, gender_id, age_id = int(r["race"]), int(r["gender"]), int(r["age"])
        img = r["image"]
        data = img["bytes"] if isinstance(img, dict) else img
        race_name = RACE_NAMES[race_id]
        out_dir = raw_root / race_name
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"ff_{args.split}_{i:06d}.jpg"
        out_path.write_bytes(data)
        rows.append({
            "image_path": out_path.as_posix(),
            "race": race_name,
            "gender": GENDER[gender_id],
            "age": AGE[age_id],
            "partition": "unlabeled",
        })

    with manifest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["image_path", "race", "gender", "age", "partition"])
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    print(f"saved {len(rows)} faces -> {raw_root}")
    print("  race:", dict(Counter(x["race"] for x in rows)),
          "| gender:", dict(Counter(x["gender"] for x in rows)))
    print(f"manifest -> {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

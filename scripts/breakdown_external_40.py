"""Break down the 40-image external eval by subset (example28 vs kceleb12) and method."""
import csv
import os
import collections

SEASONS = ["spring", "summer", "autumn", "winter"]

# subset membership from manifest
subset = {}
with open("data/eval/external_40_manifest.csv", newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        subset[os.path.basename(r["image_path"])] = r["subset"]

preds = []
with open("data/eval/ft_external_40/predictions.csv", newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        r["_subset"] = subset.get(os.path.basename(r["image_path"]), "?")
        preds.append(r)


def report(rows, tag):
    n = len(rows)
    if not n:
        return
    def acc(col):
        return sum(int(r[col]) for r in rows) / n
    print(f"\n### {tag} (n={n}) ###")
    print(f"  model : acc={acc('model_correct'):.3f}  top2={acc('model_top2_correct'):.3f}  wc={acc('model_warmcool_correct'):.3f}")
    print(f"  color : acc={acc('color_correct'):.3f}  top2={acc('color_top2_correct'):.3f}  wc={acc('color_warmcool_correct'):.3f}")
    print(f"  blend : acc={acc('correct'):.3f}  top2={acc('top2_correct'):.3f}  wc={acc('warmcool_correct'):.3f}")
    # per-class model recall
    per = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        per[r["actual"]][1] += 1
        if int(r["model_correct"]):
            per[r["actual"]][0] += 1
    pc = {s: f"{per[s][0]}/{per[s][1]}" for s in SEASONS if per[s][1]}
    print(f"  model per-class recall: {pc}")


report(preds, "ALL 40")
report([r for r in preds if r["_subset"] == "example28"], "example28 (curated)")
report([r for r in preds if r["_subset"] == "kceleb12"], "kceleb12 (Korean celeb)")

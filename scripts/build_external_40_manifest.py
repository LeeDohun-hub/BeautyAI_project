"""Build a 40-image external test manifest:
   28 curated personalcolor_example + 12 Korean-celebrity crops (3/season, strong consensus).
Korean celebs verified to have 0 identity overlap with the FT-v1 training manifest.
"""
import csv
import os
import re
import collections

ROWS = []
MP = {"autumnwarm": "autumn", "wintercool": "winter", "springwarm": "spring", "summercool": "summer"}
for fn in sorted(os.listdir("personalcolor_example")):
    if not fn.lower().endswith((".jpg", ".jpeg", ".png")):
        continue
    key = re.sub(r"[0-9].*", "", fn).lower()
    ROWS.append(("personalcolor_example/" + fn, MP[key], "example28"))

PICKS = {
    "spring": ["송혜교", "윤아", "아이유"],
    "summer": ["이영애", "손예진", "아이린"],
    "autumn": ["이성경", "한예슬", "이효리"],
    "winter": ["김혜수", "서예지", "김옥빈"],
}

crops = {}
with open("data/manifests/korean_celebrity_face_crop_manifest.csv", newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        base = os.path.basename(r["image_path"])
        name = base.split("_")[0]
        crops.setdefault(name, []).append(r["image_path"])

added = 0
missing = []
for season, names in PICKS.items():
    for nm in names:
        chosen = next((c for c in sorted(crops.get(nm, [])) if os.path.exists(c)), None)
        if chosen:
            ROWS.append((chosen.replace(os.sep, "/"), season, "kceleb12"))
            added += 1
        else:
            missing.append((season, nm, len(crops.get(nm, []))))

with open("data/eval/external_40_manifest.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["image_path", "label", "subset"])
    for p, l, s in ROWS:
        w.writerow([p, l, s])

print("total rows =", len(ROWS), "| kceleb added =", added, "| missing =", missing)
print("season dist =", dict(collections.Counter(l for _, l, _ in ROWS)))
print("subset dist =", dict(collections.Counter(s for _, _, s in ROWS)))

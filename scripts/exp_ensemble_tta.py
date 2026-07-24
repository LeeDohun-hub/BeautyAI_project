"""추가 레버 실측: 모델 앙상블(v1+v2+v3) / TTA(수평뒤집기) / 다중프레임 / 신뢰도 게이팅.

세 모델 모두 동일 129명 val 분할(누수無). 규칙은 train 인물의 참 Lab 으로만 적합.
v2·v3 은 9차원(3부위xLab)→얼굴평균 3차원으로 환산해 v1 과 앙상블.
"""
from __future__ import annotations
import collections, csv
from pathlib import Path
from statistics import median
import os
import numpy as np, torch, torch.nn as nn
from PIL import Image
from torchvision import models, transforms

torch.set_num_threads(os.cpu_count() or 4)
ROOT = Path(__file__).resolve().parents[1]
MAN = ROOT / "data/manifests/aihub_pc_manifest.csv"
BASE_TF = transforms.Compose([transforms.Resize((224, 224)), transforms.ToTensor(),
                              transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])
def ita(L, b): return float(np.degrees(np.arctan2(L - 50.0, b)))

def load_model(path, dim_out):
    ck = torch.load(ROOT / path, map_location="cpu", weights_only=False)
    net = models.efficientnet_b0(weights=None); d = net.classifier[1].in_features
    net.classifier = nn.Identity(); net.load_state_dict(ck["feat"])
    head = nn.Linear(d, dim_out); head.load_state_dict(ck["head"]); net.eval(); head.eval()
    mean = np.asarray(ck.get("target_mean", ck.get("lab_mean")), np.float32)
    std = np.asarray(ck.get("target_std", ck.get("lab_std")), np.float32)
    return net, head, mean, std, set(ck["val_uids"])

def face_pred(net, head, mean, std, x, bs=32):
    out = []
    with torch.no_grad():
        for i in range(0, len(x), bs):
            p = head(net(x[i:i+bs])).numpy() * std + mean
            out.append(p)
    p = np.concatenate(out)
    if p.shape[1] == 9:  # 3부위x Lab → 얼굴평균
        p = p.reshape(len(p), 3, 3).mean(1)
    return p  # (N,3)

def main():
    m1 = load_model("data/models/aihub_pc_lab.pt", 3)
    m2 = load_model("data/models/aihub_pc_lab_v2.pt", 9)
    m3 = load_model("data/models/aihub_pc_lab_v3.pt", 9)
    val_uids = m1[4] & m2[4] & m3[4]
    rows = list(csv.DictReader(MAN.open(encoding="utf-8")))
    tr = [r for r in rows if r["uid"] not in val_uids]
    va = [r for r in rows if r["uid"] in val_uids]

    # 규칙 (train 참Lab)
    tp = {r["uid"]: r for r in tr}
    xs = np.array([float(p["ita_avg"]) for p in tp.values()]); ys = np.array([float(p["lab_b"]) for p in tp.values()])
    slope = float(((xs-xs.mean())*(ys-ys.mean())).sum()/((xs-xs.mean())**2).sum()); inter = float(ys.mean()-slope*xs.mean())
    med = float(median(xs))
    def seas(L, a, b):
        I = ita(L, b); warm = b-(slope*I+inter) > 0; light = I > med
        return ("spring" if light else "autumn") if warm else ("summer" if light else "winter")

    # 이미지 로드 + 4예측(원본/flip x ... 실은 모델별). 모든 val 프레임.
    imgs = [Image.open(ROOT / r["image_path"]).convert("RGB") for r in va]
    X = torch.stack([BASE_TF(im) for im in imgs])
    Xf = torch.flip(X, dims=[3])  # 수평 뒤집기 TTA
    print(f"val {len(va)}프레임 / {len(val_uids)}명 추론...", flush=True)
    preds = {}  # name -> (N,3)
    for nm, mdl in [("v1", m1), ("v2", m2), ("v3", m3)]:
        net, head, mean, std, _ = mdl
        preds[nm] = face_pred(net, head, mean, std, X)
        preds[nm+"_f"] = face_pred(net, head, mean, std, Xf)
        print(f"  {nm} done", flush=True)

    true = np.array([[float(r["lab_l"]), float(r["lab_a"]), float(r["lab_b"])] for r in va], np.float32)
    uids = [r["uid"] for r in va]
    true_seas = [seas(*true[i]) for i in range(len(va))]

    def de(P): return np.sqrt(((P-true)**2).sum(1)).mean()
    def acc_frame(P): return np.mean([seas(*P[i]) == true_seas[i] for i in range(len(P))])
    def acc_person(P):
        by = collections.defaultdict(list); ts = {}
        for i in range(len(P)): by[uids[i]].append(P[i]); ts[uids[i]] = true_seas[i]
        return np.mean([seas(*np.mean(v, 0)) == ts[u] for u, v in by.items()])
    def consistency(P):
        by = collections.defaultdict(list)
        for i in range(len(P)): by[uids[i]].append(seas(*P[i]))
        full = [v for v in by.values() if len(v) == 4]
        return np.mean([len(set(v)) == 1 for v in full])

    # ⚠️ v2 는 500lux 전용 학습 → 5000lux 에서 붕괴(ΔE≈26). 앙상블은 all-lux 정상인 v1+v3 만.
    ens = (preds["v1"]+preds["v3"])/2
    ens_tta = sum(preds[k] for k in ["v1","v3","v1_f","v3_f"])/4
    print("\n"+"="*76)
    print(f"{'방법':<40}{'ΔE':>7}{'acc(프레임)':>12}{'acc(per-person)':>16}{'일치도':>8}")
    print("-"*76)
    for nm, P in [("v1 단독",preds["v1"]),("v3 단독",preds["v3"]),("v2 단독(참고:500lux전용)",preds["v2"]),
                  ("앙상블 v1+v3", ens),("앙상블 v1+v3 + TTA(flip)", ens_tta)]:
        print(f"{nm:<38}{de(P):>7.3f}{acc_frame(P):>11.1%}{acc_person(P):>15.1%}{consistency(P):>9.1%}")
    print("-"*76)
    print(f"{'앙상블+TTA + 다중프레임(per-person)':<44}{'':<7}{'':<11}{acc_person(ens_tta):>15.1%}  ← 종합")
    print("="*76)

    # 신뢰도 게이팅: 사람별 16개 미니추정(v1·v3 x4프레임 x2flip) 다수결 + 동의율. 동의율 높은 순 커버리지.
    keys_clean = ["v1","v3","v1_f","v3_f"]
    by = collections.defaultdict(list); ts = {}
    allP = {**preds}
    for i in range(len(va)):
        votes = [seas(*allP[k][i]) for k in keys_clean]
        by[uids[i]].extend(votes); ts[uids[i]] = true_seas[i]
    peeps = []
    for u, votes in by.items():
        c = collections.Counter(votes); maj, cnt = c.most_common(1)[0]
        peeps.append((cnt/len(votes), maj == ts[u]))
    peeps.sort(reverse=True)  # 동의율 높은 순
    print("\n[신뢰도 게이팅 A: 다중프레임 vote] 상위 커버리지별 정확도")
    for cov in (1.0, 0.75, 0.5, 0.25):
        k = max(1, int(len(peeps)*cov)); sub = peeps[:k]
        print(f"   상위 {cov:>4.0%} (n={k:3d}): 정확도 {np.mean([ok for _,ok in sub]):.1%}  최저동의율 {sub[-1][0]:.2f}")

    # ── 게이팅 B: 단일 이미지 margin 기반 (배포 현실 — 프레임 1장만) ──
    # ens+TTA Lab 의 소프트확률 max 를 신뢰도로. 프레임 단위(사람×조명 각각) 채점.
    SL, IN, MED = slope, inter, med
    def conf_and_ok(P):
        rows_out = []
        for i in range(len(P)):
            L, _a, b = P[i]; I = ita(L, b)
            um = (b - (SL*I+IN))/1.56; dm = (I-MED)/9.2
            pw = 1/(1+np.exp(-np.clip(um,-60,60))); pl = 1/(1+np.exp(-np.clip(dm,-60,60)))
            probs = {"spring":pw*pl,"autumn":pw*(1-pl),"summer":(1-pw)*pl,"winter":(1-pw)*(1-pl)}
            top = max(probs, key=probs.get)
            rows_out.append((probs[top], top == true_seas[i]))
        return sorted(rows_out, reverse=True)
    g = conf_and_ok(ens_tta)
    print("\n[신뢰도 게이팅 B: 단일이미지 margin (ens+TTA)] 상위 커버리지별 정확도  ← 배포 현실")
    for cov in (1.0, 0.75, 0.5, 0.25):
        k = max(1, int(len(g)*cov)); sub = g[:k]
        print(f"   상위 {cov:>4.0%} (n={k:3d}): 정확도 {np.mean([ok for _,ok in sub]):.1%}  최저신뢰도 {sub[-1][0]:.2f}")

if __name__ == "__main__":
    main()

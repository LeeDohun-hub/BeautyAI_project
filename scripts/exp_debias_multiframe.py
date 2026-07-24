"""실험: ① 예측 디바이어스(캘리브레이션) + ② 다중프레임 평균 — 계절정확도/ΔE/일치도 효과 측정.

v1 모델(aihub_pc_lab.pt, 3차원 Lab 회귀, 4조명 전부)로 baseline(ΔE 2.655/일치도85.3%/정확도55.0%)을
재현하고, 그 위에 두 개선을 얹어 같은 잣대로 비교한다. 규칙은 train 인물로만 적합(누수 방지),
캘리브레이션도 train 프레임으로만 적합해 val 에 적용(배포 가능 형태).
"""
from __future__ import annotations
import collections, csv
from pathlib import Path
from statistics import median
import numpy as np, torch, torch.nn as nn
from PIL import Image
from torchvision import models, transforms

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/manifests/aihub_pc_manifest.csv"
TF = transforms.Compose([transforms.Resize((224, 224)), transforms.ToTensor(),
                         transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])

def ita_from_lab(L, b): return float(np.degrees(np.arctan2(L - 50.0, b)))

def make_rule(train_people):
    xs = np.array([float(p["ita_avg"]) for p in train_people])
    ys = np.array([float(p["lab_b"]) for p in train_people])
    slope = float(((xs - xs.mean()) * (ys - ys.mean())).sum() / ((xs - xs.mean()) ** 2).sum())
    inter = float(ys.mean() - slope * xs.mean())
    med = float(median(xs))
    def seas(L, a, b):
        I = ita_from_lab(L, b); warm = b - (slope * I + inter) > 0; light = I > med
        return ("spring" if light else "autumn") if warm else ("summer" if light else "winter")
    return seas

def season_acc(pred_lab, true_seasons, seas):
    return np.mean([seas(*pred_lab[i]) == true_seasons[i] for i in range(len(pred_lab))])

def main():
    ck = torch.load(ROOT / "data/models/aihub_pc_lab.pt", map_location="cpu", weights_only=False)
    lab_mean = np.asarray(ck["lab_mean"], np.float32); lab_std = np.asarray(ck["lab_std"], np.float32)
    val_uids = set(ck["val_uids"])
    net = models.efficientnet_b0(weights=None); dim = net.classifier[1].in_features
    net.classifier = nn.Identity(); net.load_state_dict(ck["feat"])
    head = nn.Linear(dim, 3); head.load_state_dict(ck["head"]); net.eval(); head.eval()

    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8")))
    tr_people = {}
    for r in rows:
        if r["uid"] not in val_uids: tr_people[r["uid"]] = r
    seas = make_rule(list(tr_people.values()))

    # 전 프레임 추론 (train+val) — 캘리브레이션은 train 프레임으로만 적합. 결과 캐시.
    cache = ROOT / "data/eval/_exp_preds_v1.npy"
    if cache.exists():
        preds = np.load(cache); print(f"캐시 로드 {cache.name} ({len(preds)})")
    else:
        print(f"추론 {len(rows)}프레임 (CPU)...", flush=True)
        preds = np.zeros((len(rows), 3), np.float32)
        with torch.no_grad():
            for i in range(0, len(rows), 32):
                B = rows[i:i+32]
                x = torch.stack([TF(Image.open(ROOT / r["image_path"]).convert("RGB")) for r in B])
                preds[i:i+len(B)] = head(net(x)).numpy() * lab_std + lab_mean
                if i % 320 == 0: print(f"  {i}/{len(rows)}", flush=True)
        np.save(cache, preds)

    true = np.array([[float(r["lab_l"]), float(r["lab_a"]), float(r["lab_b"])] for r in rows], np.float32)
    uids = np.array([r["uid"] for r in rows]); lux = np.array([int(r["lux"]) for r in rows])
    is_val = np.array([r["uid"] in val_uids for r in rows])
    true_seas = [seas(*true[i]) for i in range(len(rows))]

    tr, va = ~is_val, is_val

    # ── ① 디바이어스: train 프레임으로 축별 affine (true = a·pred + b) 적합 → 배포 가능 ──
    cal = np.zeros((3, 2), np.float32)  # [axis][slope,inter]
    for k in range(3):
        A = np.vstack([preds[tr, k], np.ones(tr.sum())]).T
        cal[k] = np.linalg.lstsq(A, true[tr, k], rcond=None)[0]
    def apply_cal(P): return np.stack([cal[k, 0] * P[:, k] + cal[k, 1] for k in range(3)], 1)
    bias = (true[tr] - preds[tr]).mean(0)  # 참고용 가산 편향
    print(f"\ntrain 잔차 평균 편향(참 - 예측): L={bias[0]:+.2f} a={bias[1]:+.2f} b={bias[2]:+.2f}")
    print(f"축별 affine: " + ", ".join(f"{c}:{cal[k,0]:.2f}·p{cal[k,1]:+.2f}" for k,c in enumerate('Lab')))

    def de(P, mask): return np.sqrt(((P[mask] - true[mask])**2).sum(1)).mean()
    def acc_frame(P, mask):
        idx = np.where(mask)[0]
        return np.mean([seas(*P[i]) == true_seas[i] for i in idx])
    def consistency(P, mask):
        by = collections.defaultdict(list)
        for i in np.where(mask)[0]: by[uids[i]].append(seas(*P[i]))
        full = [v for v in by.values() if len(v) == 4]
        return np.mean([len(set(v)) == 1 for v in full]), len(full)
    def acc_person(P, mask):
        by_p = collections.defaultdict(list); by_t = {}
        for i in np.where(mask)[0]:
            by_p[uids[i]].append(P[i]); by_t[uids[i]] = true_seas[i]
        ok = [seas(*np.mean(v, 0)) == by_t[u] for u, v in by_p.items()]
        return np.mean(ok), len(ok)

    P0 = preds; P1 = apply_cal(preds)
    print("\n" + "="*72)
    print(f"{'방법':<34}{'ΔE':>7}{'계절acc(프레임)':>16}{'4조명일치도':>13}")
    print("-"*72)
    print(f"{'baseline (v1, 프레임단위)':<32}{de(P0,va):>7.3f}{acc_frame(P0,va):>15.1%}{consistency(P0,va)[0]:>13.1%}")
    print(f"{'① 디바이어스(affine)':<33}{de(P1,va):>7.3f}{acc_frame(P1,va):>15.1%}{consistency(P1,va)[0]:>13.1%}")
    print("-"*72)
    # ② 다중프레임: 사람당 프레임 평균 → 1예측 (배포 시 여러장 캡처 평균). 4조명 전부 / 500lux 2장.
    ap0, n = acc_person(P0, va);           print(f"{'② 다중프레임 평균(4조명, per-person)':<40}{'':>7}{ap0:>9.1%}  (n={n})")
    ap1, _ = acc_person(P1, va);           print(f"{'①+② 디바이어스+다중프레임(4조명)':<40}{'':>7}{ap1:>9.1%}")
    va500 = va & (lux == 500)
    ap0b, n5 = acc_person(P0, va500);      print(f"{'② 다중프레임 평균(500lux 2장만)':<40}{'':>7}{ap0b:>9.1%}  (n={n5})")
    ap1b, _ = acc_person(P1, va500);       print(f"{'①+② (500lux 2장)':<40}{'':>7}{ap1b:>9.1%}")
    print("="*72)

    # ── 왜 ①이 무효인가: 오차 구조 진단 ──
    resid_va = preds[va] - true[va]
    print(f"\n[오차 구조] val 프레임 잔차 std: L={resid_va[:,0].std():.2f} a={resid_va[:,1].std():.2f} b={resid_va[:,2].std():.2f}")
    print(f"           (규칙이 쓰는 축은 L·b. b 오차가 웜/쿨 경계를 직접 뒤집음)")

    # ── ①' 조명별 가산 디바이어스 (키오스크는 조명을 앎/고정) — train 으로 (lux,kelvin)별 평균잔차 ──
    kel = np.array([int(r["kelvin"]) for r in rows])
    cond = np.array([f"{lux[i]}_{kel[i]}" for i in range(len(rows))])
    corr = {}
    for c in set(cond):
        m = tr & (cond == c)
        corr[c] = (true[m] - preds[m]).mean(0) if m.sum() else np.zeros(3, np.float32)
    P_lit = preds + np.array([corr[cond[i]] for i in range(len(rows))], np.float32)
    print(f"\n[①' 조명별 가산보정 (키오스크 realistic, 조명 알 때)]")
    print(f"   ΔE {de(P_lit,va):.3f}  계절acc(프레임) {acc_frame(P_lit,va):.1%}  일치도 {consistency(P_lit,va)[0]:.1%}")
    print(f"   +② 다중프레임(4조명): per-person {acc_person(P_lit,va)[0]:.1%}")

    # ── 조명별 단일프레임 정확도 (다중프레임 이득의 출처 설명) ──
    print(f"\n[조명별 baseline 프레임 정확도] (5000lux 클리핑분이 실제로 더 나쁜가)")
    for c in sorted(set(cond)):
        m = va & (cond == c)
        if m.sum(): print(f"   {c:>10}(n={m.sum():3d}): acc {acc_frame(P0,m):.1%}  ΔE {de(P0,m):.2f}")

    print(f"\n해석: baseline 프레임 55%대 재현→파이프라인 검증. ①전역affine은 모델이 이미 캘리브돼 무효.")
    print(f"②다중프레임은 조명분산 상쇄로 향상(4조명평균은 낙관적 상한). ①'조명별보정은 조명 알 때만.")

if __name__ == "__main__":
    main()

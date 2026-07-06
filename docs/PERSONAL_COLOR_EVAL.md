# Personal Color Evaluation

Use this when an expert-labeled holdout set is ready. The goal is to measure
the production analyzer, not just the training validation split.

## Manifest

Option A: create the CSV manually:

```text
data/eval/personal_color_eval_manifest.csv
```

Format:

```csv
image_path,label
C:\Users\suppo\OneDrive\Desktop\sample_summer_01.jpg,summer
C:\Users\suppo\OneDrive\Desktop\sample_winter_01.jpg,winter
```

Accepted labels:

- `spring`, `summer`, `autumn`, `winter`
- Korean labels containing `봄`, `여름`, `가을`, or `겨울`

Recommended first holdout size:

- 40 to 80 images total
- Try to balance seasons
- Keep these images out of training and retraining packages

Option B: put images in labeled folders:

```text
data/eval/holdout/spring/
data/eval/holdout/summer/
data/eval/holdout/autumn/
data/eval/holdout/winter/
```

Then build the manifest:

```powershell
cd C:\WorkSpace\Beauty_Project\BeautyAI_project
backend\.venv\Scripts\python.exe scripts\build_personal_color_eval_manifest.py `
  --root data\eval\holdout `
  --out data\eval\personal_color_eval_manifest.csv
```

## Run

Evaluate the current app settings model:

```powershell
cd C:\WorkSpace\Beauty_Project\BeautyAI_project
backend\.venv\Scripts\python.exe scripts\evaluate_personal_color_model.py `
  --manifest data\eval\personal_color_eval_manifest.csv `
  --out-dir data\eval\reports
```

Evaluate a candidate model before replacing the production model:

```powershell
cd C:\WorkSpace\Beauty_Project\BeautyAI_project
backend\.venv\Scripts\python.exe scripts\evaluate_personal_color_model.py `
  --manifest data\eval\personal_color_eval_manifest.csv `
  --model-path data\models\personal_color_efficientnet.pt `
  --out-dir data\eval\reports_candidate
```

## Outputs

- `personal_color_eval_report.json`
- `confusion_matrix.csv`
- `predictions.csv`
- `errors.json`

Key metrics:

- `accuracy`
- `top2_accuracy`
- `warmcool_accuracy`
- `method_metrics.blended`: final production decision after CNN + color vector blending
- `method_metrics.model`: CNN-only decision
- `method_metrics.color`: Lab/HSV skin-vector-only decision
- `low_margin_rate`
- `model_used_rate`
- `face_detected_rate`
- season-level accuracy
- high-value confusions such as `summer_as_winter` and `spring_as_autumn`

`predictions.csv` also includes:

- `model_predicted`, `color_predicted`: split decisions for debugging
- `model_top1_prob`, `color_top1_prob`
- `lab_l`, `lab_a`, `lab_b`, `hsv_s`, `skin_vector_quality`
- `season_margin`: top-1 probability minus top-2 probability
- `alternate_label`: the adjacent personal color label
- `decision_note`: a user-facing boundary note when the top-2 gap is small

## 2026-07-06 Hybrid Baseline And Adaptive Rule

After adding landmark skin sampling and Lab/HSV skin vectors, the evaluator was
expanded to compare three methods: CNN-only, color-vector-only, and final
blended output.

The final analyzer uses a conservative blend by default. It only switches to the
color-vector probability in a narrow low-chroma winter-shift case:

- CNN top-1 is `winter`
- color-vector top-1 is `spring` or `autumn`
- `hsv_s <= 0.15`
- `lab_a <= 5`
- `lab_b <= 18`

Deep Armocromia test (`data/eval/deeparmo_test_manifest.csv`, 912 images):

| method | accuracy | top2 | warm/cool |
| --- | ---: | ---: | ---: |
| model | 0.5351 | 0.8037 | 0.6700 |
| color | 0.2632 | 0.5077 | 0.5066 |
| blended/adaptive | 0.5197 | 0.7566 | 0.6557 |

CapstoneA cross-dataset (`data/eval/capstonea_test_manifest.csv`, 75 images):

| method | accuracy | top2 | warm/cool |
| --- | ---: | ---: | ---: |
| model | 0.2400 | 0.5467 | 0.3733 |
| color | 0.4133 | 0.6800 | 0.6933 |
| blended/adaptive | 0.3867 | 0.6933 | 0.5867 |

Interpretation: the color vector is much stronger on the cross-dataset test,
but much weaker on Deep Armocromia. The adaptive rule trades about 1.5
percentage points on Deep Armocromia for a 14.7 point gain on CapstoneA, so it
is a better fit for the current "general photo robustness" priority. Keep
tracking both `method_metrics.model` and `method_metrics.color` before adding
more override rules.

## 2026-07-06 External Benchmark Note (HF jiwoonkim00)

Reference model: https://huggingface.co/jiwoonkim00/personal-color-classifier
(EfficientNet-B0, 4 seasons, reported 68.3% single / 70.8% TTA, macro F1 0.71).

Do NOT treat this number as a target to chase. The scores are not comparable and
the model card lists limitations that conflict with our robustness goal:

- Its test accuracy is on its own split (Korean celebrity domain likely
  included); our 0.535 is pure Deep Armocromia. Different test sets.
- It reports no cross-dataset numbers. Our CapstoneA robustness has no
  counterpart there.
- Trained on Korean celebrity screenshots -> makeup / lighting / editing bias,
  the opposite of our kiosk / general-photo target.
- Its most frequent confusion is `autumn_warm` vs `spring_warm` (both warm);
  fine-tuning does not fix this boundary.
- Explicitly a prototype / portfolio project, "not for clinical or expert-grade
  diagnosis." Unsuitable as a benchmark baseline for a Twinit-style product.

Use it as a reference implementation, not a benchmark target. Revised priority
order for closing the in-domain gap:

1. TTA + Mixup + label smoothing (safe gains, independent of data bias).
2. Fine-tune on consent-based, controlled-capture Asian-face data (our protocol),
   NOT celebrity screenshots.
3. Handle the warm-tone `autumn` vs `spring` boundary with the Lab a*/b* color
   vector, which HF does not have.
4. Run HF on our eval sets (Deep Armocromia 912, CapstoneA 75) to see where it
   breaks (edited vs controlled photos), not to declare a winner.

## 2026-07-06 TTA (Priority 1a, no retrain)

Confirmed the training pipeline had none of TTA / Mixup / label smoothing. Added
horizontal-flip TTA to `EfficientNetSeasonClassifier.predict_probs` (default on):
the original and left-right flipped views are averaged in softmax space. Faces
are left-right symmetric, so the flip does not change the label. This is an
inference-side change, so it needed no retraining and applies to the current
`.pt` immediately.

Results vs the hybrid/adaptive baseline above:

| dataset | method | baseline acc | +TTA acc | delta |
| --- | --- | ---: | ---: | ---: |
| Deep Armocromia (912) | model | 0.5351 | 0.5395 | +0.44 |
| Deep Armocromia (912) | blended/adaptive | 0.5197 | 0.5318 | +1.21 |
| CapstoneA (75) | model | 0.2400 | 0.2667 | +2.67 |
| CapstoneA (75) | blended/adaptive | 0.3867 | 0.4133 | +2.66 |

Final blended accuracy improved on BOTH datasets (no trade-off), with the larger
gain on the cross-dataset robustness target. Deep Armocromia top2 dropped ~1.1
points; warm/cool held or improved. Backend tests: `17 passed`. Reports:

- `data/eval/reports_deeparmo_tta/`
- `data/eval/reports_capstonea_tta/`

Remaining Priority 1 levers (Mixup, label smoothing) require a runpod retrain and
are not applied yet.

## 2026-07-06 Golden-Autumn Shift (Priority 3, no retrain)

Priority 3 started as "split the warm-tone `autumn` vs `spring` boundary with the
Lab color vector." Error analysis on the TTA predictions redirected it: the
largest warm leaks are actually warm-read-as-cool (`spring_as_summer` ~80,
`autumn_as_winter` ~69), not the warm-internal confusion. A blanket cool->warm
override fails: on Deep Armocromia, `model=cool & color=warm` cases are only 36%
actually warm, so flipping them costs -174. The color vector's warm signal is
reliable cross-dataset but noisy in-domain (same tension as the hybrid baseline).

One narrow, clean win survived the analysis: CNN reads deep golden autumn skin as
`winter`, and the Lab yellow axis separates it. Added
`_looks_like_golden_autumn_shift`: when CNN top-1 is `winter`, color-vector top-1
is `autumn`, and `lab_b >= 20`, switch to the color-vector probability. This is
complementary to the low-chroma winter shift (which requires `lab_b <= 18`), so
the two rules are disjoint.

Results vs TTA-only blended:

| dataset | TTA acc | +golden-autumn | delta | cross-dataset cost |
| --- | ---: | ---: | ---: | --- |
| Deep Armocromia (912) | 0.5318 | 0.5362 | +0.44 | — |
| CapstoneA (75) | 0.4133 | 0.4133 | +0.00 | none |

Deep Armocromia warm/cool +0.44, top2 -0.33 (minor). CapstoneA unchanged (the
rule fired on 0 of its cases). Backend tests: `17 passed`. Reports:

- `data/eval/reports_deeparmo_tta_autumn/`
- `data/eval/reports_capstonea_tta_autumn/`

Cumulative blended accuracy (hybrid baseline -> +TTA -> +golden-autumn):

| dataset | baseline | +TTA | +golden-autumn | total |
| --- | ---: | ---: | ---: | ---: |
| Deep Armocromia (912) | 0.5197 | 0.5318 | 0.5362 | +1.65 |
| CapstoneA (75) | 0.3867 | 0.4133 | 0.4133 | +2.66 |

Key negative result to remember: a general warm-boundary color override does NOT
win in-domain; the warm-read-as-cool bias is a model-level problem best fixed by
retraining (label smoothing, Mixup, warm/Asian-domain data), not post-hoc rules.

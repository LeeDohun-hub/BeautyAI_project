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
- `low_margin_rate`
- `model_used_rate`
- `face_detected_rate`
- season-level accuracy
- high-value confusions such as `summer_as_winter` and `spring_as_autumn`

`predictions.csv` also includes:

- `season_margin`: top-1 probability minus top-2 probability
- `alternate_label`: the adjacent personal color label
- `decision_note`: a user-facing boundary note when the top-2 gap is small

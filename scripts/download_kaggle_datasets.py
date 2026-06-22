from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path
from shutil import which

DATASETS = [
    "bishalsharma000/facial-skin-datasets",
    "killa92/facial-skin-analysis-and-type-classification",
    "shijo96john/facial-skin-acne-pigmentation-pores-wrinkles",
    "nayanchaure/acne-dataset",
    "nadyinky/sephora-products-and-skincare-reviews",
    "crawlfeeds/dermstore-skincare-products-and-ingredients-dataset",
]


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def normalize_kaggle_credentials() -> None:
    api_key = os.environ.get("KAGGLE_API_KEY", "").strip()
    if not api_key:
        return
    if os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"):
        return

    if api_key.startswith("{"):
        try:
            payload = json.loads(api_key)
        except json.JSONDecodeError:
            return
        username = payload.get("username")
        key = payload.get("key")
        if username and key:
            os.environ.setdefault("KAGGLE_USERNAME", username)
            os.environ.setdefault("KAGGLE_KEY", key)
        return

    if ":" in api_key:
        username, key = api_key.split(":", 1)
        if username and key:
            os.environ.setdefault("KAGGLE_USERNAME", username)
            os.environ.setdefault("KAGGLE_KEY", key)
        return

    os.environ.setdefault("KAGGLE_KEY", api_key)


def safe_extract_zip(zip_path: Path, target_dir: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            member_path = Path(member.filename)
            if member.is_dir():
                (target_dir / member_path).mkdir(parents=True, exist_ok=True)
                continue
            destination = target_dir / member_path
            if len(str(destination.resolve())) > 240:
                digest = hashlib.sha1(member.filename.encode("utf-8", errors="ignore")).hexdigest()[:16]
                destination = target_dir / member_path.parent / f"{member_path.stem[:40]}_{digest}{member_path.suffix}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, destination.open("wb") as output:
                output.write(source.read())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/datasets/kaggle")
    parser.add_argument("--only", nargs="*", default=[])
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    selected = args.only or DATASETS
    load_env_file(Path(".env"))
    normalize_kaggle_credentials()

    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError:
        print("Kaggle package is not installed. Run: uv pip install -r backend/requirements-train.txt --python backend/.venv/Scripts/python.exe")
        return 2

    api = KaggleApi()
    try:
        api.authenticate()
    except OSError:
        if os.environ.get("KAGGLE_KEY") and not os.environ.get("KAGGLE_USERNAME"):
            print("KAGGLE_KEY is set, but KAGGLE_USERNAME is missing. Add KAGGLE_USERNAME to .env.")
            return 4
        print("Kaggle credentials were not found. Put kaggle.json in %USERPROFILE%\\.kaggle\\kaggle.json or set KAGGLE_USERNAME/KAGGLE_KEY.")
        return 3

    if not which("kaggle") and sys.platform != "win32":
        print("Kaggle CLI was not found on PATH, but python -m kaggle will still be attempted.")

    for slug in selected:
        target = out_dir / slug.replace("/", "__")
        target.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {slug} -> {target}")
        try:
            existing_zips = list(target.glob("*.zip"))
            if existing_zips:
                zip_path = existing_zips[0]
            else:
                api.dataset_download_files(slug, path=target, unzip=False, quiet=False)
                zips = list(target.glob("*.zip"))
                if not zips:
                    raise FileNotFoundError(f"No zip file downloaded for {slug}")
                zip_path = zips[0]
            safe_extract_zip(zip_path, target)
        except Exception as exc:
            print("Kaggle download failed. Check ~/.kaggle/kaggle.json or KAGGLE_USERNAME/KAGGLE_KEY.")
            print(str(exc))
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import re
import shutil
import tempfile
import zipfile
from pathlib import Path


CLASS_ALIASES = {
    "atopic_dermatitis": ("atopic dermatitis", "atopic_dermatitis", "ad"),
    "contact_dermatitis": ("contact dermatitis", "contact_dermatitis", "cd"),
    "eczema": ("eczema", "ec"),
    "scabies": ("scabies", "sc"),
    "seborrheic_dermatitis": (
        "seborrheic dermatitis",
        "seborrheic_dermatitis",
        "sd",
    ),
    "tinea_corporis": ("tinea corporis", "tinea_corporis", "tc"),
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def normalized(value: str) -> str:
    return re.sub(r"[^a-z]+", " ", value.lower()).strip()


def class_for_path(path: str) -> str | None:
    text = normalized(path)
    parts = [normalized(part) for part in Path(path).parts]
    for class_name, aliases in CLASS_ALIASES.items():
        if any(
            normalized(alias) in text
            if len(normalized(alias)) > 2
            else normalized(alias) in parts
            for alias in aliases
        ):
            return class_name
    return None


def is_original_path(path: str) -> bool:
    text = normalized(path)
    return "preprocessed" in text or "augmented" not in text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--archive",
        default="data/datasets/skindisnet/yj3md44hxg-1.zip",
    )
    parser.add_argument(
        "--out",
        default="data/datasets/skindisnet/preprocessed",
    )
    args = parser.parse_args()

    archive = Path(args.archive)
    out = Path(args.out)
    if not archive.exists():
        raise SystemExit(f"Archive not found: {archive}")

    counts = {name: 0 for name in CLASS_ALIASES}
    source_archive = archive
    temporary_archive: Path | None = None
    with zipfile.ZipFile(archive) as outer:
        nested_archives = [
            entry for entry in outer.infolist()
            if Path(entry.filename).suffix.lower() == ".zip"
        ]
        image_entries = [
            entry for entry in outer.infolist()
            if Path(entry.filename).suffix.lower() in IMAGE_EXTENSIONS
        ]
        if nested_archives and not image_entries:
            temporary_archive = Path(tempfile.gettempdir()) / "skindisnet-inner.zip"
            print(f"Extracting nested archive to {temporary_archive}")
            with outer.open(nested_archives[0]) as source, temporary_archive.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
            source_archive = temporary_archive

    with zipfile.ZipFile(source_archive) as source:
        for entry in source.infolist():
            suffix = Path(entry.filename).suffix.lower()
            class_name = class_for_path(entry.filename)
            if (
                entry.is_dir()
                or suffix not in IMAGE_EXTENSIONS
                or class_name is None
                or not is_original_path(entry.filename)
            ):
                continue
            destination = out / class_name / f"{counts[class_name]:05d}{suffix}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            with source.open(entry) as input_file, destination.open("wb") as output_file:
                output_file.write(input_file.read())
            counts[class_name] += 1

    print("Prepared SkinDisNet originals:")
    for name, count in counts.items():
        print(f"  {name}: {count}")
    if sum(counts.values()) < 1000:
        raise SystemExit(
            "Too few original images were found. Inspect the archive folder names."
        )
    if temporary_archive is not None:
        temporary_archive.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

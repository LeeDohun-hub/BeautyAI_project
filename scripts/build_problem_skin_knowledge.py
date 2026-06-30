from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path("data/02.문제성 피부 메이크업 추천 데이터")
DEFAULT_OUT = Path("data/rag/problem_skin_knowledge.jsonl")


def text(value: Any) -> str:
    return str(value or "").strip()


def source_titles(payload: dict[str, Any]) -> list[str]:
    titles = []
    for index in range(1, 6):
        title = text(payload.get(f"Source_info{index}", {}).get(f"Title{index}"))
        if title and title not in titles:
            titles.append(title)
    return titles


def to_record(payload: dict[str, Any], archive: Path, entry_name: str) -> dict[str, Any] | None:
    human = payload.get("Human_info", {})
    skin = payload.get("Skin_info", {})
    annotation = payload.get("Annotation_info", {})
    question = text(annotation.get("User Question"))
    answer = text(annotation.get("Makeup Response"))
    problem = text(human.get("Skin Problem Type"))
    if not question or not answer or not problem:
        return None

    return {
        "id": text(payload.get("Data_info", {}).get("SEQ")) or Path(entry_name).stem,
        "skin_problem": problem,
        "gender": text(human.get("Gender")),
        "age": text(human.get("Age")),
        "skin_condition": text(skin.get("Skin condition category")),
        "skin_brightness": text(skin.get("Skin Brightness")),
        "makeup_focus": text(human.get("Makeup focus areas")),
        "makeup_purpose": text(human.get("makeup purpose")),
        "question": question,
        "answer": answer,
        "recommended_ingredients": text(annotation.get("Recommended Ingredients")),
        "avoid_ingredients": text(annotation.get("Ingredients to Avoid")),
        "source_titles": source_titles(payload),
        "archive": archive.name,
    }


def iter_records(root: Path):
    label_archives = sorted(root.rglob("*라벨링데이터/*.zip"))
    for archive_path in label_archives:
        with zipfile.ZipFile(archive_path) as archive:
            for entry in archive.infolist():
                if entry.is_dir() or not entry.filename.lower().endswith(".json"):
                    continue
                with archive.open(entry) as source:
                    payload = json.loads(source.read().decode("utf-8-sig"))
                record = to_record(payload, archive_path, entry.filename)
                if record:
                    yield record


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser(
        description="Build a lightweight JSONL search index from the AI Hub problem-skin labels."
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if not args.root.is_dir():
        print(f"Dataset directory not found: {args.root}")
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    problem_counts: dict[str, int] = {}
    with args.out.open("w", encoding="utf-8", newline="\n") as output:
        for record in iter_records(args.root):
            output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
            problem = record["skin_problem"]
            problem_counts[problem] = problem_counts.get(problem, 0) + 1

    print(f"Wrote {count} records to {args.out}")
    for problem, item_count in sorted(problem_counts.items()):
        print(f"- {problem}: {item_count}")
    return 0 if count else 1


if __name__ == "__main__":
    raise SystemExit(main())

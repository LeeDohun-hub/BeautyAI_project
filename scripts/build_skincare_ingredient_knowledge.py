from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path("data/03.스킨케어 성분-효능 추천 데이터")
DEFAULT_OUT = Path("data/rag/skincare_ingredient_knowledge.jsonl")


def text(value: Any) -> str:
    return str(value or "").strip()


def to_record(payload: dict[str, Any], archive: Path, entry_name: str) -> dict[str, Any] | None:
    info = payload.get("info", {})
    meta = payload.get("meta", {})
    external = payload.get("external", [])

    question = text(info.get("question"))
    answer = text(info.get("answer"))
    concern = text(info.get("target_concern"))
    if not question or not answer or not concern:
        return None

    external_factors = []
    if isinstance(external, list):
        for item in external:
            if isinstance(item, dict):
                factor = text(item.get("factor"))
                details = text(item.get("details"))
                if factor or details:
                    external_factors.append(" ".join(part for part in (factor, details) if part))

    evidence = info.get("evidence_sources")
    if not isinstance(evidence, list):
        evidence = []

    return {
        "id": text(info.get("id")) or Path(entry_name).stem,
        "target_concern": concern,
        "question": question,
        "answer": answer,
        "evidence_sources": [text(item) for item in evidence if text(item)],
        "gender": text(meta.get("gender")),
        "age": text(meta.get("age")),
        "skin_type": text(meta.get("skin_type")),
        "skin_concerns": [text(item) for item in meta.get("skin_concerns", []) if text(item)]
        if isinstance(meta.get("skin_concerns"), list)
        else [],
        "external_factors": external_factors,
        "image_filename": text(meta.get("image_filename")),
        "archive": archive.name,
    }


def iter_records(root: Path):
    for archive_path in sorted(root.rglob("*.zip")):
        if "라벨링데이터" not in str(archive_path):
            continue
        try:
            archive = zipfile.ZipFile(archive_path)
        except zipfile.BadZipFile:
            continue
        with archive:
            for entry in archive.infolist():
                if entry.is_dir() or not entry.filename.lower().endswith(".jsonl"):
                    continue
                with archive.open(entry) as source:
                    for raw_line in source.read().decode("utf-8-sig").splitlines():
                        if not raw_line.strip():
                            continue
                        payload = json.loads(raw_line)
                        record = to_record(payload, archive_path, entry.filename)
                        if record:
                            yield record


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser(
        description="Build JSONL skincare ingredient knowledge from AI Hub skincare efficacy labels."
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if not args.root.is_dir():
        print(f"Dataset directory not found: {args.root}")
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    concern_counts: dict[str, int] = {}
    with args.out.open("w", encoding="utf-8", newline="\n") as output:
        for record in iter_records(args.root):
            output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
            concern = record["target_concern"]
            concern_counts[concern] = concern_counts.get(concern, 0) + 1

    print(f"Wrote {count} records to {args.out}")
    for concern, item_count in sorted(concern_counts.items()):
        print(f"- {concern}: {item_count}")
    return 0 if count else 1


if __name__ == "__main__":
    raise SystemExit(main())

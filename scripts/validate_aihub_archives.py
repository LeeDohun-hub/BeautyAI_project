from __future__ import annotations

import argparse
import json
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_ROOTS = (
    Path("data/01.글로벌 다인종 피부색 데이터"),
    Path("data/02.문제성 피부 메이크업 추천 데이터"),
)


@dataclass(frozen=True)
class ArchiveResult:
    path: str
    status: str
    entries: int
    expanded_bytes: int
    error: str | None = None


def validate_archive(path: Path) -> ArchiveResult:
    if path.stat().st_size == 0:
        return ArchiveResult(
            path=str(path),
            status="invalid",
            entries=0,
            expanded_bytes=0,
            error="empty file",
        )

    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            bad_entry = archive.testzip()
            if bad_entry is not None:
                return ArchiveResult(
                    path=str(path),
                    status="invalid",
                    entries=len(entries),
                    expanded_bytes=sum(entry.file_size for entry in entries),
                    error=f"CRC check failed: {bad_entry}",
                )
            return ArchiveResult(
                path=str(path),
                status="ok",
                entries=len(entries),
                expanded_bytes=sum(entry.file_size for entry in entries),
            )
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        return ArchiveResult(
            path=str(path),
            status="invalid",
            entries=0,
            expanded_bytes=0,
            error=str(exc),
        )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser(
        description="Validate downloaded AI Hub ZIP archives before extraction."
    )
    parser.add_argument(
        "roots",
        nargs="*",
        type=Path,
        default=list(DEFAULT_ROOTS),
        help="Directories to scan recursively (defaults to the two AI Hub datasets).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of the text report.",
    )
    args = parser.parse_args()

    missing_roots = [root for root in args.roots if not root.is_dir()]
    if missing_roots:
        for root in missing_roots:
            print(f"Missing dataset directory: {root}")
        return 2

    archives = sorted(
        path
        for root in args.roots
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() == ".zip"
    )
    partial_downloads = sorted(
        path
        for root in args.roots
        for path in root.rglob("*")
        if path.is_file() and ".zip." in path.name.lower()
    )
    results = [validate_archive(path) for path in archives]
    invalid = [result for result in results if result.status != "ok"]

    if args.json:
        print(
            json.dumps(
                {
                    "archives": [asdict(result) for result in results],
                    "partial_downloads": [str(path) for path in partial_downloads],
                    "summary": {
                        "total": len(results),
                        "ok": len(results) - len(invalid),
                        "invalid": len(invalid),
                        "partial": len(partial_downloads),
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for result in invalid:
            print(f"INVALID  {result.path}: {result.error}")
        for path in partial_downloads:
            print(f"PARTIAL  {path}")
        print(
            f"Checked {len(results)} archives: "
            f"{len(results) - len(invalid)} ok, "
            f"{len(invalid)} invalid, "
            f"{len(partial_downloads)} partial downloads"
        )

    return 1 if invalid or partial_downloads else 0


if __name__ == "__main__":
    raise SystemExit(main())

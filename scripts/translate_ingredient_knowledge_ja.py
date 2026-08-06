"""성분 지식 코퍼스(한국어)를 일본어로 번역해 `*.ja.jsonl` 을 만든다.

왜 별도 파일인가
  원본을 건드리지 않는다. 한국어 코퍼스 재생성과 번역 작업이 서로를 막지 않고,
  번역이 없는 레코드는 일본어 모드에서 그냥 문단이 빠진다(한국어가 새지 않는다).
  붙이는 키는 레코드 `id` 다 — skincare_ingredient_knowledge._ja_answers() 가 그 키로 찾는다.

규모(2026-08-06 실측)
  8,341 레코드 / 번역 대상 약 306만 자.
  한 번에 다 돌리지 않아도 되게 **재개 가능**하게 만들었다 — 이미 번역된 id 는 건너뛴다.

사용
  export ANTHROPIC_API_KEY=...
  python scripts/translate_ingredient_knowledge_ja.py --limit 50      # 맛보기
  python scripts/translate_ingredient_knowledge_ja.py                 # 전체(재개)
  python scripts/translate_ingredient_knowledge_ja.py --dry-run       # 비용만 추정

⚠ 유료 API 를 호출한다. --dry-run 으로 먼저 규모를 확인할 것.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "rag" / "skincare_ingredient_knowledge.jsonl"
TARGET = ROOT / "data" / "rag" / "skincare_ingredient_knowledge.ja.jsonl"

# 의학 인접 문구라 의미를 바꾸지 않는 것이 최우선이다. 성분명은 일본에서 통용되는 표기로
# 옮기되(예: 나이아신아마이드 → ナイアシンアミド), 확신이 없으면 원문을 괄호로 병기하게 한다.
SYSTEM = """あなたは化粧品・皮膚科学の専門翻訳者です。韓国語の肌悩みアドバイスを日本語に翻訳します。

規則:
- 意味を変えない。断定を強めたり、効能を誇張しない。
- 成分名は日本の化粧品表示で一般的な表記にする。確信が持てない場合は日本語表記の後に韓国語原文を括弧で併記する。
- 「〜します」「〜です」の丁寧体で、簡潔に。
- 医療行為を勧める表現にしない。原文が「相談を検討」ならその強さを保つ。
- 出力は翻訳文のみ。前置き・後書き・引用符を付けない。"""


def _load(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def _done_ids(path: Path) -> set[str]:
    return {str(row.get("id", "")) for row in _load(path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="이번 실행에서 번역할 최대 건수(0=전체)")
    parser.add_argument("--dry-run", action="store_true", help="호출 없이 남은 분량만 계산")
    parser.add_argument("--model", default="claude-haiku-4-5-20251001")
    args = parser.parse_args()

    rows = _load(SOURCE)
    if not rows:
        print(f"원본이 없습니다: {SOURCE}")
        return 1

    done = _done_ids(TARGET)
    todo = [r for r in rows if str(r.get("id", "")) not in done]
    chars = sum(len(str(r.get("answer", ""))) for r in todo)
    print(f"전체 {len(rows)} / 완료 {len(done)} / 남음 {len(todo)} ({chars:,}자)")

    if args.dry_run:
        in_tok = chars / 1.5
        print(f"추정 입력 토큰 {int(in_tok):,} · 출력 토큰 {int(in_tok * 1.1):,}")
        return 0
    if not todo:
        print("남은 작업이 없습니다.")
        return 0

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY 가 없습니다.")
        return 1

    try:
        from anthropic import Anthropic
    except ImportError:
        print("pip install anthropic 이 필요합니다.")
        return 1

    client = Anthropic(api_key=api_key)
    batch = todo[: args.limit] if args.limit > 0 else todo

    # 한 건씩 append 로 쓴다 — 중간에 끊겨도 그때까지가 남고 다음 실행이 이어받는다.
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with TARGET.open("a", encoding="utf-8") as out:
        for index, row in enumerate(batch, 1):
            answer = str(row.get("answer", "")).strip()
            concern = str(row.get("target_concern", "")).strip()
            if not answer:
                continue
            try:
                message = client.messages.create(
                    model=args.model,
                    max_tokens=1500,
                    system=SYSTEM,
                    messages=[{
                        "role": "user",
                        "content": f"肌悩みの分類: {concern}\n\n本文:\n{answer}",
                    }],
                )
                translated = "".join(
                    block.text for block in message.content if getattr(block, "type", "") == "text"
                ).strip()
            except Exception as exc:  # 네트워크·레이트리밋 등 — 건너뛰고 다음 실행에서 재시도
                print(f"  [{index}/{len(batch)}] id={row.get('id')} 실패: {exc}", file=sys.stderr)
                time.sleep(2)
                continue
            if not translated:
                continue
            out.write(json.dumps({
                "id": row.get("id"),
                "target_concern": _CONCERN_JA.get(concern, concern),
                "answer": translated,
            }, ensure_ascii=False) + "\n")
            out.flush()
            written += 1
            if index % 25 == 0:
                print(f"  {index}/{len(batch)} 진행")

    print(f"완료: {written}건 추가 → {TARGET}")
    return 0


# target_concern 은 8종뿐이라 사람이 정해 둔다(매번 번역하면 표기가 흔들린다).
_CONCERN_JA = {
    "미백(색소침착/기미/칙칙함)": "美白（色素沈着・シミ・くすみ）",
    "모공": "毛穴",
    "주름": "シワ",
    "여드름/뾰루지": "ニキビ・吹き出物",
    "붉어짐(홍조)": "赤み（紅潮）",
    "과각질/악건성": "角質肥厚・極度の乾燥",
    "피부처짐/탄력저하": "たるみ・ハリ低下",
    "민감성(트러블/자극감)": "敏感肌（トラブル・刺激感）",
}


if __name__ == "__main__":
    raise SystemExit(main())

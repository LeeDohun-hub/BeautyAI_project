"""성분 지식 코퍼스(한국어)를 일본어로 번역해 `*.ja.jsonl` 을 만든다.

왜 별도 파일인가
  원본을 건드리지 않는다. 한국어 코퍼스 재생성과 번역 작업이 서로를 막지 않고,
  번역이 없는 레코드는 일본어 모드에서 그냥 문단이 빠진다(한국어가 새지 않는다).
  붙이는 키는 레코드 `id` 다 — skincare_ingredient_knowledge._ja_answers() 가 그 키로 찾는다.

규모(2026-08-06 실측)
  8,341 레코드 / 번역 대상 약 306만 자.
  한 번에 다 돌리지 않아도 되게 **재개 가능**하게 만들었다 — 이미 번역된 id 는 건너뛴다.

사용
  # 키·모델은 백엔드 설정(.env 의 OPENAI_API_KEY / OPENAI_MODEL)을 그대로 쓴다 —
  # 이 저장소의 다른 LLM 호출(llm_consult)과 같은 자격증명·모델을 보게 하기 위해서다.
  python scripts/translate_ingredient_knowledge_ja.py --limit 50      # 맛보기
  python scripts/translate_ingredient_knowledge_ja.py                 # 전체(재개)
  python scripts/translate_ingredient_knowledge_ja.py --dry-run       # 비용만 추정

⚠ 유료 API 를 호출한다. --dry-run 으로 먼저 규모를 확인할 것.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "rag" / "skincare_ingredient_knowledge.jsonl"
TARGET = ROOT / "data" / "rag" / "skincare_ingredient_knowledge.ja.jsonl"

# 의학 인접 문구라 의미를 바꾸지 않는 것이 최우선이다. 성분명은 일본에서 통용되는 표기로
# 옮기되(예: 나이아신아마이드 → ナイアシンアミド), 확신이 없으면 원문을 괄호로 병기하게 한다.
SYSTEM = """あなたは化粧品・皮膚科学の専門翻訳者です。韓国語の肌悩みアドバイスを日本語に翻訳します。

規則:
- 意味を変えない。断定を強めたり、効能を誇張しない。
- 成分名は日本の化粧品表示で一般的な表記にする。確信が持てない場合のみ、日本語表記の後に
  英語（INCI）名を括弧で併記する。例: ゴボウ根エキス（Arctium Lappa Root Extract）
- 韓国語は一文字も残さない。括弧の中にも韓国語を書かない。
- 「〜します」「〜です」の丁寧体で、簡潔に。
- 医療行為を勧める表現にしない。原文が「相談を検討」ならその強さを保つ。
- 出力は翻訳文のみ。前置き・後書き・引用符を付けない。"""


_HANGUL = re.compile(r"[가-힣]")
# 한국어만 든 괄호(성분명 병기). 프롬프트가 금지했는데도 드물게 나온다(실측 5,672건 중 1건).
_KOREAN_PAREN = re.compile(r"\s*[（(][^）)]*[가-힣][^）)]*[）)]")


# 기다려도 안 풀리는 오류. 429 라고 다 같은 429 가 아니다 — 레이트리밋은 재시도할 값이지만
# 크레딧 소진·인증 실패는 재시도할수록 로그만 더럽고 시간만 버린다.
_FATAL_MARKERS = (
    "insufficient_quota",
    "credit_balance_exhausted",
    "no credits remaining",
    "invalid_api_key",
    "authentication",
)


def _is_fatal(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _FATAL_MARKERS)


def sanitize(text: str) -> str:
    """일본어 본문에 섞여 나온 한국어 괄호 병기를 떼어낸다.

    괄호 밖에 한국어가 남으면 번역이 실패한 것이므로 그대로 두고 호출부가 버린다 —
    반쯤 한국어인 문장을 일본 사용자에게 내보내지 않는다.
    """
    cleaned = _KOREAN_PAREN.sub("", text)
    return "" if _HANGUL.search(cleaned) else cleaned


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
    parser.add_argument("--model", default="", help="비우면 백엔드 설정의 openai_model")
    parser.add_argument("--workers", type=int, default=8, help="동시 요청 수(레이트리밋에 맞춰 조절)")
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

    sys.path.insert(0, str(ROOT / "backend"))
    from app.core.config import get_settings  # noqa: E402

    settings = get_settings()
    api_key = settings.openai_api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY 가 없습니다(.env 확인).")
        return 1
    model = args.model or settings.openai_model

    try:
        from openai import OpenAI
    except ImportError:
        print("pip install openai 가 필요합니다.")
        return 1

    client = OpenAI(api_key=api_key)
    batch = todo[: args.limit] if args.limit > 0 else todo
    print(f"모델 {model} · 이번 실행 {len(batch)}건")

    _abort = threading.Event()

    def translate(row: dict) -> dict | None:
        """한 건 번역. 일시 오류는 백오프 후 재시도, 회복 불가 오류는 전체 중단."""
        if _abort.is_set():
            return None
        answer = str(row.get("answer", "")).strip()
        concern = str(row.get("target_concern", "")).strip()
        if not answer:
            return None
        for attempt in range(4):
            try:
                completion = client.chat.completions.create(
                    model=model,
                    max_tokens=1500,
                    temperature=0.2,  # 번역이라 창의성이 필요 없다. 표기 흔들림을 줄인다.
                    messages=[
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": f"肌悩みの分類: {concern}\n\n本文:\n{answer}"},
                    ],
                )
                translated = sanitize((completion.choices[0].message.content or "").strip())
                if not translated:
                    return None
                return {
                    "id": row.get("id"),
                    "target_concern": _CONCERN_JA.get(concern, concern),
                    "answer": translated,
                }
            except Exception as exc:
                # ⚠ 크레딧 소진·인증 오류는 **기다려도 안 풀린다.** 429 라는 이유로 재시도하면
                #   남은 수천 건이 각각 4번씩 헛돌고(실측 450+회) 진짜 원인이 로그에 묻힌다.
                #   이런 건 즉시 전체를 멈춘다 — 크레딧을 채우고 다시 실행하면 이어받는다.
                if _is_fatal(exc):
                    _abort.set()
                    print(f"\n중단: {exc}", file=sys.stderr)
                    return None
                if _abort.is_set():
                    return None
                if attempt == 3:
                    # 남겨두면 다음 실행이 이어받는다(이 id 는 파일에 안 써지므로 미완료로 남는다).
                    print(f"  id={row.get('id')} 포기: {exc}", file=sys.stderr)
                    return None
                # 지수 백오프 + 지터. 동시 요청이 한꺼번에 재시도해 다시 429 를 맞는 걸 막는다.
                time.sleep((2 ** attempt) + random.uniform(0, 1))
        return None

    # 한 건씩 append 로 쓴다 — 중간에 끊겨도 그때까지가 남고 다음 실행이 이어받는다.
    # 쓰기는 락으로 직렬화한다(여러 스레드가 같은 파일에 쓰면 줄이 섞인다).
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    done_count = 0
    lock = threading.Lock()
    started = time.time()

    with TARGET.open("a", encoding="utf-8") as out:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(translate, row): row for row in batch}
            for future in as_completed(futures):
                record = future.result()
                with lock:
                    done_count += 1
                    if record:
                        out.write(json.dumps(record, ensure_ascii=False) + "\n")
                        out.flush()
                        written += 1
                    if done_count % 100 == 0 or done_count == len(batch):
                        rate = done_count / max(1e-9, time.time() - started)
                        left = (len(batch) - done_count) / rate if rate else 0
                        print(
                            f"  {done_count}/{len(batch)} 완료 (성공 {written}) "
                            f"· {rate:.1f}건/초 · 남은 시간 약 {left / 60:.0f}분",
                            flush=True,
                        )

    elapsed = time.time() - started
    print(f"완료: {written}건 추가 ({elapsed / 60:.1f}분) → {TARGET}")
    if written < len(batch):
        print(f"실패 {len(batch) - written}건은 파일에 없으므로 다시 실행하면 이어서 시도한다.")
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

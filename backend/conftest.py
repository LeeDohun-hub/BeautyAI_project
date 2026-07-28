"""리포지토리 루트에서 pytest 를 돌려도 `app` 패키지를 찾도록 sys.path 를 보정한다.

CI(.github/workflows/ci.yml)는 루트에서 `pytest backend` 로 실행하는데, backend/ 가
sys.path 에 없어 전 테스트가 수집 단계에서 `ModuleNotFoundError: No module named 'app'`
로 죽고 있었다. requirements.txt 에 editable 설치가 없어 CI 에서도 동일하게 실패한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

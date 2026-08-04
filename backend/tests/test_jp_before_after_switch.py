"""일본 비포/애프터 제어 스위치.

일본 医療広告ガイドライン 은 시술 전후 사진에 시술 내용·비용·주요 위험을 병기하도록
요구한다. 병원 연결이 붙으면 가상 성형 미리보기가 그 규제에 걸릴 수 있어, 일본어 화면에서
나란히 놓기를 끌 수 있어야 한다(docs/medical_ad_working_assumptions.md 전제 4).

**지금은 켜 둔 채로 둔다.** 병원 연결 전에는 의료광고 주체가 아니라는 해석이 성립하고,
회신 전에 기능을 미리 줄일 이유가 없다. 이 항목의 목적은 '필요할 때 즉시 끌 수 있게'다.

만들어만 두고 안 도는 스위치는 없느니만 못하므로 여기서 검사한다.
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    # conftest 에 공용 client 가 없어 파일마다 만든다(test_web_account_link.py 와 같은 방식).
    with TestClient(app) as test_client:
        yield test_client


def test_default_is_on_so_current_behaviour_is_unchanged() -> None:
    """기본값이 False 로 바뀌면 일본 사용자 화면이 조용히 달라진다."""
    assert Settings(jp_before_after=True).jp_before_after is True
    # 명시하지 않았을 때의 기본값도 확인 — .env 가 없는 환경 기준.
    assert Settings(_env_file=None).jp_before_after is True  # type: ignore[call-arg]


def test_config_endpoint_exposes_the_switch(client: TestClient) -> None:
    """프론트가 이 값을 못 받으면 스위치를 내려도 화면이 안 바뀐다."""
    res = client.get("/api/auth/config")
    assert res.status_code == 200
    assert "jp_before_after" in res.json()


def test_switch_can_be_turned_off_by_environment(monkeypatch) -> None:
    """운영에서 **재배포 없이** 끌 수 있어야 한다 — 회신이 오면 급히 내려야 할 수 있다."""
    monkeypatch.setenv("JP_BEFORE_AFTER", "false")
    assert Settings().jp_before_after is False


def test_frontend_reads_the_switch() -> None:
    """스위치를 화면이 실제로 본다. 백엔드만 있고 배선이 없으면 아무 일도 안 일어난다
    (오늘 삭제 API 를 화면 없이 만든 것과 같은 실수)."""
    from pathlib import Path

    app_tsx = Path(__file__).resolve().parents[2] / "frontend" / "src" / "App.tsx"
    source = app_tsx.read_text(encoding="utf-8")
    assert "jp_before_after" in source, "프론트가 이 값을 읽지 않습니다"
    assert "hideBeforeAfter" in source, "끄는 분기가 없습니다"

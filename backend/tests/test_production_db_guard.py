"""운영 DB 가드 — 로컬 개발이 운영 DB 를 치는 사고를 막는 장치.

왜 테스트를 두는가: 이 가드는 **평소에 아무 일도 하지 않는다.** 조용히 죽어 있어도
아무도 모르고, 알게 되는 순간은 이미 운영 데이터를 건드린 뒤다.
(2026-08-03: .env 와 .env.prod 의 DATABASE_URL 이 글자 하나까지 같은 걸 발견해 만들었다.)
"""

import pytest

from app.core import database
from app.core.config import Settings

PROD_URL = "postgresql://postgres.ekmelstemgzjbjppoalg:pw@aws-1-ap-southeast-2.pooler.supabase.com:5432/postgres"
DEV_URL = "postgresql://postgres.someotherproject:pw@aws-1-ap-southeast-2.pooler.supabase.com:5432/postgres"


def _guard_with(monkeypatch: pytest.MonkeyPatch, url: str, **overrides: object) -> None:
    # ⚠️ 두 값은 **반드시 명시**한다. Settings 는 개발자 로컬 .env 를 읽으므로,
    # 비워두면 그 기계의 ALLOW_PRODUCTION_DB=true 가 새어 들어와 테스트가 조용히 통과한다
    # (실제로 그렇게 통과했다). 테스트 결과가 기계 설정에 좌우되면 안 된다.
    overrides.setdefault("app_env", "local")
    overrides.setdefault("allow_production_db", False)
    settings = Settings(**{"database_url": url, **overrides})  # type: ignore[arg-type]
    monkeypatch.setattr(database, "settings", settings)
    database.guard_production_db(url)


def test_local_pointing_at_production_db_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(RuntimeError) as exc:
        _guard_with(monkeypatch, PROD_URL, app_env="local")
    # 메시지가 '무엇을 하면 되는지' 를 담고 있어야 한다 — 막기만 하면 결국 가드를 지운다.
    assert "ALLOW_PRODUCTION_DB" in str(exc.value)
    assert "APP_ENV" in str(exc.value)


def test_production_container_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    # 운영에서 이게 막히면 서비스가 통째로 안 뜬다.
    _guard_with(monkeypatch, PROD_URL, app_env="production")


def test_explicit_opt_in_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    _guard_with(monkeypatch, PROD_URL, app_env="local", allow_production_db=True)


@pytest.mark.parametrize("url", [DEV_URL, "sqlite:///./beautyai.db"])
def test_non_production_urls_pass(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    _guard_with(monkeypatch, url, app_env="local")


def test_marker_must_be_kept_in_sync_with_real_prod_url() -> None:
    """마커가 비면 가드가 전부 통과한다 — 그 상태를 테스트로 붙잡는다."""
    assert Settings().production_db_marker.strip(), "production_db_marker 가 비면 가드가 무력화된다"


def test_prod_compose_sets_app_env() -> None:
    """운영 컴포즈에서 APP_ENV 가 빠지면 **운영이 부팅을 거부한다.**

    가드를 넣으면서 같이 넣은 값이라, 누가 환경변수를 정리하다 지우면 서비스가 죽는다.
    """
    from pathlib import Path

    compose = Path(__file__).resolve().parents[2] / "docker-compose.prod.yml"
    assert "APP_ENV: production" in compose.read_text(encoding="utf-8"), (
        "docker-compose.prod.yml 에 APP_ENV: production 이 없으면 백엔드가 안 뜬다"
    )

"""준비 상태(/ready) 회귀 테스트(2026-07-30).

배경: 워밍(카탈로그·모델 로딩 ≈20초)이 끝나기 전에도 /health 가 200 이라, 컨테이너가
healthy 로 뜨고 첫 사용자가 30초를 기다렸다. 생존(liveness)과 준비(readiness)를 분리한다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture()
def client():
    # lifespan 을 돌리면 seed/워밍이 실행되므로 앱만 그대로 쓴다(엔드포인트 자체 검증이 목적).
    return TestClient(main.app)


def test_health_is_always_ok_even_while_warming(client):
    """생존 확인은 워밍 중에도 200 이어야 한다 — 아니면 오케스트레이터가 계속 재시작한다."""
    main._warm_done.clear()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_is_503_while_warming(client):
    main._warm_done.clear()
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "warming"


def test_ready_is_200_after_warmup(client):
    main._warm_done.set()
    try:
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"
    finally:
        main._warm_done.clear()


def test_warmup_failure_still_sets_ready(monkeypatch):
    """워밍이 실패해도 준비 신호는 세워야 한다 — 아니면 /ready 가 영원히 503 이라 배포가 멈춘다."""
    main._warm_done.clear()

    def boom(*_args, **_kwargs):
        raise RuntimeError("catalog load failed")

    monkeypatch.setattr(main, "SessionLocal", boom)
    main._warm_caches()
    assert main._warm_done.is_set()
    main._warm_done.clear()

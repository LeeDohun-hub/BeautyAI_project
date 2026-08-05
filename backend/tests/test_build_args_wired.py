"""Vite 빌드 인자가 운영 compose 에 배선돼 있는지 검사한다.

왜 필요한가(2026-08-04 사용자 제보): 운영 ai.yopalette.com 의 'YoPalette 홈으로 이동'
버튼이 **localhost:5175** 를 가리키고 있었다.

원인은 코드가 아니라 **빌드 인자 누락**이다. Vite 는 import.meta.env 를 **빌드 시점에**
치환하므로, 컨테이너 환경변수로는 바꿀 수 없다. 인자를 안 주면 코드의 로컬 기본값
(`|| 'http://localhost:5174'`)이 그대로 번들에 구워진다.

이 부류는 **화면을 열어 눌러 보기 전에는 드러나지 않는다** — 빌드도 배포도 테스트도
전부 통과한다. 그래서 여기서 잡는다.

⚠ 2026-08-05: compose 만 검사했더니 이 테스트가 통과하는데도 증상이 그대로였다.
Docker 는 **Dockerfile 에 ARG 로 선언되지 않은 build arg 를 경고만 남기고 버린다.**
그래서 compose 의 args 와 Dockerfile 의 ARG **둘 다** 있어야 값이 실제로 전달된다.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "frontend" / "src" / "App.tsx"
COMPOSE = ROOT / "docker-compose.prod.yml"
DOCKERFILE = ROOT / "frontend" / "Dockerfile.prod"


def _env_keys_with_local_default() -> set[str]:
    """`import.meta.env.VITE_X || 'http://localhost…'` 형태를 찾는다.

    로컬 기본값이 있는 것만 본다 — 기본값이 없으면 빌드가 빈 값을 쓰므로
    '로컬 주소가 구워지는' 사고가 안 난다.
    """
    source = APP.read_text(encoding="utf-8")
    # ⚠ 실제 코드는 캐스팅과 괄호가 붙는다:
    #     (import.meta.env.VITE_X as string | undefined) || 'http://localhost:5174'
    #   처음에 `[^|\n]*` 로 썼더니 ' | undefined' 의 파이프에 걸려 한 건도 못 잡았다.
    #   정규식이 0건이면 검사가 조용히 통과하므로, 아래 하한 테스트가 그것을 잡는다.
    pattern = re.compile(
        r"import\.meta\.env\.(VITE_[A-Z0-9_]+)[\s\S]{0,60}?\|\|\s*'(https?://(?:localhost|127\.0\.0\.1)[^']*)'"
    )
    return {m.group(1) for m in pattern.finditer(source)}


LOCAL_DEFAULTED = sorted(_env_keys_with_local_default())


def test_there_are_such_keys() -> None:
    """패턴이 안 맞으면 아래 검사가 조용히 아무것도 안 한다(0건 통과)."""
    assert LOCAL_DEFAULTED, "로컬 기본값을 가진 VITE 키를 하나도 못 찾았습니다 — 정규식 확인"


@pytest.mark.parametrize("key", LOCAL_DEFAULTED)
def test_local_defaulted_env_is_passed_at_build_time(key: str) -> None:
    """운영 compose 의 build.args 에 있어야 한다. 없으면 localhost 가 구워진다."""
    compose = COMPOSE.read_text(encoding="utf-8")
    assert f"{key}:" in compose, (
        f"{key} 가 docker-compose.prod.yml 의 build args 에 없습니다.\n"
        "  Vite 는 빌드 시점에 치환하므로 런타임 환경변수로는 못 고칩니다 —\n"
        "  인자를 안 주면 코드의 로컬 기본값(localhost)이 번들에 그대로 구워집니다."
    )


@pytest.mark.parametrize("key", LOCAL_DEFAULTED)
def test_local_defaulted_env_is_declared_in_dockerfile(key: str) -> None:
    """Dockerfile 에도 ARG 로 선언돼야 한다.

    compose 에만 적고 여기를 빼면 Docker 가 그 인자를 **조용히 버린다**(경고뿐).
    빌드는 성공하고 배포도 성공하는데 번들에는 localhost 가 들어간다 — 실제 사고 경로다.
    ENV 까지 있어야 `npm run build` 단계의 Vite 가 값을 본다.
    """
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(rf"^\s*ARG\s+{key}\b", dockerfile, re.MULTILINE), (
        f"{key} 가 frontend/Dockerfile.prod 에 ARG 로 선언돼 있지 않습니다.\n"
        "  compose 의 build args 만으로는 전달되지 않습니다 — Docker 가 버립니다."
    )
    assert re.search(rf"^\s*ENV\s+{key}=", dockerfile, re.MULTILINE), (
        f"{key} 가 frontend/Dockerfile.prod 에 ENV 로 노출돼 있지 않습니다.\n"
        "  ARG 만 있으면 RUN npm run build 안의 Vite 가 값을 보지 못합니다."
    )

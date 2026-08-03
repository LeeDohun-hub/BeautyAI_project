#!/usr/bin/env bash
# EC2 에 GitHub Actions self-hosted 러너를 설치하고 서비스로 등록한다.
#
# 왜 self-hosted 인가: GitHub 호스팅 러너는 우리 EC2 에 SSH 로 못 들어온다(보안그룹이
# 22번을 특정 IP 로 제한 — 실측으로 러너 접속 시도가 sshd 로그에 아예 안 남았다).
# 러너를 서버 안에 두면 **바깥으로** 접속해 작업을 받아오므로 인바운드 구멍이 필요 없고,
# S3·GHCR·SSH 키 같은 준비물도 전부 사라진다.
#
# 사용법(서버에서):
#   bash install_github_runner.sh <저장소URL> <등록토큰> [설치경로]
#
# 등록 토큰은 GitHub 저장소 → Settings → Actions → Runners → "New self-hosted runner"
# 화면에 나오는 `--token` 값이다. **1시간이면 만료**되므로 받은 직후 실행할 것.
#
# 예:
#   bash install_github_runner.sh https://github.com/LeeDohun-hub/BeautyAI_project AXXXX...
set -euo pipefail

REPO_URL="${1:-}"
TOKEN="${2:-}"
RUNNER_DIR="${3:-$HOME/actions-runner}"

if [ -z "$REPO_URL" ] || [ -z "$TOKEN" ]; then
  echo "사용법: bash $0 <저장소URL> <등록토큰> [설치경로]" >&2
  exit 1
fi

if [ -d "$RUNNER_DIR" ] && [ -f "$RUNNER_DIR/.runner" ]; then
  echo "이미 러너가 설정돼 있습니다: $RUNNER_DIR"
  echo "다시 설치하려면 먼저 제거하세요:"
  echo "  cd $RUNNER_DIR && sudo ./svc.sh stop && sudo ./svc.sh uninstall && ./config.sh remove --token <제거토큰>"
  exit 1
fi

# 러너는 docker 를 호출한다. 지금 사용자가 docker 그룹에 있어야 sudo 없이 동작한다.
if ! docker ps >/dev/null 2>&1; then
  echo "!! 현재 사용자($(whoami))가 docker 를 못 씁니다. 아래 실행 후 재로그인하세요:" >&2
  echo "   sudo usermod -aG docker $(whoami)" >&2
  exit 1
fi

mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"

if [ ! -f ./config.sh ]; then
  # 최신 버전을 조회해 받는다(버전을 박아두면 몇 달 뒤 설치가 깨진다).
  # ⚠ `curl ... | grep -m1` 로 쓰면 안 된다 — grep 이 첫 매치 후 파이프를 닫아 curl 이
  #   SIGPIPE(exit 23)로 죽고, `set -o pipefail` 때문에 스크립트가 통째로 중단된다(실측).
  #   응답을 변수에 먼저 담고 나서 파싱한다.
  RELEASE_JSON=$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest)
  VERSION=$(printf '%s\n' "$RELEASE_JSON" | grep -m1 '"tag_name"' | sed -E 's/.*"v([^"]+)".*/\1/')
  [ -n "$VERSION" ] || { echo "러너 최신 버전을 알아내지 못했습니다" >&2; exit 1; }
  echo "러너 v$VERSION 내려받는 중..."
  curl -fsSL -o runner.tar.gz \
    "https://github.com/actions/runner/releases/download/v${VERSION}/actions-runner-linux-x64-${VERSION}.tar.gz"
  tar xzf runner.tar.gz && rm runner.tar.gz
fi

# --unattended: 대화형 질문 없이 진행. --replace: 같은 이름 러너가 있으면 교체.
# 라벨에 호스트명을 넣어 어느 서버인지 Actions 화면에서 구분되게 한다.
./config.sh --unattended --replace \
  --url "$REPO_URL" \
  --token "$TOKEN" \
  --name "$(hostname)" \
  --labels "self-hosted,Linux,X64,$(hostname)" \
  --work _work

sudo ./svc.sh install "$(whoami)"
sudo ./svc.sh start

echo
echo "완료 — 상태:"
sudo ./svc.sh status | head -5
echo
echo "GitHub 의 Settings → Actions → Runners 에서 'Idle' 로 보이면 정상입니다."

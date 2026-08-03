# 자동배포 켜기 — 클릭 순서대로

브라우저 옆에 띄워놓고 위에서부터 그대로 따라가면 된다.
설계 배경은 [CD_SETUP.md](CD_SETUP.md) 참조.

**준비물이 거의 없다.** 서버 안에 GitHub 러너를 두는 방식이라 S3·IAM 키·GHCR 토큰·SSH 키가
전부 필요 없다. 저장소마다 **등록 토큰 한 번 + 변수 한 개**가 전부다.

각 저장소에 대해 같은 4단계를 반복한다. WEB 부터 하면 10분이면 끝난다.

---

# PART 0. WEB 저장소를 private 으로 (WEB 만, 처음 한 번)

self-hosted 러너는 워크플로 코드를 **우리 서버에서 실행**한다. 저장소가 public 이면
아무나 PR 을 올려 서버에서 임의 코드를 돌릴 수 있다(GitHub 공식 경고).

1. **https://github.com/LeeDohun-hub/BeautyWEB_project/settings**
2. 페이지 **맨 아래** `Danger Zone` → **Change repository visibility** → **Change visibility**
3. `Make private` 선택 → 저장소 이름을 입력해 확인

---

# PART 1. 러너 설치 (저장소마다 1회)

## 1-1. 등록 토큰 받기

1. **WEB**: https://github.com/LeeDohun-hub/BeautyWEB_project/settings/actions/runners
   **AI**: https://github.com/LeeDohun-hub/BeautyAI_project/settings/actions/runners
   (저장소 **Settings** → 왼쪽 **Actions** → **Runners**)
2. 오른쪽 위 **New self-hosted runner**
3. 운영체제 **Linux**, 아키텍처 **x64** 선택
4. 화면 중간 `Configure` 항목의 명령에서 `--token` 뒤의 값을 복사한다.
   `AAAAA...` 형태의 긴 문자열이다.

> **1시간이면 만료된다.** 받은 직후 1-2 를 진행할 것. 만료됐으면 이 화면을 새로고침해 다시 받으면 된다.

## 1-2. 서버에서 설치 명령 실행

로컬 PowerShell 에서 서버에 접속한다. **WEB 과 AI 는 서버도 키도 다르다.**

```powershell
# WEB
ssh -i C:\WorkSpace\Beauty_Project\YoPalette.pem ubuntu@www.yopalette.com

# AI
ssh -i C:\WorkSpace\Beauty_Project\YoPalAI.pem ubuntu@ai.yopalette.com
```

접속된 뒤(서버 안에서) — `<토큰>` 자리에 1-1 에서 복사한 값을 넣는다:

```bash
# WEB 서버에서
curl -fsSL https://raw.githubusercontent.com/LeeDohun-hub/BeautyAI_project/main/scripts/install_github_runner.sh -o /tmp/install_runner.sh
bash /tmp/install_runner.sh https://github.com/LeeDohun-hub/BeautyWEB_project <토큰>

# AI 서버에서
curl -fsSL https://raw.githubusercontent.com/LeeDohun-hub/BeautyAI_project/main/scripts/install_github_runner.sh -o /tmp/install_runner.sh
bash /tmp/install_runner.sh https://github.com/LeeDohun-hub/BeautyAI_project <토큰>
```

> AI 저장소는 private 이라 위 `curl` 이 404 가 난다. 그때는 스크립트를 로컬에서 올린다:
> ```powershell
> scp -i C:\WorkSpace\Beauty_Project\YoPalAI.pem `
>   C:\WorkSpace\Beauty_Project\BeautyAI_project\scripts\install_github_runner.sh `
>   ubuntu@ai.yopalette.com:/tmp/install_runner.sh
> ```
> WEB 도 private 으로 바꾼 뒤에는 같은 방법을 쓴다.

`완료 — 상태:` 와 `Active: active (running)` 이 보이면 성공이다.

## 1-3. 러너가 붙었는지 확인

1-1 의 Runners 화면을 새로고침한다. 서버 호스트명이 **Idle** 상태로 보이면 정상이다.

---

# PART 2. 변수 등록 (저장소마다 1회)

1. **WEB**: https://github.com/LeeDohun-hub/BeautyWEB_project/settings/variables/actions
   **AI**: https://github.com/LeeDohun-hub/BeautyAI_project/settings/variables/actions
   (Settings → **Secrets and variables** → **Actions** → 위쪽 **Variables** 탭)
2. **New repository variable**

| Name | Value |
|---|---|
| `DEPLOY_BRANCH` | `main` |

> 이걸 안 만들면 배포 잡이 **항상 회색으로 건너뛰어진다**(실수 배포 방지 장치).
> 즉 여기까지 안 하면 아무 일도 일어나지 않는다.

---

# PART 3. production 환경 만들기 (저장소마다 1회)

1. **Settings** → 왼쪽 사이드바 **Environments** → **New environment**
2. 이름 `production` → **Configure environment**
3. 아무것도 건드리지 말고 나오면 된다.

> 나중에 이 화면에서 **Required reviewers** 를 켜면, 워크플로를 고치지 않고도
> "푸시하면 대기 → 승인 눌러야 배포" 로 바뀐다.

---

# PART 4. 돌려보기

1. 저장소 **Actions** 탭
2. 왼쪽 목록에서 **Deploy WEB**(또는 **Deploy AI**) 클릭
3. 오른쪽 **Run workflow** ▾ → 브랜치 `main` → **Run workflow**
4. 새 실행을 클릭해 로그를 본다.

성공 신호:
- WEB: `backend OK`
- AI: `ready OK` (첫 실행은 이미지 재빌드라 오래 걸릴 수 있다)

여기까지 되면 **이제부터 `main` 에 푸시할 때마다 CI 통과 후 자동 배포된다.**

---

# 알아둘 것

**런타임 번들은 자동으로 갱신되지 않는다.** AI 의 `dist/runtime_data`(모델·매니페스트
373MB)는 git 에 없어서 배포가 건드리지 못한다. 모델을 바꾸거나 크롤을 새로 돌렸으면
로컬에서 만들어 서버로 올려야 한다:

```powershell
cd C:\WorkSpace\Beauty_Project\BeautyAI_project
python scripts\build_runtime_bundle.py
scp -i C:\WorkSpace\Beauty_Project\YoPalAI.pem -r dist\runtime_data ubuntu@ai.yopalette.com:/home/ubuntu/BeautyAI_project/dist/
```

배포 로그의 `번들 최신 파일: <날짜>` 로 낡았는지 확인할 수 있다.

**CI 는 GitHub 러너에서 돈다**(서버 자원을 쓰지 않게). 두 저장소가 private 이므로
Actions 분이 과금 대상(무료 2,000분/월)이다. AI 의 `ci.yml` `images` 잡이 매 push 마다
torch 이미지를 빌드해 분을 크게 쓰므로, 부족해지면 그 잡부터 좁힐 것.

---

# 막혔을 때

| 증상 | 원인 |
|---|---|
| 배포 잡이 **회색으로 건너뜀** | `DEPLOY_BRANCH` 변수가 없거나 `main` 이 아니다 |
| 실행이 **노란색으로 계속 대기** | 러너가 죽어 있다. 서버에서 `cd ~/actions-runner && sudo ./svc.sh status` |
| `Runner ... is offline` | 같은 명령으로 상태 확인 → `sudo ./svc.sh start` |
| `$DEPLOY_DIR 가 없습니다` | 서버의 배포 디렉터리 경로가 다르다. 워크플로 `env.DEPLOY_DIR` 확인 |
| `permission denied ... docker.sock` | 러너 사용자가 docker 그룹에 없다. `sudo usermod -aG docker ubuntu` 후 러너 재시작 |
| 배포는 성공인데 화면이 안 바뀜 | compose 프로젝트명 불일치로 **두 번째 스택**이 떴을 때 나온다. 서버에서 `docker compose ls` 확인 |
| 등록 토큰이 `invalid` | 1시간 만료. Runners 화면을 새로고침해 새 토큰을 받는다 |

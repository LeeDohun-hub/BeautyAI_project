# 자동배포(CD) 설계 — AI · WEB

> **켜는 절차는 [CD_SETUP_STEPS.md](CD_SETUP_STEPS.md).** 이 문서는 왜 이렇게 만들었는지다.

`git push` → CI(GitHub 러너) 통과 → **서버 안의 self-hosted 러너**가 재빌드·재기동.

| | AI (`BeautyAI_project`) | WEB (`BeautyWEB_project`) |
|---|---|---|
| 호스트 | `ai.yopalette.com` | `www.yopalette.com` (**다른 인스턴스**) |
| SSH 키 | `YoPalAI.pem` | `YoPalette.pem` (다른 키) |
| 디렉터리 | `/home/ubuntu/BeautyAI_project` | `/home/ubuntu/BeautyWEB_project` |
| compose 프로젝트명 | `beautyai_project` | `beautyweb_project` |
| compose 파일 | `docker-compose.prod.yml` | `docker-compose.aws.yml` (+`--profile local-db`) |
| env | `.env.prod` | `.env` (`BACKEND_PORT=8082`) |
| 사양 | 4코어 / 15GB / 96GB | 2코어 / 3GB / 48GB |

---

## 왜 self-hosted 러너인가

**GitHub 호스팅 러너는 우리 EC2 에 들어올 수 없다.** 보안그룹(`launch-wizard-7`)이 22번을
특정 IP 로 제한하고 있어서, SSH 방식으로 짠 첫 배포는 39초 만에 실패했다. 서버의 sshd
로그를 봤더니 **러너의 접속 시도가 아예 남아 있지 않았다**(도달조차 못 함).

선택지는 셋이었다.
1. 22번을 `0.0.0.0/0` 으로 개방 — SSH 를 인터넷에 노출한다.
2. GitHub 러너 IP 대역만 허용 — 대역이 수천 개라 보안그룹 규칙 한도를 넘는다.
3. **서버 안에 러너를 둔다** — 러너가 GitHub 로 **바깥으로** 접속해 작업을 받아온다.
   인바운드 구멍이 필요 없다.

3번을 골랐고, 덤으로 준비물이 통째로 사라졌다: **S3 버킷·IAM 키·GHCR 토큰·SSH 키가 전부 불필요**하다.

### 처음엔 왜 S3+GHCR 로 짰었나 (기록)

"EC2 에서 torch 를 빌드하면 3.2GB·수 분이라 무리" 라고 판단해, 러너에서 이미지를 굽고
GHCR 로 보내는 구조를 짰다. 근거는 `DEPLOY_READY_CHECKLIST.md` 의 "backend image rebuild
did not finish within 15 minutes" 였는데 — **그건 로컬 PC 이야기였다.**

실제 서버를 보니 4코어·15GB 에 빌드 캐시 6.4GB 가 있고, 현재 돌고 있는
`beautyai_project-backend:latest`(4.54GB) 자체가 **서버에서 구운 것**이었다.
전제가 틀려서 준비물만 잔뜩 늘린 구조였다. 서버 사실관계를 먼저 확인했어야 했다.

---

## 동작 흐름

```
push → CI (GitHub 러너: pytest / 프론트 빌드 / 카탈로그 무결성)
         └─ 성공 + DEPLOY_BRANCH 일 때만 ─→ Deploy (서버 안 러너)
                                              rsync 체크아웃 → 배포 디렉터리
                                              docker compose up -d --build
                                              AI: /ready 확인 · WEB: /v1/api/items 확인
                                              dangling 이미지 정리
```

**왜 러너 작업공간이 아니라 배포 디렉터리에서 빌드하나**: 비밀값(`.env.prod`/`.env`)과
AI 런타임 번들(`dist/runtime_data`)이 거기에만 있고, **compose 프로젝트명이 디렉터리명에서
나오기 때문**이다. 다른 곳에서 띄우면 기존 스택을 갱신하는 대신 두 번째 스택이 뜨고,
Caddy 가 이미 80/443 을 잡고 있어 새 스택은 뜨다 말고 **서비스는 옛 버전 그대로 남는다**
(배포는 '성공'으로 끝나는 최악의 실패 모드 — 실제로 `-p beautyai_prod` 로 잘못 짜뒀다가 잡았다).

`rsync` 에 `--delete` 를 쓰지 않는 것도 같은 이유다. 저장소에 없고 서버에만 있는 것들
(`.env.prod`, `dist/runtime_data`, `beautyai.db`, 백업들)이 지워진다.

---

## 필요한 설정 (전부)

저장소마다:

| 종류 | 이름 | 값 |
|---|---|---|
| Variable | `DEPLOY_BRANCH` | `main` — **없으면 배포 잡이 항상 건너뛰어진다** |
| Environment | `production` | 빈 환경. 나중에 Required reviewers 로 승인제 전환 가능 |
| 러너 | self-hosted | 서버당 1개 (`scripts/install_github_runner.sh`) |

시크릿은 하나도 없다.

---

## 주의

- **self-hosted 러너는 워크플로 코드를 서버에서 실행한다** → 두 저장소 모두 **private** 이어야
  한다. public 이면 아무나 PR 로 서버에서 임의 코드를 돌릴 수 있다(GitHub 공식 경고).
- **런타임 번들은 자동 갱신되지 않는다.** `dist/runtime_data` 는 git 에 없다. 모델·매니페스트를
  바꿨으면 로컬에서 만들어 `scp` 로 올려야 한다. 안 하면 코드만 새로 배포되고 데이터는
  옛것이라 **에러 없이 커버리지만 떨어진다**(이 프로젝트에서 같은 부류로 두 번 당했다).
  배포 로그의 `번들 최신 파일: <날짜>` 로 확인할 수 있다.
- **CI 는 GitHub 러너에서 돈다**(서버 자원 보호). private 저장소라 Actions 분이 과금
  대상(무료 2,000분/월)이다. AI 의 `ci.yml` `images` 잡이 매 push 마다 torch 이미지를
  빌드해 분을 크게 쓴다 — 부족해지면 그 잡부터 좁힐 것.
- **BeautyWEB 로컬 `origin` 은 엉뚱한 저장소(`LeeDohun-hub/gallery.git`)를 가리킨다.**
  진짜 원격은 `beautyweb`. 로컬 푸시는 `git push beautyweb beautyweb-main:main`.
- apex `yopalette.com` 에 A 레코드가 없어서 WEB Caddyfile 의 apex 리다이렉트는 동작하지 않는다.
- `DEPLOY_READY_CHECKLIST.md` 는 Caddy 도입 **이전** 문서다("same Docker host" 서술 등) — 그대로 믿지 말 것.

# 자동배포(CD) 셋업 — AI · WEB

`git push` → CI 통과 → EC2 반영. 두 저장소가 **다른 방식**으로 배포된다.

| | AI (`BeautyAI_project`, private) | WEB (`BeautyWEB_project`, public) |
|---|---|---|
| 이미지 빌드 | GitHub 러너 | **EC2 서버에서** |
| 왜 | EC2 에서 torch 빌드는 3.2GB·수 분(로컬 15분 내 실패 기록). 게다가 373MB 런타임 번들이 git 에 없다 | 45MB 카탈로그를 작업트리에서 바인드 마운트하고, 프론트가 서버 `.env` 값을 빌드 인자로 굽는다 |
| 번들/데이터 | S3 → 러너 → 이미지에 COPY | git 에 포함 |
| 서버 동작 | `docker compose pull && up -d --no-build` | `git reset --hard && up -d --build` |
| 서버에 git 필요 | 아니오(compose·Caddyfile 만 scp) | 예(public 이라 인증 불필요) |

---

## 1. 한 번만 하는 준비

### 1-1. 런타임 번들을 S3 에 올린다 (AI)

AWS CLI 가 필요하다: `winget install Amazon.AWSCLI` → 새 터미널 → `aws configure`
(S3 쓰기 권한이 있는 키).

```powershell
cd C:\WorkSpace\Beauty_Project\BeautyAI_project
$env:RUNTIME_BUNDLE_S3_URI = "s3://<버킷>/runtime_data"
python scripts\publish_runtime_bundle.py --dry-run   # 무엇이 바뀌는지 먼저 확인
python scripts\publish_runtime_bundle.py             # 빌드 + 업로드
```

`publish_runtime_bundle.py` 는 번들 빌드와 업로드를 **한 명령으로 묶는다**. 이 파이프라인의
유일한 조용한 실패 모드가 **"모델·매니페스트를 바꿨는데 S3 재업로드를 잊는 것"** 이기
때문이다 — 코드는 정상 배포되는데 데이터만 옛것이라 에러 없이 커버리지만 떨어진다.

**모델이나 매니페스트를 바꿀 때마다 이걸 다시 해야 한다.** 코드만 바꿨으면 필요 없다.
(예: 올리브영/아마존 크롤을 새로 돌렸다 → 다시 올려야 배포에 반영된다.)
배포 로그에도 `번들 최신 파일: <날짜>` 가 찍히니, 낡았는지 거기서 눈으로 확인할 수 있다.

### 1-2. EC2 준비

```bash
# AI — compose 와 .env.prod 가 있을 디렉터리. 저장소 클론은 필요 없다.
mkdir -p ~/beautyai && cd ~/beautyai
# .env.prod 를 여기에 둔다(git 에 없는 파일).

# WEB — 저장소를 클론해 둔다(public 이라 자격증명 불필요).
git clone https://github.com/LeeDohun-hub/BeautyWEB_project.git ~/beautyweb
cd ~/beautyweb   # .env 를 여기에 둔다.

# 공용 네트워크(양쪽 스택이 붙는다)
docker network create beauty_stack || true
```

### 1-3. GHCR 이미지를 EC2 가 받을 수 있게 (AI)

AI 저장소가 private 이라 GHCR 패키지도 private 이다. `read:packages` 스코프만 가진
**클래식 PAT** 을 만들어 `GHCR_PULL_TOKEN` 시크릿에 넣는다.

---

## 2. GitHub Secrets / Variables

### BeautyAI_project

| 종류 | 이름 | 값 |
|---|---|---|
| Variable | `DEPLOY_BRANCH` | 배포할 브랜치명 (예: `main`) |
| Secret | `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | S3 읽기 권한만 있는 IAM 사용자 |
| Secret | `AWS_REGION` | 예: `ap-northeast-2` |
| Secret | `RUNTIME_BUNDLE_S3_URI` | `s3://<버킷>/runtime_data` |
| Secret | `DEPLOY_HOST` | **AI 인스턴스**의 퍼블릭 IP(Elastic IP) 또는 도메인 |
| Secret | `DEPLOY_USER` | 예: `ubuntu` / `ec2-user` |
| Secret | `DEPLOY_SSH_KEY` | `YoPalAI.pem` **내용 전체**(`-----BEGIN` 줄 포함) |
| Secret | `DEPLOY_AI_DIR` | 예: `/home/ubuntu/beautyai` |
| Secret | `GHCR_PULL_TOKEN` | `read:packages` PAT |

### BeautyWEB_project

| 종류 | 이름 | 값 |
|---|---|---|
| Variable | `DEPLOY_BRANCH` | `main` |
| Secret | `DEPLOY_HOST` | **WEB 인스턴스**의 IP/도메인 (AI 와 다를 수 있다 — 아래 참고) |
| Secret | `DEPLOY_USER` | 예: `ubuntu` / `ec2-user` |
| Secret | `DEPLOY_SSH_KEY` | `YoPalette.pem` **내용 전체** |
| Secret | `DEPLOY_WEB_DIR` | 예: `/home/ubuntu/beautyweb` |

> **AI 와 WEB 은 서로 다른 인스턴스일 가능성이 높다.** 근거 둘:
> `YoPalAI.pem` 과 `YoPalette.pem` 이 **서로 다른 키**이고, 두 스택의 Caddy 가 **둘 다
> `80:80`·`443:443` 을 잡는다**(`docker-compose.prod.yml` / `docker-compose.aws.yml`).
> 같은 호스트라면 나중에 뜨는 쪽이 포트 바인딩에 실패한다 — 자동배포가 조용히 깨지는 지점이다.
> 각 저장소가 자기 시크릿을 쓰므로 **한 호스트든 두 호스트든 워크플로는 그대로 동작한다.**
> 다만 한 호스트라면 Caddy 를 하나로 합치고(Caddyfile 병합) 다른 쪽 caddy 서비스를 빼야 한다.
> `DEPLOY_READY_CHECKLIST.md` 는 Caddy 도입 **이전** 문서라 "같은 호스트" 라고 쓰여 있다 — 그대로 믿지 말 것.

> `environment: production` 을 쓰므로, Settings → Environments 에 `production` 을 만들어야
> 시크릿이 주입된다. 여기에 **승인 규칙(Required reviewers)** 을 걸면 "수동 승인 후 배포"로
> 언제든 바꿀 수 있다 — 워크플로 수정 없이.

---

## 3. 동작 흐름

```
push → CI (pytest / 프론트 빌드 / 이미지 빌드)
          └─ 성공 + DEPLOY_BRANCH 일 때만 ─→ Deploy
                                              AI : S3 번들 → 이미지 빌드 → GHCR → EC2 pull → /ready 확인
                                              WEB: EC2 git reset --hard → up -d --build → /v1/api/items 확인
```

실패하면 배포되지 않는다. `workflow_dispatch` 로 수동 실행도 가능하다.

---

## 4. 주의

- **`workflow_run` 은 기본 브랜치에 있는 워크플로만 실행된다**(GitHub 제약). 즉
  `deploy.yml` 이 `main` 에 머지되기 전에는 **아무 일도 일어나지 않는다** — 기능 브랜치에
  올려둔 상태로는 트리거가 걸리지 않는다. AI 는 현재 `fix/product-recommendation-20260730`
  에 있으므로, 자동배포를 켜려면 이 브랜치를 `main` 에 머지해야 한다.
  머지 전에도 Actions 탭에서 `workflow_dispatch`(수동 실행)로는 돌려볼 수 있다.
- `DEPLOY_BRANCH` Variable 을 만들지 않으면 조건이 빈 문자열과 비교돼 **배포 잡이 항상
  건너뛰어진다**. 실수로 배포되는 일은 없지만, 켤 때 반드시 만들어야 한다.
- **AI 저장소는 private** → Actions 분이 과금 대상(무료 2,000분/월)이다. 현재 `ci.yml` 의
  `images` 잡이 매 push 마다 백엔드 이미지(torch)를 빌드해 수 분씩 쓴다. 분이 모자라면
  그 잡을 `if: github.event_name == 'push'` 로 좁히거나 배포 잡의 빌드로 갈음할 것.
- **WEB 배포는 서버 작업트리를 `git reset --hard` 한다.** 서버에서 직접 고친 파일은 사라진다.
  `.env` 는 `.gitignore` 라 안전하다.
- **WEB 저장소의 `origin` 은 로컬에서 엉뚱한 곳(`gallery.git`)을 가리킨다.** 실제 원격은
  `beautyweb` 이다. 로컬에서 푸시할 때 `git push beautyweb beautyweb-main:main` 처럼
  원격을 명시할 것(EC2 클론은 origin 이 정상이라 무관).
- 배포 태그는 커밋 SHA 앞 12자리다. 롤백은 EC2 에서 `.env.images` 의 태그를 이전 값으로
  바꾸고 `docker compose ... up -d --no-build` 하면 된다.

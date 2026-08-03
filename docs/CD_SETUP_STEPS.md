# 자동배포 켜기 — 클릭 순서대로

브라우저 옆에 띄워놓고 위에서부터 그대로 따라가면 된다.
설계 배경과 시크릿 표는 [CD_SETUP.md](CD_SETUP.md) 참조.

**순서를 지킬 것.** WEB 은 준비물이 없어 10분이면 끝나고, AI 는 AWS·토큰을 만들어야 한다.
WEB 을 먼저 끝내서 파이프라인이 도는 걸 눈으로 확인한 뒤 AI 로 넘어가는 편이 빠르다.

---

# PART 1. WEB 켜기 (준비물 없음)

## 1-1. .pem 내용을 클립보드에 담기

메모장으로 열어 드래그하지 말 것 — 마지막 줄바꿈이 빠져 `invalid key` 로 실패하는 사고가 잦다.
PowerShell 에서:

```powershell
Get-Content C:\WorkSpace\Beauty_Project\YoPalette.pem -Raw | Set-Clipboard
```

이제 클립보드에 `-----BEGIN RSA PRIVATE KEY-----` 부터 끝까지 들어 있다.

## 1-2. 시크릿 4개 등록

1. 브라우저에서 열기 →
   **https://github.com/LeeDohun-hub/BeautyWEB_project/settings/secrets/actions**
   (저장소 페이지 상단 **Settings** → 왼쪽 사이드바 **Secrets and variables** → **Actions** 와 같은 곳)
2. 오른쪽 위 초록 버튼 **New repository secret**
3. `Name` 과 `Secret` 을 넣고 **Add secret**. 아래 4개를 반복한다.

| Name | Secret |
|---|---|
| `DEPLOY_HOST` | `www.yopalette.com` |
| `DEPLOY_USER` | `ubuntu` |
| `DEPLOY_SSH_KEY` | 1-1 에서 복사한 클립보드 내용 (Ctrl+V) |
| `DEPLOY_WEB_DIR` | `/home/ubuntu/BeautyWEB_project` |

> 등록한 값은 다시 볼 수 없다(이름만 보인다). 틀렸으면 같은 이름으로 다시 등록하면 덮어써진다.

## 1-3. 변수 1개 등록

1. 같은 페이지 위쪽 탭에서 **Variables** 클릭 (Secrets 옆)
2. **New repository variable**

| Name | Value |
|---|---|
| `DEPLOY_BRANCH` | `main` |

> 이걸 안 만들면 배포 잡이 **항상 건너뛰어진다**(실수 배포 방지 장치). 즉 여기까지 안 하면 아무 일도 안 일어난다.

## 1-4. production 환경 만들기

1. **https://github.com/LeeDohun-hub/BeautyWEB_project/settings/environments**
2. **New environment** → 이름에 `production` → **Configure environment**
3. 아무것도 건드리지 말고 그냥 나오면 된다.

> 나중에 이 화면에서 **Required reviewers** 를 켜면, 워크플로를 고치지 않고도
> "푸시하면 대기 → 승인 눌러야 배포" 로 바뀐다.

## 1-5. 돌려보기

1. **https://github.com/LeeDohun-hub/BeautyWEB_project/actions**
2. 왼쪽 목록에서 **Deploy WEB** 클릭
3. 오른쪽 **Run workflow** ▾ → 브랜치 `main` → **Run workflow**
4. 1~2분 뒤 새 실행을 클릭해 로그를 본다. 성공하면 `backend OK` 가 찍힌다.

여기까지 되면 **이제부터 `main` 에 푸시할 때마다 CI 통과 후 자동 배포된다.**

---

# PART 2. AI 켜기 (AWS·토큰 필요)

AI 는 373MB 런타임 번들(모델·카탈로그)을 이미지에 굽는데, 그 원본이 git 에 없다.
그래서 S3 에 올려두고 러너가 받아가게 한다. 준비물이 셋이다: S3 버킷, IAM 키, GHCR 토큰.

## 2-1. S3 버킷 만들기

1. **https://s3.console.aws.amazon.com/s3/buckets** (서울 리전인지 오른쪽 위에서 확인)
2. **버킷 만들기**
3. **버킷 이름**: 전역에서 고유해야 한다. 예) `yopalette-runtime-bundle`
4. **AWS 리전**: `아시아 태평양(서울) ap-northeast-2`
5. 나머지는 **전부 기본값 그대로**(퍼블릭 액세스 차단 유지 — 공개할 필요 없다)
6. **버킷 만들기**

정한 이름을 기억해 둔다. 시크릿 값은 `s3://yopalette-runtime-bundle/runtime_data` 형태가 된다.

## 2-2. IAM 사용자 + 액세스 키 만들기

1. **https://console.aws.amazon.com/iam/home#/users** → **사용자 생성**
2. 사용자 이름: `beautyai-cd`
3. "AWS Management Console에 대한 사용자 액세스 권한 제공" → **체크하지 않는다**(콘솔 로그인 불필요)
4. 권한 설정 → **직접 정책 연결** → 위쪽 **정책 생성**(새 탭) → **JSON** 탭에 아래를 붙여넣는다.
   `BUCKET` 두 군데를 2-1 의 버킷 이름으로 바꿀 것.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": ["s3:ListBucket"], "Resource": "arn:aws:s3:::BUCKET" },
    { "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::BUCKET/*" }
  ]
}
```

   정책 이름 `beautyai-runtime-bundle` 로 저장 → 원래 탭으로 돌아와 새로고침 후 그 정책을 체크 → **사용자 생성**

   > 이 키는 **그 버킷 하나만** 읽고 쓸 수 있다. 업로드(로컬)와 다운로드(러너)에 같은 키를
   > 쓰려고 쓰기 권한을 포함했다. 더 엄격히 가려면 읽기 전용 사용자를 따로 만들어
   > GitHub 에는 그쪽 키만 넣으면 된다.

5. 생성된 사용자 클릭 → **보안 자격 증명** 탭 → **액세스 키 만들기**
6. 사용 사례 **명령줄 인터페이스(CLI)** 선택 → 확인 체크 → **다음** → **액세스 키 만들기**
7. **액세스 키 ID** 와 **비밀 액세스 키** 를 지금 복사해 둔다(비밀 키는 이 화면을 벗어나면 다시 못 본다)

## 2-3. GHCR 토큰 만들기

러너가 만든 이미지를 EC2 가 받아가야 하는데, AI 저장소가 private 이라 이미지도 private 이다.

1. **https://github.com/settings/tokens**
2. **Generate new token** ▾ → **Generate new token (classic)** ← *classic 이어야 한다*
3. Note: `beautyai-ghcr-pull`
4. Expiration: 원하는 기간(만료되면 배포가 실패하니 달력에 적어둘 것)
5. Select scopes: **`read:packages` 하나만** 체크
6. **Generate token** → 값 복사(이 화면을 벗어나면 다시 못 본다)

## 2-4. 시크릿 9개 + 변수 1개 등록

`Get-Content C:\WorkSpace\Beauty_Project\YoPalAI.pem -Raw | Set-Clipboard` (WEB 과 **다른 키**다)

**https://github.com/LeeDohun-hub/BeautyAI_project/settings/secrets/actions** → **New repository secret**

| Name | Secret |
|---|---|
| `DEPLOY_HOST` | `ai.yopalette.com` |
| `DEPLOY_USER` | `ubuntu` |
| `DEPLOY_SSH_KEY` | `YoPalAI.pem` 내용 (클립보드) |
| `DEPLOY_AI_DIR` | `/home/ubuntu/BeautyAI_project` |
| `AWS_ACCESS_KEY_ID` | 2-2 의 액세스 키 ID |
| `AWS_SECRET_ACCESS_KEY` | 2-2 의 비밀 액세스 키 |
| `AWS_REGION` | `ap-northeast-2` |
| `RUNTIME_BUNDLE_S3_URI` | `s3://<2-1 버킷명>/runtime_data` |
| `GHCR_PULL_TOKEN` | 2-3 의 토큰 |

**Variables** 탭 → `DEPLOY_BRANCH` = `main`
**Environments** → `production` 생성 (1-4 와 동일)

## 2-5. 번들을 S3 에 올리기 (로컬에서)

```powershell
aws configure
#   AWS Access Key ID     : 2-2 의 값
#   AWS Secret Access Key : 2-2 의 값
#   Default region name   : ap-northeast-2
#   Default output format : (엔터)

cd C:\WorkSpace\Beauty_Project\BeautyAI_project
$env:RUNTIME_BUNDLE_S3_URI = "s3://<버킷명>/runtime_data"
python scripts\publish_runtime_bundle.py --dry-run   # 무엇이 올라갈지 먼저 확인
python scripts\publish_runtime_bundle.py             # 실제 업로드(373MB, 회선에 따라 수 분)
```

> **모델이나 매니페스트를 바꿀 때마다 이걸 다시 해야 한다.** 안 하면 코드만 새로 배포되고
> 데이터는 옛것이라, 에러 없이 커버리지만 떨어진다. 배포 로그의 `번들 최신 파일:` 날짜로 확인할 수 있다.

## 2-6. 돌려보기

**https://github.com/LeeDohun-hub/BeautyAI_project/actions** → **Deploy AI** → **Run workflow**

성공하면 로그 끝에 `ready OK` 가 찍힌다. 첫 실행은 이미지 빌드+푸시라 10~20분 걸린다.

---

# 막혔을 때

| 증상 | 원인 |
|---|---|
| 배포 잡이 **회색으로 건너뜀** | `DEPLOY_BRANCH` 변수가 없거나 `main` 이 아니다 |
| `다음 Secret 이 비어 있습니다: …` | 그 이름의 시크릿이 없다(오타 포함). 이름은 대소문자를 구분한다 |
| `ssh: invalid key` / `no key found` | `.pem` 을 일부만 붙여넣었다. 1-1 의 클립보드 방법으로 다시 |
| `denied` / `unauthorized` (docker pull) | `GHCR_PULL_TOKEN` 이 classic 이 아니거나 `read:packages` 가 빠졌다 |
| `Unable to locate credentials` | `AWS_ACCESS_KEY_ID`/`SECRET`/`REGION` 셋 중 하나가 비었다 |
| `NoSuchBucket` | `RUNTIME_BUNDLE_S3_URI` 의 버킷명 오타, 또는 리전이 다르다 |
| 배포는 성공인데 화면이 안 바뀜 | compose 프로젝트명 불일치로 **두 번째 스택**이 떴을 때 나온다. 서버에서 `docker compose ls` 로 확인 |

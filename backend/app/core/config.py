from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./beautyai.db"
    # ── 환경 가드 ──────────────────────────────────────────────────────────────
    # 로컬 개발이 운영 DB 를 그대로 치는 사고를 막는다.
    # 2026-08-03 확인: .env 와 .env.prod 의 DATABASE_URL 이 글자 하나까지 같아, 로컬에서
    # uvicorn 을 띄우거나 스크립트를 돌리면 운영 DB(회원 14·분석 111·이력 483)에 썼다.
    # 운영 컨테이너만 APP_ENV=production 을 받는다(docker-compose.prod.yml).
    app_env: str = "local"
    # 운영 DB 를 알아보는 조각(Supabase 프로젝트 ref). DATABASE_URL 에 이 문자열이 있으면
    # 운영 DB 로 본다. ⚠️ 운영 DB 를 옮기면 이 값도 같이 바꿔야 가드가 계속 동작한다.
    production_db_marker: str = "ekmelstemgzjbjppoalg"
    # 로컬에서 **의도적으로** 운영 DB 를 봐야 할 때만 켠다(데이터 확인·마이그레이션 리허설).
    # 사고는 막되 필요한 작업은 막지 않기 위한 명시적 탈출구다.
    allow_production_db: bool = False
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    chroma_path: str = "./data/rag/chromadb"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # ── 웹 계정 연동 ────────────────────────────────────────────────────────────
    # BeautyWEB(Spring)과 **같은 값**이어야 한다. 다르면 핸드오프 티켓 서명 검증이 전부 실패한다.
    # 기본값은 WEB 의 TokenUtils 기본값과 맞춰 로컬에서 설정 없이 돌아가게 한 것 — 운영에서는 반드시 교체.
    jwt_secret: str = "CHANGE_ME_32_BYTE_MINIMUM_JWT_SECRET!"
    # AI 가 티켓을 교환해 발급하는 자체 세션 수명. WEB 액세스토큰(1분)과 무관하게 여기서 정한다.
    ai_session_exp_hours: int = 12
    # True 면 분석·추천 API 가 세션 없이는 401. 프론트 게이트만으로는 API 가 그대로 열려 있어서
    # 운영에서는 켜는 게 맞다(docker-compose.prod.yml 에서 REQUIRE_LOGIN=true).
    # 기본값이 False 인 이유: 로컬/테스트에서 익명 호출로 기능을 그대로 확인할 수 있게.
    require_login: bool = False
    # ── 개인정보 보관 기간 ──────────────────────────────────────────────────────
    # 이 일수가 지난 분석·설문·추천이력·상담기록을 지운다(scripts/expire_user_data.py).
    #
    # ⚠ 365 는 **개발팀이 정한 기본값**이지 법무·정책이 확정한 값이 아니다.
    #    정책이 정해지면 DATA_RETENTION_DAYS 만 바꾸면 된다(재배포 불필요).
    # ⚠ 0 이면 만료하지 않는다. 설정 실수로 데이터가 사라지지 않게, **끄는 쪽이 안전한 값**이다.
    data_retention_days: int = 365
    # ── 일본 비포/애프터 제어 ───────────────────────────────────────────────────
    # 일본 医療広告ガイドライン 은 시술 전후 사진에 시술 내용·비용·주요 위험을 **병기**하도록
    # 요구한다. 가상 성형 미리보기가 형식상 그 형태라, 병원 연결이 붙는 시점에 일본에서는
    # 원본·변형본 나란히 놓기를 끌 수 있어야 한다(docs/medical_ad_working_assumptions.md 전제 4).
    #
    # ⚠ **지금은 켜 둔다(True = 현행 유지).** 병원 연결 전에는 의료광고 주체가 아니라는
    #    해석이 성립하고, 법무 회신 전에 기능을 미리 줄일 이유가 없다.
    #    회신이 '해당한다'로 오면 운영에서 이 값만 false 로 바꾼다 — 재배포가 필요 없게
    #    환경변수로 뺐다. 스위치를 미리 만들어 두는 것이 이 항목의 목적이다.
    jp_before_after: bool = True
    # 게이트에 걸렸을 때 프론트가 안내할 웹 로그인 주소.
    web_login_url: str = "http://localhost:5174/login"
    # 웹 API 주소(BeautyWEB 프론트의 VITE_API_BASE_URL 과 같은 값 — `/v1/api` 까지).
    #
    # AI 프론트가 부팅할 때 "웹에 로그인돼 있나"를 **브라우저에서 직접** 물어보는 곳이다.
    # 웹에서 로그인만 하고 주소창으로 AI 에 들어온 사용자를 게이트에서 되돌리지 않으려면
    # 필요하다(티켓은 웹의 AI 버튼으로 넘어올 때만 생긴다).
    #
    # **비워두면 web_login_url 의 오리진에서 자동으로 만든다**(resolved_web_api_base_url).
    # 운영 서버의 .env.prod 는 사람이 직접 고치는 파일이라, 새 변수를 필수로 만들면
    # 채우는 걸 잊었을 때 기능만 조용히 죽는다 — 이미 있는 값에서 유도되게 둔다.
    #
    # ⚠ 반드시 **리프레시 쿠키가 붙은 호스트**(=한국몰 www)여야 한다. 쿠키는 Domain 미설정
    #   호스트 한정이라, 일본몰 주소를 넣으면 쿠키가 없어 항상 비로그인으로 보인다.
    # ⚠ 그 호스트의 CORS 허용 목록(BEAUTYWEB_CORS_ALLOWED_ORIGINS)에 AI 오리진이 있어야 한다.
    web_api_base_url: str = ""
    # 결과지 QR 이 가리킬 웹 장바구니 주소. `?ai=<code>` 가 붙는다.
    web_cart_url: str = "http://localhost:5174/cart"
    # 장바구니 핸드오프 코드 수명(분). 결과지를 출력해 놓고 나중에 찍는 경우가 있어
    # 로그인 티켓(120초)보다는 넉넉히 준다. 1회용이라 다 쓰면 바로 죽는다.
    cart_handoff_exp_minutes: int = 30
    # 피부케어 6항목 회귀기. AI-Hub 03(스킨케어) 육안평가 등급으로 재학습한 버전으로 교체
    # (2026-07-23). 03 val MAE 39.8→6.2, 출력채널 상관 0.349→0.182(6항목 구분 개선).
    # 구 Kaggle-키워드 라벨 버전(skin_efficientnet_b0.pt)은 폴백용으로 보존. 되돌리려면 이 줄만 원복.
    # ⚠️ 실셀카 재현성은 소폭 개선뿐 → 추론 시 여러 프레임 평균 + 3구간 표시 유지 필수.
    skin_model_path: str = "./data/models/skin_efficientnet_b0_aihub03.pt"
    body_skin_model_path: str = "./data/models/body_skin_mobilenet_v3.pt"
    # 2단 피부질환 선별 모델(Tier1 게이트 + Tier2 케어 분류).
    derma_tier1_model_path: str = "./data/models/derma_tier1_gate.pt"
    derma_tier2_model_path: str = "./data/models/derma_tier2_classifier.pt"
    personal_color_model_path: str = "./data/models/personal_color_retrain_try2_smooth005.pt"
    # AI-Hub 다인종 데이터 기반 분류기(사진 → 분광측색 참Lab 회귀 → 계절 규칙).
    # 기존과 원리가 달라 색블렌드를 쓰지 않는다(모델이 조명 보정을 내장). 켜면 기존 경로를 대체.
    # 실측(동북아 646명, val 129명, GALAXY 24 Ultra): 조명일치도 85.3% / 계절정확도 55.0%.
    aihub_pc_model_path: str = "./data/models/aihub_pc_lab.pt"
    personal_color_use_aihub: bool = False
    # 앙상블 — v1(all-lux 3d) + v3(all-lux 9d) 예측 Lab 평균 + 좌우반전 TTA.
    # 실측(val 129명): 프레임정확도 55.4→57.6%, 조명일치도 50.4→61.2%, ΔE 2.642→2.586.
    # ⚠️ v2(aihub_pc_lab_v2.pt)는 500lux 전용이라 5000lux에서 ΔE≈26으로 붕괴 → 앙상블 금지.
    aihub_pc_ensemble_paths: str = "./data/models/aihub_pc_lab.pt,./data/models/aihub_pc_lab_v3.pt"
    aihub_pc_tta: bool = True
    # 경계선 판정 임계값 — 최상위 계절 확률이 이 값 미만이면 borderline(=top-2 병기 권장).
    # 보정 실측(AI-Hub 60명, analyzer 전체 경로, 전체 정확도 63.3%):
    #   0.34 → 경계 28% / 확신 67.4%   0.38 → 경계 53% / 확신 75.0%
    #   0.42 → 경계 68% / 확신 84.2%   0.45 → 경계 75% / 확신 93.3%
    # 경계 그룹은 임계값과 무관하게 ~53%(진짜 애매). 커버리지↔정밀도 트레이드오프라 조정 가능.
    # 기본 0.38 = 절반이 확신 답변(75% 정확). 키오스크가 정밀도를 원하면 0.45로 올린다.
    personal_color_borderline_threshold: float = 0.38
    # 네일 디자인 리트리벌(B안). 셋 중 하나라도 없으면 기능이 비활성으로 응답한다.
    #  - seg: 손톱 학습 YOLOv8(CC BY 4.0). 발톱에도 전이됨(발 909장 100% 검출).
    #  - embedder: torchvision IMAGENET1K_V1 백본을 로컬 체크포인트로 굳힌 것.
    #    ⚠️ weights=IMAGENET1K_V1 로 만들면 런타임에 인터넷 다운로드가 일어난다 — 다른 모델들과
    #    동일하게 weights=None + 로컬 로드로 간다. 인덱스를 만든 가중치와 반드시 같아야 한다.
    nail_seg_model_path: str = "./data/models/nails_seg_s_yolov8_v1.pt"
    nail_embedder_model_path: str = "./data/models/nail_embedder_efficientnet_b0.pt"
    nail_index_dir: str = "./data/nail_index"
    # 하이브리드 점수 score = cos유사도 − λ·(ΔE/100). λ 스윕 실측(질의 400개):
    #   0 → ΔE 23.4·hit@5 71% / 0.5 → ΔE 11.4·hit@5 96% / 1.0 → ΔE 8.3·hit@5 100%(질감 뭉개짐)
    nail_retrieval_color_weight: float = 0.5
    problem_skin_knowledge_path: str = "./data/rag/problem_skin_knowledge.jsonl"
    skincare_ingredient_knowledge_path: str = "./data/rag/skincare_ingredient_knowledge.jsonl"
    # 위 코퍼스의 일본어 번역본(id 로 1:1 대응). 없으면 일본어 모드에서 성분 근거 문단을
    # 생략한다 — 한국어를 대신 내보내지 않는다.
    skincare_ingredient_knowledge_path_ja: str = "./data/rag/skincare_ingredient_knowledge.ja.jsonl"
    # 병별 OTC 의약품 예시(OpenFDA OTC 라벨 기반). build_otc_drug_knowledge.py로 생성.
    otc_drug_knowledge_path: str = "./data/rag/otc_drug_knowledge.jsonl"
    naver_client_id: str | None = None
    naver_client_secret: str | None = None
    rakuten_app_id: str | None = None
    rakuten_access_key: str | None = None
    rakuten_referer: str = "http://127.0.0.1:5173/"
    # 퍼스널컬러 계절 블렌드 게이팅: 색상 휴리스틱(color) 가중치에 곱하는 배율.
    # 1.0=현행(한국/일본 얼굴에 유리, 색블렌드가 도움). 유럽/글로벌 얼굴은 model 단독이 더 정확해
    # (실측: global model 0.36 vs blended 0.29) 글로벌 마켓 요청 시 배율을 낮춰 model 쪽으로 기울인다.
    personal_color_color_blend_scale: float = 1.0
    personal_color_global_blend_scale: float = 0.35
    # 조명 게이팅: 공막 화이트밸런스 실패(=따뜻한 실내광/캐스트 미보정) 시 색 신호를 낮춘다.
    # AI Hub 분광측색계 실측 대조(2026-07-15): WB성공 시 픽셀 b*가 실측과 상관(r0.64), WB실패 시 무의미(r0.09).
    personal_color_wb_fail_color_scale: float = 0.5

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in {"production", "prod"}

    @property
    def resolved_web_api_base_url(self) -> str:
        """웹 세션을 물어볼 API 주소. 설정이 비었으면 web_login_url 의 오리진에서 만든다.

        운영은 WEB_LOGIN_URL 이 이미 `https://<한국몰>/login` 이라 그대로 맞아떨어진다.
        로그인 주소와 API 호스트가 다른 배포(예: api 서브도메인)에서만 WEB_API_BASE_URL 을
        따로 준다.
        """
        explicit = self.web_api_base_url.strip().rstrip("/")
        if explicit:
            return explicit
        parts = urlsplit(self.web_login_url.strip())
        if not parts.scheme or not parts.netloc:
            return ""
        return f"{parts.scheme}://{parts.netloc}/v1/api"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[3]

    @property
    def resolved_skin_model_path(self) -> str:
        path = Path(self.skin_model_path)
        if path.is_absolute():
            return str(path)
        return str(self.project_root / path)

    @property
    def resolved_body_skin_model_path(self) -> str:
        path = Path(self.body_skin_model_path)
        if path.is_absolute():
            return str(path)
        return str(self.project_root / path)

    @property
    def resolved_personal_color_model_path(self) -> str:
        path = Path(self.personal_color_model_path)
        if path.is_absolute():
            return str(path)
        return str(self.project_root / path)

    @property
    def resolved_aihub_pc_model_path(self) -> str:
        return self._resolved(self.aihub_pc_model_path)

    @property
    def resolved_aihub_pc_ensemble_paths(self) -> list[str]:
        """앙상블 체크포인트(존재하는 것만). 비면 단일 aihub_pc_model_path 로 폴백."""
        paths = [self._resolved(p) for p in self.aihub_pc_ensemble_paths.split(",") if p.strip()]
        existing = [p for p in paths if Path(p).exists()]
        return existing or [self.resolved_aihub_pc_model_path]

    def _resolved(self, value: str) -> str:
        path = Path(value)
        return str(path) if path.is_absolute() else str(self.project_root / path)

    @property
    def resolved_derma_tier1_model_path(self) -> str:
        return self._resolved(self.derma_tier1_model_path)

    @property
    def resolved_derma_tier2_model_path(self) -> str:
        return self._resolved(self.derma_tier2_model_path)


@lru_cache
def get_settings() -> Settings:
    return Settings()

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./beautyai.db"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    chroma_path: str = "./data/rag/chromadb"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    skin_model_path: str = "./data/models/skin_efficientnet_b0.pt"
    body_skin_model_path: str = "./data/models/body_skin_mobilenet_v3.pt"
    # 2단 피부질환 선별 모델(Tier1 게이트 + Tier2 케어 분류).
    derma_tier1_model_path: str = "./data/models/derma_tier1_gate.pt"
    derma_tier2_model_path: str = "./data/models/derma_tier2_classifier.pt"
    personal_color_model_path: str = "./data/models/personal_color_retrain_try2_smooth005.pt"
    problem_skin_knowledge_path: str = "./data/rag/problem_skin_knowledge.jsonl"
    skincare_ingredient_knowledge_path: str = "./data/rag/skincare_ingredient_knowledge.jsonl"
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

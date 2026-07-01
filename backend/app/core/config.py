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
    personal_color_model_path: str = "./data/models/personal_color_efficientnet.pt"
    problem_skin_knowledge_path: str = "./data/rag/problem_skin_knowledge.jsonl"
    naver_client_id: str | None = None
    naver_client_secret: str | None = None
    rakuten_app_id: str | None = None
    rakuten_access_key: str | None = None
    rakuten_referer: str = "http://127.0.0.1:5173/"

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


@lru_cache
def get_settings() -> Settings:
    return Settings()

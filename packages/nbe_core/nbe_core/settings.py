"""Runtime settings, read once from the environment (set by docker-compose and .env)."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    demo_id: str = os.getenv("DEMO_ID", "dev")
    postgres_host: str = os.getenv("POSTGRES_HOST", "nbe-postgres")
    postgres_password: str = os.getenv("POSTGRES_PASSWORD", "")
    qdrant_url: str = os.getenv("QDRANT_URL", "http://nbe-qdrant:6333")
    # Platform services (Phase 1), all on the internal nbe-core network
    llm_gateway_url: str = os.getenv("LLM_GATEWAY_URL", "")          # LiteLLM, OpenAI-compatible
    llm_gateway_key: str = os.getenv("LITELLM_MASTER_KEY", "")
    rerank_url: str = os.getenv("RERANK_URL", "http://nbe-rerank:8000")
    guardrails_url: str = os.getenv("GUARDRAILS_URL", "http://nbe-guardrails:8000")
    mockbank_url: str = os.getenv("MOCKBANK_URL", "http://nbe-mockbank:8000")
    docling_url: str = os.getenv("DOCLING_URL", "http://nbe-docling:8000")

    @property
    def postgres_dsn(self) -> str:
        return f"host={self.postgres_host} dbname=nbe user=nbe password={self.postgres_password} connect_timeout=3"


settings = Settings()

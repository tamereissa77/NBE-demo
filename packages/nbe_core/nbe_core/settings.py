"""Runtime settings, read once from the environment (set by docker-compose and .env)."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    demo_id: str = os.getenv("DEMO_ID", "dev")
    postgres_host: str = os.getenv("POSTGRES_HOST", "nbe-postgres")
    postgres_password: str = os.getenv("POSTGRES_PASSWORD", "")
    qdrant_url: str = os.getenv("QDRANT_URL", "http://nbe-qdrant:6333")
    # OpenAI-compatible model gateway (LiteLLM), wired in Phase 1
    llm_gateway_url: str = os.getenv("LLM_GATEWAY_URL", "")

    @property
    def postgres_dsn(self) -> str:
        return f"host={self.postgres_host} dbname=nbe user=nbe password={self.postgres_password} connect_timeout=3"


settings = Settings()

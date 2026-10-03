from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6-luna"
    max_tool_iterations: int = 5
    bookly_today: str = "2026-10-01"

    public_demo: bool = False
    demo_rate_limit_requests: int = 30
    demo_rate_limit_window_seconds: int = 600

    identity_base_url: str = "http://127.0.0.1:8001"
    commerce_base_url: str = "http://127.0.0.1:8002"
    knowledge_base_url: str = "http://127.0.0.1:8003"


settings = Settings()

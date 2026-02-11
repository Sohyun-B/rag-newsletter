from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # MSSQL
    MSSQL_SERVER: str
    MSSQL_DATABASE: str
    MSSQL_USER: str
    MSSQL_PASSWORD: str

    # OpenAI
    OPENAI_API_KEY: str

    # Chroma
    CHROMA_PATH: str = "./chroma_data"

    # Gmail
    GMAIL_TOKEN_PATH: str = "./gmail/token.json"
    GMAIL_CREDENTIALS_PATH: str = "./gmail/credentials.json"

    # Scheduler
    SYNC_INTERVAL_MINUTES: int = 5

    # 동기화 대상 발신인
    SYNC_SENDERS: list[str] = [
        "whatsup@newneek.co",
        "dig@mk.co.kr",
        "nytdirect@nytimes.com",
        "nytimes@e.newyorktimes.com",
        "editorpicks@nytimes.com",
        "newsletters@theatlantic.com",
        "modulabs01-gmail.com@send.stibee.com",
        "letter@khan.kr",
        "contact@datarian.io",
    ]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

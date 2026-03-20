import os
from pathlib import Path

from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    database_url: str = f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'twitter_monitor.db'}"
    secret_key: str = "change-me-in-production"
    default_check_interval: int = 5  # minutes
    wechat_webhook_key: str = ""
    serverchan_sendkey: str = ""
    twitter_proxy_url: str = ""
    twitter_proxy_timeout: int = 45
    twitter_transaction_fallback: bool = True

    class Config:
        env_file = str(BASE_DIR / ".env")
        env_file_encoding = "utf-8"


settings = Settings()

# Ensure data directory exists
(BASE_DIR / "data").mkdir(exist_ok=True)

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env.local")
load_dotenv(RAIZ / ".env")


class Settings:
    API_KEY: str = (os.getenv("API_KEY") or "").strip()
    CORS_ORIGINS: list[str] = [
        origem.strip()
        for origem in (os.getenv("CORS_ORIGINS") or "http://localhost:3000").split(",")
        if origem.strip()
    ]


settings = Settings()

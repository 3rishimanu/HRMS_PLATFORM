import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./hrms.db")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "hireflow-ai-super-secret-key-change-in-production")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60


settings = Settings()

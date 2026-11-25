from pydantic_settings import BaseSettings

# 예전에 main.py에 박혀 있던 목록 그대로다.
DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://localhost:5173",
    "https://baro-front-five.vercel.app",
    "https://baro-front-qlq4xlmhw-soyeons-projects-0593c180.vercel.app",
)


class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ENCRYPTION_KEY: str
    OPENAI_API_KEY: str
    OPENAI_MODEL: str = "gpt-5-mini"  # OpenAI 모델 이름
    BARO_AI_URL: str = "http://localhost:8001"  # Baro-AI 서비스 URL
    # 허용할 프론트 주소. 쉼표로 구분한다.
    # 비어 있으면 DEFAULT_CORS_ORIGINS를 쓴다. 운영 compose는 값이 없을 때 빈 문자열을 넘기므로
    # 빈 값을 "모두 차단"으로 해석하면 안 된다.
    CORS_ORIGINS: str = ""

    @property
    def cors_origins(self) -> list[str]:
        if not self.CORS_ORIGINS.strip():
            return list(DEFAULT_CORS_ORIGINS)
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    class Config:
        env_file = ".env"

settings = Settings()
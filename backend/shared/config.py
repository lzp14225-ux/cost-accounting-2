from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="allow",
    )

    APP_NAME: str = "mold_main_backend"
    APP_VERSION: str = "3.0.0"

    PORT: int = 8211
    API_GATEWAY_HOST: str = "0.0.0.0"
    API_GATEWAY_PORT: int = 8211
    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 8211
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8211

    DEBUG: bool = True
    RELOAD: bool = True
    CORS_ORIGINS: str = ""
    START_EMBEDDED_WORKER: bool = True
    EMBEDDED_WORKER_ENTRY: str = "workers/all_tasks_worker.py"

    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 5432
    DB_NAME: str = "mold_cost_db"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = ""

    REDIS_URL: str = ""

    RABBITMQ_HOST: str = "127.0.0.1"
    RABBITMQ_PORT: int = 5672
    RABBITMQ_USER: str = ""
    RABBITMQ_PASSWORD: str = ""
    RABBITMQ_QUEUE_JOB_PROCESSING: str = "job_processing"
    RABBITMQ_QUEUE_DLX: str = "job_processing_dlx"

    MINIO_ENDPOINT: str = ""
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_REGION: str = "us-east-1"
    MINIO_USE_HTTPS: bool = False
    MINIO_BUCKET_FILES: str = "files"
    MINIO_EXTERNAL_ENDPOINT: str = ""

    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"
    ENABLE_JSON_LOG: bool = False

    MAX_FILE_SIZE_MB: int = 1000
    ALLOWED_FILE_EXTENSIONS: str = ".dwg,.prt"

    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "Qwen3-30B-A3B-Instruct"
    OPENAI_BASE_URL: str = ""
    LLM_TIMEOUT: float = 30.0

    CAD_PRICE_SEARCH_MCP_URL: str = ""
    FEATURE_REPROCESS_API_URL: str = ""
    PRICING_RECALCULATE_API_URL: str = ""
    PRICING_RECALCULATE_FALLBACK_URL: str = ""
    WEIGHT_PRICE_API_URL: str = ""
    NC_AGENT_URL: str = ""
    NC_AGENT_TIMEOUT: int = 7200
    NC_AGENT_REQUEST_TIMEOUT: int = 180
    NC_AGENT_POLL_INTERVAL: float = 60.0
    NC_EXCEL_RETENTION_DAYS: int = 7
    NC_SOURCE_DB_HOST: str = ""
    NC_SOURCE_DB_PORT: int = 5432
    NC_SOURCE_DB_NAME: str = ""
    NC_SOURCE_DB_USER: str = ""
    NC_SOURCE_DB_PASSWORD: str = ""
    NC_SOURCE_TABLE: str = "nc"
    NC_SOURCE_MINIO_ENDPOINT: str = ""
    NC_SOURCE_MINIO_ACCESS_KEY: str = ""
    NC_SOURCE_MINIO_SECRET_KEY: str = ""
    NC_SOURCE_MINIO_REGION: str = "us-east-1"
    NC_SOURCE_MINIO_USE_HTTPS: bool = False
    NC_SOURCE_MINIO_BUCKET: str = "ncresult"
    SPEECH_SERVICE_URL: str = ""
    TTS_SERVICE_URL: str = ""
    SPEECH_DEFAULT_MODEL: str = "small"
    SPEECH_DEFAULT_LANGUAGE: str = "zh"
    SPEECH_MODEL_DIR: str = ""
    FFMPEG_PATH: str = ""
    SPEECH_HOST: str = "0.0.0.0"
    SPEECH_PORT: int = 8888
    COSYVOICE_ROOT: str = ""
    TTS_MODEL_DIR: str = ""
    TTS_DEFAULT_MODE: str = "sft"
    TTS_HOST: str = "0.0.0.0"
    TTS_PORT: int = 8890
    API_TIMEOUT: float = 60.0

    PRICE_WG_RULE_WEIGHT_UNIT: str = "g"

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def RABBITMQ_URL(self) -> str:
        return (
            f"amqp://{self.RABBITMQ_USER}:{self.RABBITMQ_PASSWORD}"
            f"@{self.RABBITMQ_HOST}:{self.RABBITMQ_PORT}/"
        )

    @property
    def CORS_ORIGINS_LIST(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def ALLOWED_EXTENSIONS_LIST(self) -> List[str]:
        return [
            ext.strip().lower()
            for ext in self.ALLOWED_FILE_EXTENSIONS.split(",")
            if ext.strip()
        ]

    @property
    def MAX_FILE_SIZE_BYTES(self) -> int:
        return int(self.MAX_FILE_SIZE_MB) * 1024 * 1024

    @property
    def UNIFIED_PORT(self) -> int:
        return int(self.PORT or self.API_GATEWAY_PORT or self.SERVER_PORT)


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

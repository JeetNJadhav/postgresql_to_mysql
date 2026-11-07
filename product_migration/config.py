import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    postgres_host: str = os.getenv("POSTGRES_HOST", "localhost")
    postgres_port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    postgres_database: str = os.getenv("POSTGRES_DATABASE", "")
    postgres_user: str = os.getenv("POSTGRES_USER", "")
    postgres_password: str = os.getenv("POSTGRES_PASSWORD", "")
    mysql_host: str = os.getenv("MYSQL_HOST", "localhost")
    mysql_port: int = int(os.getenv("MYSQL_PORT", "3306"))
    mysql_database: str = os.getenv("MYSQL_DATABASE", "")
    mysql_user: str = os.getenv("MYSQL_USER", "")
    mysql_password: str = os.getenv("MYSQL_PASSWORD", "")
    llm_provider: str = os.getenv("LLM_PROVIDER", "").lower()
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    confidence_threshold: float = float(os.getenv("LLM_CONFIDENCE_THRESHOLD", "0.80"))
    provider_timeout: float = float(os.getenv("PROVIDER_TIMEOUT_SECONDS", "12"))
    user_agent: str = os.getenv("PROVIDER_USER_AGENT", "ProductMigrationAgent/1.0")
    batch_size: int = int(os.getenv("BATCH_SIZE", "50"))
    enable_off: bool = os.getenv("ENABLE_OPEN_FOOD_FACTS", "true").lower() == "true"
    enable_obf: bool = os.getenv("ENABLE_OPEN_BEAUTY_FACTS", "true").lower() == "true"

    def postgres_url(self) -> str:
        self._required(self.postgres_database, self.postgres_user, self.postgres_password)
        from urllib.parse import quote_plus
        return f"postgresql+psycopg://{quote_plus(self.postgres_user)}:{quote_plus(self.postgres_password)}@{self.postgres_host}:{self.postgres_port}/{quote_plus(self.postgres_database)}"

    def mysql_url(self) -> str:
        self._required(self.mysql_database, self.mysql_user, self.mysql_password)
        from urllib.parse import quote_plus
        return f"mysql+pymysql://{quote_plus(self.mysql_user)}:{quote_plus(self.mysql_password)}@{self.mysql_host}:{self.mysql_port}/{quote_plus(self.mysql_database)}?charset=utf8mb4"

    @staticmethod
    def _required(*values: str) -> None:
        if not all(values):
            raise ValueError("Database configuration is incomplete; populate the corresponding POSTGRES_* or MYSQL_* variables in .env")

settings = Settings()

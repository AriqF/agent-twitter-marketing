import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_OWNER_CHAT_ID: str = os.getenv("TELEGRAM_OWNER_CHAT_ID")
TELEGRAM_UPDATE_MODE: str = os.getenv("TELEGRAM_UPDATE_MODE", "polling")
TELEGRAM_WEBHOOK_URL: str = os.getenv("TELEGRAM_WEBHOOK_URL", "")
TELEGRAM_WEBHOOK_PORT: str = int(os.getenv("TELEGRAM_WEBHOOK_PORT", "8080"))
TELEGRAM_WEBHOOK_PATH: str = os.getenv("TELEGRAM_WEBHOOK_PATH", "/telegram/webhook")
TELEGRAM_WEBHOOK_LISTEN: str = os.getenv("TELEGRAM_WEBHOOK_LISTEN", "0.0.0.0")
TELEGRAM_WEBHOOK_SECRET: str = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
TELEGRAM_REQUEST_TIMEOUT: float = float(os.getenv("TELEGRAM_REQUEST_TIMEOUT", "30"))
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://user:password@localhost:5432/marketing_agent",
)
TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Jakarta")

# X API
# OAuth 1.0a User Context (for posting)
X_API_KEY: str = os.getenv("X_API_KEY")
X_API_SECRET: str = os.getenv("X_API_SECRET")
X_ACCESS_TOKEN: str = os.getenv("X_ACCESS_TOKEN")
X_ACCESS_TOKEN_SECRET: str = os.getenv("X_ACCESS_TOKEN_SECRET")
# Bearer Token (for search - App-Only auth)
X_BEARER_TOKEN: str = os.getenv("X_BEARER_TOKEN")
BATCH_CYCLE_DAYS: int = int(os.getenv("BATCH_CYCLE_DAYS", "3"))
REPLY_TIMES: str = os.getenv("REPLY_TIMES", "09:00,20:00").split(",")
REPLY_KEYWORDS_PER_CYCLE: int = int(os.getenv("REPLY_KEYWORDS_PER_CYCLE", "3"))
REPLY_SCAN_BACKLOG_THRESHOLD: int = int(os.getenv("REPLY_SCAN_BACKLOG_THRESHOLD", "5"))
REPLY_MAX_NEW_CANDIDATES: int = int(os.getenv("REPLY_MAX_NEW_CANDIDATES", "5"))
X_ACCOUNT_USERNAME: str = os.getenv("X_ACCOUNT_USERNAME", None)
X_EXCLUDE_SELF_REPLIES: bool = os.getenv("X_EXCLUDE_SELF_REPLIES", "true") == "true"

PRODUCT_PATH = BASE_DIR / "product.yaml"
with open(PRODUCT_PATH, "r", encoding="utf-8") as f:
    PRODUCT = yaml.safe_load(f)["product"]

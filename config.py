import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_OWNER_CHAT_ID = os.getenv("TELEGRAM_OWNER_CHAT_ID")
TELEGRAM_UPDATE_MODE = os.getenv("TELEGRAM_UPDATE_MODE", "polling")
TELEGRAM_WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL", "")
TELEGRAM_WEBHOOK_PORT = int(os.getenv("TELEGRAM_WEBHOOK_PORT", "8080"))
TELEGRAM_WEBHOOK_PATH = os.getenv("TELEGRAM_WEBHOOK_PATH", "/telegram/webhook")
TELEGRAM_WEBHOOK_LISTEN = os.getenv("TELEGRAM_WEBHOOK_LISTEN", "0.0.0.0")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://user:password@localhost:5432/marketing_agent",
)
TIMEZONE = os.getenv("TIMEZONE", "Asia/Jakarta")

# X API
# OAuth 1.0a User Context (for posting)
X_API_KEY = os.getenv("X_API_KEY")
X_API_SECRET = os.getenv("X_API_SECRET")
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN")
X_ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET")
# Bearer Token (for search - App-Only auth)
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")
BATCH_CYCLE_DAYS = int(os.getenv("BATCH_CYCLE_DAYS", "3"))
REPLY_TIMES = os.getenv("REPLY_TIMES", "09:00,20:00").split(",")
REPLY_KEYWORDS_PER_CYCLE = int(os.getenv("REPLY_KEYWORDS_PER_CYCLE", "3"))
REPLY_SCAN_BACKLOG_THRESHOLD = int(os.getenv("REPLY_SCAN_BACKLOG_THRESHOLD", "5"))
REPLY_MAX_NEW_CANDIDATES = int(os.getenv("REPLY_MAX_NEW_CANDIDATES", "5"))

PRODUCT_PATH = BASE_DIR / "product.yaml"
with open(PRODUCT_PATH, "r", encoding="utf-8") as f:
    PRODUCT = yaml.safe_load(f)["product"]

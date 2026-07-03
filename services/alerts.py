import asyncio
import logging
from collections.abc import Awaitable
from typing import TypeVar

from config import TELEGRAM_OWNER_CHAT_ID

logger = logging.getLogger(__name__)

T = TypeVar("T")

_NOTIFY_TIMEOUT_SEC = 15.0
_NOTIFY_RETRIES = 2


def is_transient_telegram_error(exc: BaseException) -> bool:
    from telegram.error import NetworkError, RetryAfter, TimedOut

    return isinstance(exc, (TimedOut, NetworkError, RetryAfter))


async def notify_owner(text: str) -> None:
    from services.telegram import get_bot

    bot = get_bot()
    for attempt in range(_NOTIFY_RETRIES):
        try:
            await asyncio.wait_for(
                bot.send_message(chat_id=TELEGRAM_OWNER_CHAT_ID, text=text),
                timeout=_NOTIFY_TIMEOUT_SEC,
            )
            return
        except TimeoutError:
            logger.warning(
                "Owner notification wait timed out (attempt %s/%s)",
                attempt + 1,
                _NOTIFY_RETRIES,
            )
        except Exception as exc:
            if is_transient_telegram_error(exc):
                logger.warning(
                    "Owner notification transient error (attempt %s/%s): %s",
                    attempt + 1,
                    _NOTIFY_RETRIES,
                    exc,
                )
            else:
                logger.error("Failed to send owner notification: %s", text[:200])
                return
        if attempt + 1 < _NOTIFY_RETRIES:
            await asyncio.sleep(2)


async def notify_owner_error(context: str, exc: Exception) -> None:
    if is_transient_telegram_error(exc):
        logger.warning("%s transient telegram error: %s", context, exc)
        return

    logger.exception("%s failed", context)
    message = f"⚠️ {context}: {str(exc)[:200]}"
    await notify_owner(message)


async def run_guarded(
    context: str,
    coro: Awaitable[T],
    *,
    re_raise: bool = False,
) -> T | None:
    try:
        return await coro
    except Exception as exc:
        await notify_owner_error(context, exc)
        if re_raise:
            raise
        return None

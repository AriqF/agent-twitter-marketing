import asyncio
import logging

from services.logging_config import setup_logging

setup_logging()

from telegram.ext import (  # noqa: E402
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from api.server import start_http_server, stop_http_server  # noqa: E402
from config import (  # noqa: E402
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_REQUEST_TIMEOUT,
    TELEGRAM_UPDATE_MODE,
    TELEGRAM_WEBHOOK_LISTEN,
    TELEGRAM_WEBHOOK_PATH,
    TELEGRAM_WEBHOOK_PORT,
    TELEGRAM_WEBHOOK_SECRET,
    TELEGRAM_WEBHOOK_URL,
)
from db.session import init_db  # noqa: E402
from scheduler.jobs import setup_scheduler  # noqa: E402
from services.alerts import is_transient_telegram_error, notify_owner_error  # noqa: E402
from services.telegram import (  # noqa: E402
    cmd_help,
    cmd_create_plan,
    cmd_publish_content,
    cmd_publish_reply,
    cmd_search_reply,
    cmd_start,
    cmd_view_content,
    cmd_view_plan,
    cmd_view_replies,
    handle_callback,
    handle_feedback_message,
    set_bot,
)
from services.wiki_writer import seed_product_wiki_if_empty  # noqa: E402

logger = logging.getLogger(__name__)

_SHUTDOWN_TIMEOUT_SEC = 15.0


def _validate_webhook_config() -> None:
    if not TELEGRAM_WEBHOOK_URL:
        raise ValueError(
            "TELEGRAM_WEBHOOK_URL is required when TELEGRAM_UPDATE_MODE=webhook"
        )
    if not TELEGRAM_WEBHOOK_URL.rstrip("/").endswith(TELEGRAM_WEBHOOK_PATH.rstrip("/")):
        raise ValueError(
            f"TELEGRAM_WEBHOOK_URL must end with TELEGRAM_WEBHOOK_PATH ({TELEGRAM_WEBHOOK_PATH})"
        )


def _build_telegram_app() -> Application:
    timeout = TELEGRAM_REQUEST_TIMEOUT
    return (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .connect_timeout(timeout)
        .read_timeout(timeout)
        .write_timeout(timeout)
        .pool_timeout(timeout)
        .get_updates_connect_timeout(timeout)
        .get_updates_read_timeout(timeout)
        .build()
    )


async def _ptb_error_handler(update: object, context) -> None:
    error = context.error
    if error and is_transient_telegram_error(error):
        logger.warning("Telegram transient error (update=%s): %s", update, error)
        return

    logger.exception("Unhandled PTB error", exc_info=error)
    if error:
        await notify_owner_error("telegram_handler", error)


async def _shutdown_telegram(
    app: Application,
    *,
    use_webhook: bool,
    http_runner,
) -> None:
    try:
        async with asyncio.timeout(_SHUTDOWN_TIMEOUT_SEC):
            if use_webhook:
                try:
                    await app.bot.delete_webhook(drop_pending_updates=False)
                except Exception as exc:
                    logger.warning("delete_webhook failed: %s", exc)
                if http_runner is not None:
                    await stop_http_server(http_runner)
            else:
                await app.updater.stop()
            await app.stop()
            await app.shutdown()
    except TimeoutError:
        logger.warning("Telegram shutdown timed out after %.0fs", _SHUTDOWN_TIMEOUT_SEC)
    except Exception as exc:
        logger.warning("Telegram shutdown error: %s", exc)


async def main():
    app = None
    http_runner = None
    scheduler = None
    use_webhook = TELEGRAM_UPDATE_MODE == "webhook"

    try:
        await init_db()
        await seed_product_wiki_if_empty()

        scheduler = setup_scheduler()
        scheduler.start()

        app = _build_telegram_app()
        set_bot(app.bot)
        app.add_error_handler(_ptb_error_handler)

        app.add_handler(CommandHandler("create_plan", cmd_create_plan))
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("help", cmd_help))
        app.add_handler(CommandHandler("view_plan", cmd_view_plan))
        app.add_handler(CommandHandler("search_reply", cmd_search_reply))
        app.add_handler(CommandHandler("view_replies", cmd_view_replies))
        app.add_handler(CommandHandler("publish_reply", cmd_publish_reply))
        app.add_handler(CommandHandler("view_content", cmd_view_content))
        app.add_handler(CommandHandler("publish_content", cmd_publish_content))

        app.add_handler(CallbackQueryHandler(handle_callback))
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_feedback_message)
        )

        await app.initialize()
        await app.start()

        if use_webhook:
            _validate_webhook_config()
            http_runner = await start_http_server(app)
            await app.bot.set_webhook(
                url=TELEGRAM_WEBHOOK_URL,
                secret_token=TELEGRAM_WEBHOOK_SECRET or None,
            )
            logger.info(
                "AI Marketing Agent running (webhook mode at %s)",
                TELEGRAM_WEBHOOK_URL,
            )
            logger.info(
                "HTTP server listening on %s:%s",
                TELEGRAM_WEBHOOK_LISTEN,
                TELEGRAM_WEBHOOK_PORT,
            )
            logger.info(
                "Webhook: POST %s | Health: GET /health",
                TELEGRAM_WEBHOOK_PATH,
            )
        else:
            await app.updater.start_polling()
            logger.info("AI Marketing Agent running (polling mode)")

        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, SystemExit):
            pass
    except Exception as exc:
        logger.exception("Startup failed")
        try:
            await notify_owner_error("startup", exc)
        except Exception:
            logger.error("Could not notify owner about startup failure")
        raise
    finally:
        if scheduler is not None:
            try:
                scheduler.shutdown(wait=False)
            except Exception:
                pass
        if app is not None:
            await _shutdown_telegram(
                app, use_webhook=use_webhook, http_runner=http_runner
            )


if __name__ == "__main__":
    asyncio.run(main())

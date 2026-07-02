import asyncio

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from api.server import start_http_server, stop_http_server
from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_UPDATE_MODE,
    TELEGRAM_WEBHOOK_LISTEN,
    TELEGRAM_WEBHOOK_PATH,
    TELEGRAM_WEBHOOK_PORT,
    TELEGRAM_WEBHOOK_SECRET,
    TELEGRAM_WEBHOOK_URL,
)
from db.session import init_db
from scheduler.jobs import setup_scheduler
from services.telegram import (
    cmd_create_plan,
    cmd_search_reply,
    cmd_view_plan,
    handle_callback,
    handle_revision_message,
)
from services.wiki_writer import seed_product_wiki_if_empty


def _validate_webhook_config() -> None:
    if not TELEGRAM_WEBHOOK_URL:
        raise ValueError(
            "TELEGRAM_WEBHOOK_URL is required when TELEGRAM_UPDATE_MODE=webhook"
        )
    if not TELEGRAM_WEBHOOK_URL.rstrip("/").endswith(TELEGRAM_WEBHOOK_PATH.rstrip("/")):
        raise ValueError(
            f"TELEGRAM_WEBHOOK_URL must end with TELEGRAM_WEBHOOK_PATH ({TELEGRAM_WEBHOOK_PATH})"
        )


async def main():
    await init_db()
    await seed_product_wiki_if_empty()

    scheduler = setup_scheduler()
    scheduler.start()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("create_plan", cmd_create_plan))
    app.add_handler(CommandHandler("view_plan", cmd_view_plan))
    app.add_handler(CommandHandler("search_reply", cmd_search_reply))

    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_revision_message)
    )

    await app.initialize()
    await app.start()

    http_runner = None
    use_webhook = TELEGRAM_UPDATE_MODE == "webhook"

    if use_webhook:
        _validate_webhook_config()
        http_runner = await start_http_server(app)
        await app.bot.set_webhook(
            url=TELEGRAM_WEBHOOK_URL,
            secret_token=TELEGRAM_WEBHOOK_SECRET or None,
        )
        print(
            f"AI Marketing Agent is running (webhook mode at {TELEGRAM_WEBHOOK_URL})..."
        )
        print(
            f"HTTP server listening on {TELEGRAM_WEBHOOK_LISTEN}:{TELEGRAM_WEBHOOK_PORT}"
        )
        print(f"Webhook: POST {TELEGRAM_WEBHOOK_PATH} | Health: GET /health")
    else:
        await app.updater.start_polling()
        print("AI Marketing Agent is running (polling mode)...")

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        scheduler.shutdown()
        if use_webhook:
            await app.bot.delete_webhook(drop_pending_updates=False)
            if http_runner is not None:
                await stop_http_server(http_runner)
        else:
            await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

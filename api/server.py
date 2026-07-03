import logging

from aiohttp import web
from telegram import Update
from telegram.ext import Application

from config import (
    TELEGRAM_WEBHOOK_LISTEN,
    TELEGRAM_WEBHOOK_PATH,
    TELEGRAM_WEBHOOK_PORT,
    TELEGRAM_WEBHOOK_SECRET,
)

logger = logging.getLogger(__name__)


async def health_handler(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def telegram_webhook_handler(request: web.Request) -> web.Response:
    try:
        ptb_app: Application = request.app["ptb_app"]

        if TELEGRAM_WEBHOOK_SECRET:
            token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if token != TELEGRAM_WEBHOOK_SECRET:
                return web.Response(status=403)

        data = await request.json()
        update = Update.de_json(data, ptb_app.bot)
        await ptb_app.process_update(update)
        return web.Response(status=200)
    except Exception:
        logger.exception("Webhook processing failed")
        return web.Response(status=500)


async def start_http_server(ptb_app: Application) -> web.AppRunner:
    aio_app = web.Application()
    aio_app["ptb_app"] = ptb_app
    aio_app.router.add_get("/health", health_handler)
    aio_app.router.add_post(TELEGRAM_WEBHOOK_PATH, telegram_webhook_handler)

    runner = web.AppRunner(aio_app)
    await runner.setup()
    site = web.TCPSite(runner, TELEGRAM_WEBHOOK_LISTEN, TELEGRAM_WEBHOOK_PORT)
    await site.start()
    return runner


async def stop_http_server(runner: web.AppRunner) -> None:
    await runner.cleanup()

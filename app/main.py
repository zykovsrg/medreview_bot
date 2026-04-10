from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.bot import create_router
from app.config import load_settings
from app.google_clients import GoogleRepository
from app.reminders import ReminderService
from app.storage import Storage


logger = logging.getLogger(__name__)
STARTUP_RETRY_DELAY_SECONDS = 5
TELEGRAM_SESSION_TIMEOUT_SECONDS = 120


async def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    bot = Bot(
        settings.bot_token,
        session=AiohttpSession(timeout=TELEGRAM_SESSION_TIMEOUT_SECONDS),
    )
    dispatcher = Dispatcher()

    storage = Storage(settings.db_path)
    repository = GoogleRepository(settings)
    reminders = ReminderService(storage, repository)
    dispatcher.include_router(create_router(repository, storage, settings, reminders))
    await reminders.start(bot)

    while True:
        try:
            await dispatcher.start_polling(bot, polling_timeout=10)
            break
        except TelegramNetworkError:
            logger.exception(
                "Telegram API is temporarily unavailable during polling startup. Retrying in %s seconds.",
                STARTUP_RETRY_DELAY_SECONDS,
            )
            await asyncio.sleep(STARTUP_RETRY_DELAY_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.bot import create_router
from app.config import load_settings
from app.google_clients import GoogleRepository
from app.storage import Storage


async def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    bot = Bot(settings.bot_token)
    dispatcher = Dispatcher()

    storage = Storage(settings.db_path)
    repository = GoogleRepository(settings)
    dispatcher.include_router(create_router(repository, storage, settings))

    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

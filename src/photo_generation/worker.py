import asyncio
import logging

from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from .config import get_settings
from .db import init_db
from .queue import JobQueue
from .service import GenerationService

logger = logging.getLogger(__name__)


def result_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Сделать ещё фото", callback_data="result:new")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="result:menu")],
    ])


def user_error_message(error: Exception) -> str:
    """Turn provider failures into safe, actionable Telegram messages."""
    details = str(error).lower()
    if "403 forbidden" in details and "fal.ai" in details:
        return (
            "Баланс fal.ai закончился. Пополни баланс на fal.ai или оставь настроенный "
            "OPENAI_API_KEY для резервной генерации. Генерация возвращена."
        )
    if "moderation_blocked" in details or "safety" in details:
        return (
            "Этот снимок или запрос не прошёл проверку безопасности AI. "
            "Попробуй обычное фото в одежде и нейтральное описание. Генерация возвращена."
        )
    return "Не удалось обработать фото. Генерация возвращена — можно попробовать ещё раз."


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    init_db()
    queue = JobQueue(settings)
    service = GenerationService(settings)
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    bot = Bot(settings.telegram_bot_token)
    logger.info(
        "Worker started: mode=%s, luxury=%s, celebrity_with_photo=%s, composite=%s",
        "mock" if settings.mock_mode else "live",
        service.router.choose("luxury").name,
        service.router.choose("celebrity", has_reference=True).name,
        service.router.choose("composite", has_reference=True).name,
    )
    while True:
        try:
            item = await asyncio.to_thread(queue.next, 10)
        except Exception:
            logger.exception("Redis queue is unavailable; retrying in 5 seconds")
            await asyncio.sleep(5)
            continue
        if not item:
            continue
        try:
            output_path = await asyncio.to_thread(service.process_job, item.job_id)
            await bot.send_photo(
                item.telegram_id,
                FSInputFile(output_path),
                caption="Готово ✨",
                reply_markup=result_menu(),
            )
        except Exception as error:
            logger.exception("Job %s failed", item.job_id)
            await bot.send_message(
                item.telegram_id,
                user_error_message(error),
                reply_markup=result_menu(),
            )


if __name__ == "__main__":
    asyncio.run(main())

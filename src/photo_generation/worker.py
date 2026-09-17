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
    recovered = await asyncio.to_thread(queue.recover_pending)
    logger.info(
        "Worker started: concurrency=%s, recovered=%s, mode=%s, luxury=%s, celebrity_with_photo=%s, composite=%s",
        settings.worker_concurrency,
        recovered,
        "mock" if settings.mock_mode else "live",
        service.router.choose("luxury").name,
        service.router.choose("celebrity", has_reference=True).name,
        service.router.choose("composite", has_reference=True).name,
    )
    async def consume() -> None:
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
                output_path = await asyncio.to_thread(service.process_job, item.job.job_id)
                if output_path:
                    await bot.send_photo(
                        item.job.telegram_id,
                        FSInputFile(output_path),
                        caption="Готово ✨",
                        reply_markup=result_menu(),
                    )
            except Exception as error:
                logger.exception("Job %s failed", item.job.job_id)
                await bot.send_message(
                    item.job.telegram_id,
                    user_error_message(error),
                    reply_markup=result_menu(),
                )
            finally:
                await asyncio.to_thread(service.cleanup_workspace, item.job.job_id)
                try:
                    await asyncio.to_thread(queue.acknowledge, item)
                except Exception:
                    logger.exception("Could not acknowledge job %s; it will be recovered", item.job.job_id)

    await asyncio.gather(*(consume() for _ in range(settings.worker_concurrency)))


if __name__ == "__main__":
    asyncio.run(main())

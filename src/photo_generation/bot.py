import asyncio
import logging
import uuid
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)
from sqlalchemy import select

from .config import Settings
from .db import Payment, SessionLocal, User, init_db
from .prompts import SCENES, celebrity_prompt, composite_prompt, luxury_prompt
from .queue import JobQueue
from .service import GenerationService
from .storage import MediaStorage

logger = logging.getLogger(__name__)


class PhotoFlow(StatesGroup):
    awaiting_main = State()
    awaiting_reference = State()
    awaiting_text = State()


def menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Жить богато", callback_data="mode:luxury")],
        [InlineKeyboardButton(text="🌟 Я со знаменитостью", callback_data="mode:celebrity")],
        [InlineKeyboardButton(text="🖼 Добавить меня на фото", callback_data="mode:composite")],
        [InlineKeyboardButton(text="💳 Купить генерации", callback_data="buy")],
    ])


def scene_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=scene.title, callback_data=f"scene:{scene.key}")] for scene in SCENES
    ])


def result_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Сделать ещё фото", callback_data="result:new")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="result:menu")],
    ])


def build_router(settings: Settings) -> Router:
    router = Router()
    service = GenerationService(settings)
    queue = JobQueue(settings)
    storage = MediaStorage(settings)

    @router.message(CommandStart())
    async def start(message: Message, state: FSMContext) -> None:
        await state.clear()
        await asyncio.to_thread(service.get_or_create_user, message.from_user.id)
        await message.answer(
            f"Привет! Это {settings.bot_name}. Выбери сценарий и отправь фотографию хорошего качества.",
            reply_markup=menu(),
        )

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        await message.answer(
            "Для вставки на другое фото отправь сначала своё фото, потом фоновое. "
            "После результата можно нажать «Сделать ещё фото»."
        )

    @router.message(Command("status"))
    async def status_command(message: Message) -> None:
        if settings.mock_mode:
            await message.answer("Сейчас включён DEMO-режим: AI-провайдеры не вызываются.")
        else:
            providers = []
            if settings.openai_api_key:
                providers.append("OpenAI")
            if settings.fal_key:
                providers.append("fal.ai")
            await message.answer("Активные провайдеры: " + (", ".join(providers) or "нет") + ".")

    @router.message(Command("myid"))
    async def my_id(message: Message) -> None:
        await message.answer(f"Твой Telegram ID: {message.from_user.id}")

    @router.message(Command("reset_free"))
    async def reset_free(message: Message) -> None:
        if settings.admin_telegram_id == 0 or message.from_user.id != settings.admin_telegram_id:
            await message.answer("Команда доступна только владельцу бота.")
            return
        service.reset_free_limit(message.from_user.id)
        await message.answer("Тестовый бесплатный лимит сброшен. Можно запускать новую генерацию.", reply_markup=menu())

    @router.callback_query(F.data.startswith("mode:"))
    async def choose_mode(callback: CallbackQuery, state: FSMContext) -> None:
        mode = callback.data.split(":", 1)[1]
        await state.update_data(mode=mode)
        await state.set_state(PhotoFlow.awaiting_main)
        await callback.answer()
        text = {
            "luxury": "Выбери сцену, затем отправь свою фотографию.",
            "celebrity": "Отправь свою фотографию. Потом напиши имя знаменитости или пришли её фото.",
            "composite": "Сначала отправь свою фотографию, затем фоновую фотографию.",
        }[mode]
        await callback.message.answer(text, reply_markup=scene_menu() if mode == "luxury" else None)

    @router.callback_query(F.data.startswith("scene:"))
    async def choose_scene(callback: CallbackQuery, state: FSMContext) -> None:
        await state.update_data(scene_key=callback.data.split(":", 1)[1])
        await callback.answer("Сцена выбрана")
        await callback.message.answer("Теперь отправь свою фотографию.")

    @router.callback_query(F.data == "result:new")
    async def new_result(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await callback.answer()
        await callback.message.answer("Выбери новый сценарий:", reply_markup=menu())

    @router.callback_query(F.data == "result:menu")
    async def result_home(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await callback.answer()
        await callback.message.answer("Главное меню:", reply_markup=menu())

    async def download_photo(message: Message, job_id: str, slot: str) -> Path | None:
        photo = message.photo[-1]
        if photo.file_size and photo.file_size > settings.max_upload_mb * 1024 * 1024:
            await message.answer(f"Фото слишком большое. Максимум — {settings.max_upload_mb} МБ.")
            return None
        folder = Path(settings.media_dir) / job_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{slot}.jpg"
        try:
            telegram_file = await message.bot.get_file(photo.file_id)
            await message.bot.download_file(telegram_file.file_path, destination=path)
            stored = await asyncio.to_thread(storage.store, path, f"uploads/{job_id}/{slot}.jpg")
            path.unlink(missing_ok=True)
            return Path(stored)
        except Exception:
            logger.exception("Could not download Telegram photo")
            await message.answer("Не удалось скачать фото. Попробуй отправить его ещё раз.")
            return None

    @router.message(PhotoFlow.awaiting_main, F.photo)
    async def receive_main(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        job_id = str(uuid.uuid4())
        main_path = await download_photo(message, job_id, "main")
        if main_path is None:
            return
        await state.update_data(job_id=job_id, main_path=str(main_path))
        mode = data["mode"]
        if mode == "luxury":
            scene_key = data.get("scene_key", "yacht")
            scene = next(item for item in SCENES if item.key == scene_key)
            await create_and_enqueue(message, state, mode, luxury_prompt(scene), main_path, None, job_id, service, queue)
        elif mode == "composite":
            await state.set_state(PhotoFlow.awaiting_reference)
            await message.answer("Теперь отправь фоновую фотографию.")
        else:
            await state.set_state(PhotoFlow.awaiting_text)
            await message.answer("Напиши имя знаменитости или пришли её фотографию.")

    @router.message(PhotoFlow.awaiting_reference, F.photo)
    async def receive_reference(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        reference_path = await download_photo(message, data["job_id"], "reference")
        if reference_path is None:
            return
        await create_and_enqueue(message, state, "composite", composite_prompt(), Path(data["main_path"]), reference_path, data["job_id"], service, queue)

    @router.message(PhotoFlow.awaiting_text, F.text)
    async def receive_celebrity_name(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        await create_and_enqueue(message, state, "celebrity", celebrity_prompt(message.text.strip()), Path(data["main_path"]), None, data["job_id"], service, queue)

    @router.message(PhotoFlow.awaiting_text, F.photo)
    async def receive_celebrity_photo(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        reference_path = await download_photo(message, data["job_id"], "reference")
        if reference_path is None:
            return
        await create_and_enqueue(message, state, "celebrity", celebrity_prompt("the person in the second reference image"), Path(data["main_path"]), reference_path, data["job_id"], service, queue)

    @router.callback_query(F.data == "buy")
    async def buy(callback: CallbackQuery) -> None:
        await callback.answer()
        await callback.message.answer_invoice(
            title="Пакет генераций",
            description=f"{settings.paid_credits_per_pack} AI-фотографии",
            payload=f"photo_pack:{settings.paid_credits_per_pack}",
            currency="XTR",
            prices=[LabeledPrice(label="Генерации", amount=settings.paid_pack_stars)],
            provider_token="",
        )

    @router.pre_checkout_query()
    async def pre_checkout(query: PreCheckoutQuery) -> None:
        await query.answer(ok=True)

    @router.message(F.successful_payment)
    async def successful_payment(message: Message) -> None:
        payment = message.successful_payment
        with SessionLocal() as session:
            exists = session.scalar(select(Payment).where(
                Payment.telegram_payment_id == payment.telegram_payment_charge_id
            ))
            if not exists:
                user = session.scalar(select(User).where(User.telegram_id == message.from_user.id))
                if not user:
                    user = User(telegram_id=message.from_user.id)
                    session.add(user)
                    session.flush()
                user.credits += settings.paid_credits_per_pack
                session.add(Payment(
                    telegram_payment_id=payment.telegram_payment_charge_id,
                    telegram_id=message.from_user.id,
                    stars=payment.total_amount,
                ))
                session.commit()
        await message.answer("Оплата получена. Кредиты добавлены.", reply_markup=menu())

    return router


async def create_and_enqueue(message, state, mode, prompt, main_path, reference_path, job_id, service, queue):
    charge_type = None
    job_created = False
    try:
        allowed, charge_type = await asyncio.to_thread(service.reserve_generation, message.from_user.id)
        if not allowed:
            await state.clear()
            text = (
                "У тебя уже есть генерация в очереди. Дождись результата, затем можно будет создать новую."
                if charge_type == "busy"
                else "Бесплатная генерация на сегодня закончилась."
            )
            await message.answer(text, reply_markup=menu())
            return
        await asyncio.to_thread(
            service.create_job,
            message.from_user.id,
            mode,
            prompt,
            str(main_path),
            str(reference_path) if reference_path else None,
            job_id=job_id,
            paid=charge_type == "credit",
        )
        job_created = True
        queued = await asyncio.to_thread(queue.enqueue, job_id, message.from_user.id)
        if not queued:
            await asyncio.to_thread(service.cancel_queued_job, job_id)
            await asyncio.to_thread(service.refund_generation, message.from_user.id, charge_type)
            await state.clear()
            await message.answer(
                "Сейчас слишком много запросов. Попробуй снова через несколько минут.", reply_markup=menu()
            )
            return
        await state.clear()
        await message.answer("Фото принято и поставлено в очередь. Я пришлю результат, когда он будет готов.")
    except Exception:
        logger.exception("Could not enqueue photo generation job")
        if job_created:
            await asyncio.to_thread(service.cancel_queued_job, job_id)
        if charge_type in {"credit", "free"}:
            await asyncio.to_thread(service.refund_generation, message.from_user.id, charge_type)
        await state.clear()
        await message.answer("Не удалось поставить фото в очередь. Проверь Redis и попробуй ещё раз.")


async def run_bot(settings: Settings) -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    init_db()
    from aiogram.fsm.storage.redis import RedisStorage
    from redis.asyncio import Redis

    storage = RedisStorage(redis=Redis.from_url(settings.redis_url))
    bot = Bot(settings.telegram_bot_token)
    dispatcher = Dispatcher(storage=storage)
    dispatcher.include_router(build_router(settings))
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    from .config import get_settings

    asyncio.run(run_bot(get_settings()))

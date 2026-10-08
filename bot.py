from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, User

from config import Settings, load_settings
from storage import Storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EDIT_LABELS = {
    "welcome": "основное приветствие",
    "button_1_text": "название первой кнопки",
    "answer_1": "ответ на первую кнопку",
    "button_2_text": "название второй кнопки",
    "answer_2": "ответ на вторую кнопку",
}


class AdminState(StatesGroup):
    editing_setting = State()
    waiting_for_broadcast = State()
    confirming_broadcast = State()


def is_admin(user: User, settings: Settings) -> bool:
    return bool(user.username and user.username.lower() in settings.admin_usernames)


def public_keyboard(storage: Storage) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=storage.get("button_1_text"), callback_data="public:one"),
                InlineKeyboardButton(text=storage.get("button_2_text"), callback_data="public:two"),
            ]
        ]
    )


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Приветствие", callback_data="admin:edit:welcome")],
            [
                InlineKeyboardButton(text="✏️ Кнопка 1", callback_data="admin:edit:button_1_text"),
                InlineKeyboardButton(text="✏️ Ответ 1", callback_data="admin:edit:answer_1"),
            ],
            [
                InlineKeyboardButton(text="✏️ Кнопка 2", callback_data="admin:edit:button_2_text"),
                InlineKeyboardButton(text="✏️ Ответ 2", callback_data="admin:edit:answer_2"),
            ],
            [
                InlineKeyboardButton(text="📣 Создать рассылку", callback_data="admin:broadcast"),
                InlineKeyboardButton(text="👥 Пользователи", callback_data="admin:users"),
            ],
        ]
    )


def broadcast_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подробнее", callback_data="public:details")]
        ]
    )


def confirm_broadcast_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data="admin:broadcast:confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="admin:broadcast:cancel"),
            ]
        ]
    )


def build_dispatcher(settings: Settings, storage: Storage) -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())

    def permitted(user: User) -> bool:
        allowed = is_admin(user, settings)
        storage.refresh_known_user_role(user.id, user.username, allowed)
        return allowed

    async def send_welcome(message: Message) -> None:
        await message.answer(storage.get("welcome"), reply_markup=public_keyboard(storage))

    async def show_admin_panel(message: Message) -> None:
        await message.answer("Админ-панель", reply_markup=admin_keyboard())

    @dispatcher.message(CommandStart())
    async def start_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        allowed = is_admin(message.from_user, settings)
        storage.register_started_user(message.from_user.id, message.from_user.username, allowed)
        await send_welcome(message)
        if allowed:
            await show_admin_panel(message)

    @dispatcher.message(Command("admin"))
    async def admin_command(message: Message) -> None:
        if permitted(message.from_user):
            await show_admin_panel(message)

    @dispatcher.callback_query(F.data == "public:one")
    async def first_button(callback: CallbackQuery) -> None:
        await callback.answer()
        await callback.message.answer(storage.get("answer_1"))

    @dispatcher.callback_query(F.data == "public:two")
    async def second_button(callback: CallbackQuery) -> None:
        await callback.answer()
        await callback.message.answer(storage.get("answer_2"))

    @dispatcher.callback_query(F.data == "public:details")
    async def details_button(callback: CallbackQuery) -> None:
        await callback.answer()
        await send_welcome(callback.message)

    @dispatcher.callback_query(F.data.startswith("admin:"))
    async def admin_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not permitted(callback.from_user):
            await callback.answer("Нет доступа", show_alert=True)
            return

        if callback.data == "admin:users":
            await callback.answer()
            await callback.message.answer(
                f"Бота запустили: {storage.user_count()} пользователей."
            )
            return

        if callback.data == "admin:broadcast":
            await state.set_state(AdminState.waiting_for_broadcast)
            await callback.answer()
            await callback.message.answer(
                "Отправьте текст рассылки. Перед отправкой покажу подтверждение.\n"
                "Отмена: /cancel"
            )
            return

        if callback.data.startswith("admin:edit:"):
            key = callback.data.removeprefix("admin:edit:")
            if key not in EDIT_LABELS:
                await callback.answer("Неизвестная настройка", show_alert=True)
                return
            await state.set_state(AdminState.editing_setting)
            await state.update_data(setting_key=key)
            await callback.answer()
            await callback.message.answer(
                f"Отправьте новый текст: {EDIT_LABELS[key]}.\nОтмена: /cancel"
            )
            return

        if callback.data == "admin:broadcast:cancel":
            await state.clear()
            await callback.answer("Рассылка отменена")
            await callback.message.answer("Рассылка не отправлена.")
            return

        if callback.data == "admin:broadcast:confirm":
            data = await state.get_data()
            text = data.get("broadcast_text")
            if not text:
                await callback.answer("Черновик не найден", show_alert=True)
                return
            await state.clear()
            await callback.answer("Рассылка началась")
            sent, failed = 0, 0
            for user_id in storage.user_ids():
                try:
                    await callback.bot.send_message(user_id, text, reply_markup=broadcast_keyboard())
                    sent += 1
                    await asyncio.sleep(0.04)
                except (TelegramForbiddenError, TelegramBadRequest):
                    failed += 1
                except Exception:
                    failed += 1
                    logger.exception("Broadcast failed for user %s", user_id)
            await callback.message.answer(
                f"Рассылка завершена. Отправлено: {sent}; недоступно: {failed}."
            )
            return

        await callback.answer("Неизвестная команда", show_alert=True)

    @dispatcher.message(Command("cancel"), AdminState.editing_setting)
    @dispatcher.message(Command("cancel"), AdminState.waiting_for_broadcast)
    @dispatcher.message(Command("cancel"), AdminState.confirming_broadcast)
    async def cancel(message: Message, state: FSMContext) -> None:
        if not permitted(message.from_user):
            return
        await state.clear()
        await message.answer("Отменено.")

    @dispatcher.message(AdminState.editing_setting, F.text)
    async def save_setting(message: Message, state: FSMContext) -> None:
        if not permitted(message.from_user):
            return
        text = message.text.strip()
        if not text:
            await message.answer("Текст не должен быть пустым. Или /cancel.")
            return
        data = await state.get_data()
        key = data["setting_key"]
        if key.endswith("_text") and len(text) > 64:
            await message.answer("Название кнопки не должно быть длиннее 64 символов.")
            return
        if not key.endswith("_text") and len(text) > 4096:
            await message.answer("Текст не должен быть длиннее 4096 символов.")
            return
        storage.set(key, text)
        await state.clear()
        await message.answer(f"Готово: изменено {EDIT_LABELS[key]}.")

    @dispatcher.message(AdminState.waiting_for_broadcast, F.text)
    async def preview_broadcast(message: Message, state: FSMContext) -> None:
        if not permitted(message.from_user):
            return
        text = message.text.strip()
        if not text:
            await message.answer("Текст не должен быть пустым. Или /cancel.")
            return
        if len(text) > 4096:
            await message.answer("Текст не должен быть длиннее 4096 символов.")
            return
        await state.set_state(AdminState.confirming_broadcast)
        await state.update_data(broadcast_text=text)
        await message.answer(
            f"Предпросмотр рассылки:\n\n{text}\n\n"
            f"Получателей сейчас: {storage.user_count()}",
            reply_markup=confirm_broadcast_keyboard(),
        )

    @dispatcher.message(AdminState.editing_setting)
    @dispatcher.message(AdminState.waiting_for_broadcast)
    async def text_only(message: Message) -> None:
        if permitted(message.from_user):
            await message.answer("Отправьте обычный текст без вложений или /cancel.")

    return dispatcher


async def main() -> None:
    settings = load_settings()
    storage = Storage(settings.db_path, settings.defaults)
    storage.initialize(settings.admin_usernames)
    logger.info("Admin rights synchronized for configured usernames")

    bot = Bot(token=settings.bot_token)
    dispatcher = build_dispatcher(settings, storage)
    logger.info("Bot started")
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())


"""
Онбординг нового пользователя: роль → группа → подгруппа → уведомления → подсказки
"""
from typing import Optional, List
from aiogram import Bot
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from bot.services.state_manager import state_manager
from bot.utils import (
    build_role_selection_keyboard,
    build_subgroup_keyboard,
    build_yes_no_keyboard,
    build_time_selection_keyboard,
    build_skip_keyboard,
    extract_group_from_text,
    validate_time_format,
    escape_markdown_v2,
)
from database.repository import UserRepository
from bot.services.schedule import schedule_service


class OnboardingFlow:
    """Пошаговый онбординг пользователя"""

    def __init__(self, bot: Bot, chat_id: int, user_id: int):
        self.bot = bot
        self.chat_id = chat_id
        self.user_id = user_id

    def _set_step(self, step: str, extra: Optional[dict] = None):
        data = {'action': 'onboarding', 'step': step}
        if extra:
            data.update(extra)
        state_manager.set_state(self.chat_id, self.user_id, data)

    def _update(self, data: dict):
        state_manager.update_state(self.chat_id, self.user_id, data)

    def _get_state(self) -> Optional[dict]:
        return state_manager.get_state(self.chat_id, self.user_id)

    async def start(self, session: AsyncSession):
        """Запустить онбординг с приветствием и выбором роли"""
        self._set_step('role')
        try:
            await self.bot.send_message(
                self.chat_id,
                escape_markdown_v2(
                    "👋 Привет! Помогу быстро настроить расписание. Давай начнём с роли:"
                ),
                parse_mode="MarkdownV2",
                reply_markup=build_role_selection_keyboard()
            )
        except Exception as e:
            logger.error(f"Failed to send onboarding welcome: {e}")

    async def handle_role_selected(self, session: AsyncSession, role: str, callback: Optional[CallbackQuery] = None):
        """Обработка выбора роли и переход к группе"""
        user = await UserRepository.get_by_id(session, self.user_id)
        if user:
            await UserRepository.update(session, self.user_id, role=role)
        else:
            await UserRepository.create(
                session,
                user_id=self.user_id,
                role=role
            )
        await session.commit()

        if callback:
            try:
                await callback.answer()
            except Exception:
                pass
            try:
                await callback.message.edit_text(
                    f"✅ Роль выбрана: {'👨‍🎓 Студент' if role == 'student' else '👨‍🏫 Преподаватель'}"
                )
            except Exception:
                # Если не удалось отредактировать (например, старое сообщение) — игнорируем
                pass

        await self._ask_group()

    async def _ask_group(self):
        """Попросить пользователя указать группу"""
        self._set_step('group')
        try:
            await self.bot.send_message(
                self.chat_id,
                escape_markdown_v2(
                    "Укажи свою группу в формате 241\-362.\n"
                    "Можно просто написать номер группы или команду `/add 241-362`"
                ),
                parse_mode="MarkdownV2",
                reply_markup=build_skip_keyboard("onb:skip")
            )
        except Exception as e:
            logger.error(f"Failed to send group prompt: {e}")

    async def handle_group_message(self, session: AsyncSession, message: Message):
        """Обработка ввода группы"""
        group = extract_group_from_text(message.text or '')
        if not group:
            await message.answer("❌ Не удалось распознать группу. Пример: 241-362")
            return

        # Валидация группы по наличию расписания
        schedule = await schedule_service.fetch_schedule(group)
        if not schedule:
            await message.answer("❌ Такой группы не найдено в расписании. Проверь формат и номер.")
            return

        # Сохраняем группу
        user = await UserRepository.get_by_id(session, self.user_id)
        if user:
            await UserRepository.update(session, self.user_id, group=group)
        else:
            await UserRepository.create(session, user_id=self.user_id, group=group)
        await session.commit()

        await message.answer(f"✅ Группа {group} сохранена")
        await self._ask_subgroup()

    async def _ask_subgroup(self):
        self._set_step('subgroup')
        try:
            await self.bot.send_message(
                self.chat_id,
                "Выбери подгруппу (если есть):",
                reply_markup=build_subgroup_keyboard(prefix="subg_onb")
            )
        except Exception as e:
            logger.error(f"Failed to send subgroup prompt: {e}")

    async def handle_subgroup_callback(self, session: AsyncSession, callback: CallbackQuery, subgroup_raw: str):
        try:
            await callback.answer()
        except Exception:
            pass

        if subgroup_raw == 'back':
            await self._ask_group()
            return

        try:
            subgroup = int(subgroup_raw)
        except ValueError:
            subgroup = None

        if subgroup is not None:
            if subgroup == 0:
                await UserRepository.update(session, self.user_id, subgroup=None)
            elif subgroup in (1, 2):
                await UserRepository.update(session, self.user_id, subgroup=subgroup)
            await session.commit()

        try:
            await callback.message.edit_text(
                f"✅ Подгруппа: {'Все' if not subgroup or subgroup == 0 else subgroup}"
            )
        except Exception:
            pass

        await self._ask_daily_notifications()

    async def _ask_daily_notifications(self):
        self._set_step('daily')
        try:
            await self.bot.send_message(
                self.chat_id,
                "Включить ежедневные уведомления с расписанием?",
                reply_markup=build_yes_no_keyboard(
                    yes_callback="onb:daily:yes",
                    no_callback="onb:daily:no"
                )
            )
        except Exception as e:
            logger.error(f"Failed to send daily notify prompt: {e}")

    async def handle_daily_choice(self, session: AsyncSession, choice: str, callback: CallbackQuery):
        try:
            await callback.answer()
        except Exception:
            pass

        enabled = choice == 'yes'
        await UserRepository.update(session, self.user_id, daily_notify_enabled=enabled)
        await session.commit()

        if enabled:
            await self._ask_time()
        else:
            await self._ask_online_notifications()

    async def _ask_time(self):
        self._set_step('time')
        try:
            await self.bot.send_message(
                self.chat_id,
                "Во сколько присылать расписание? Выбери время или укажи своё в формате HH:MM",
                reply_markup=build_time_selection_keyboard(["08:00", "20:00"], callback_prefix="onb:time")
            )
        except Exception as e:
            logger.error(f"Failed to send time prompt: {e}")

    async def handle_time_callback(self, session: AsyncSession, callback: CallbackQuery, token: str):
        try:
            await callback.answer()
        except Exception:
            pass

        if token == 'custom':
            self._set_step('time_custom')
            try:
                await self.bot.send_message(
                    self.chat_id,
                    "Напиши время в формате HH:MM",
                    reply_markup=build_skip_keyboard("onb:skip")
                )
            except Exception:
                pass
            return

        # Предустановленное время
        await UserRepository.update(session, self.user_id, notification_time=token)
        await session.commit()
        try:
            await callback.message.edit_text(f"✅ Время уведомлений: {token}")
        except Exception:
            pass
        await self._ask_online_notifications()

    async def handle_time_message(self, session: AsyncSession, message: Message):
        time_str = (message.text or '').strip()
        if not validate_time_format(time_str):
            await message.answer("❌ Некорректное время. Пример: 08:00")
            return
        await UserRepository.update(session, self.user_id, notification_time=time_str)
        await session.commit()
        await message.answer(f"✅ Время уведомлений: {time_str}")
        await self._ask_online_notifications()

    async def _ask_online_notifications(self):
        self._set_step('online')
        try:
            await self.bot.send_message(
                self.chat_id,
                "Сообщать отдельно об онлайн-парах?",
                reply_markup=build_yes_no_keyboard(
                    yes_callback="onb:online:yes",
                    no_callback="onb:online:no"
                )
            )
        except Exception as e:
            logger.error(f"Failed to send online notify prompt: {e}")

    async def handle_online_choice(self, session: AsyncSession, choice: str, callback: CallbackQuery):
        try:
            await callback.answer()
        except Exception:
            pass

        enabled = choice == 'yes'
        await UserRepository.update(session, self.user_id, notify_online=enabled)
        await session.commit()
        await self.finish(session)

    async def skip(self):
        await self.bot.send_message(
            self.chat_id,
            "⏭ Онбординг пропущен. Настройки можно изменить в /settings"
        )
        state_manager.delete_state(self.chat_id, self.user_id)

    async def finish(self, session: AsyncSession):
        # Отмечаем завершение tutorial/онбординга
        await UserRepository.update(session, self.user_id, tutorial_completed=True)
        await session.commit()

        # Выводим подсказки
        try:
            tips = (
                "🎉 Готово! Вот быстрые команды:\n"
                "• /day — расписание на сегодня\n"
                "• /cur — текущая пара\n"
                "• /help — все возможности\n"
                "\nИзменить настройки: /settings"
            )
            await self.bot.send_message(self.chat_id, tips)
        except Exception:
            pass
        state_manager.delete_state(self.chat_id, self.user_id)

    async def process_callback(self, session: AsyncSession, callback: CallbackQuery) -> bool:
        """Общий обработчик callback-ов онбординга"""
        data = callback.data or ''
        if not data.startswith('onb:'):
            return False

        parts = data.split(':')
        # onb:daily:yes|no; onb:time:08:00|custom; onb:online:yes|no; onb:skip
        if len(parts) == 2 and parts[1] == 'skip':
            await self.skip()
            return True

        if len(parts) >= 3:
            kind = parts[1]
            value = ':'.join(parts[2:])
            if kind == 'daily':
                await self.handle_daily_choice(session, value, callback)
                return True
            if kind == 'time':
                await self.handle_time_callback(session, callback, value)
                return True
            if kind == 'online':
                await self.handle_online_choice(session, value, callback)
                return True

        return False

    async def process_message(self, session: AsyncSession, message: Message) -> bool:
        """Обработка пользовательских сообщений на шагах онбординга"""
        state = self._get_state()
        if not state or state.get('action') != 'onboarding':
            return False

        step = state.get('step')
        if step == 'group':
            await self.handle_group_message(session, message)
            return True
        if step == 'time_custom':
            await self.handle_time_message(session, message)
            return True
        return False



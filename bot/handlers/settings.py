"""
Хэндлеры для настроек пользователя
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from database.repository import UserRepository, ChatRepository
from bot.utils import build_settings_keyboard, build_subgroup_keyboard
from bot.services.state_manager import state_manager


router = Router()

def _format_settings_text(
    daily_notify: bool,
    notify_online: bool,
    notification_time: str | None,
    subgroup: int | None
) -> str:
    text = "⚙️ Настройки уведомлений\n\n"
    text += f"Ежедневные: {'✅ Вкл' if daily_notify else '❌ Выкл'}\n"
    if daily_notify and notification_time:
        text += f"Время: {notification_time}\n"
    text += f"Онлайн-пары: {'✅ Вкл' if notify_online else '❌ Выкл'}\n"
    if subgroup:
        text += f"Подгруппа: {subgroup}\n"
    return text


@router.message(Command("settings"))
async def cmd_settings(message: Message, session: AsyncSession, keyboard_cleanup_service=None):
    """Команда /settings - настройки уведомлений"""
    # В callback'ах message.from_user может быть ботом (сообщение настроек от бота).
    # В приватных чатах идентификатор пользователя равен chat.id, используем его.
    chat_id = message.chat.id
    user_id = message.from_user.id if message.chat.type in ['group', 'supergroup'] else chat_id
    
    # Получаем настройки
    if message.chat.type in ['group', 'supergroup']:
        chat = await ChatRepository.get_by_id(session, chat_id)
        if not chat:
            await message.answer("❌ Сначала установите группу командой /add")
            return
        
        daily_notify = chat.daily_notify_enabled
        notify_online = chat.notify_online
        notification_time = chat.notification_time
        subgroup = None
    else:
        user = await UserRepository.get_by_id(session, user_id)
        if not user or not user.group:
            await message.answer("❌ Сначала установите группу командой /add")
            return
        
        daily_notify = user.daily_notify_enabled
        notify_online = user.notify_online
        notification_time = user.notification_time
        subgroup = user.subgroup
    
    # Формируем текст
    text = _format_settings_text(
        daily_notify,
        notify_online,
        notification_time,
        subgroup
    )
    
    keyboard = build_settings_keyboard(
        daily_notify,
        notify_online,
        notification_time,
        subgroup
    )
    
    sent = await message.answer(text, reply_markup=keyboard)
    # Планируем очистку клавиатуры по TTL (если сервис доступен)
    if keyboard_cleanup_service:
        await keyboard_cleanup_service.schedule_clear(sent.chat.id, sent.message_id)


@router.callback_query(F.data.startswith("settings:"))
async def process_settings_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    keyboard_cleanup_service=None
):
    """Обработка callback'ов настроек"""
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    action = callback.data.split(":")[1]
    
    is_group_chat = callback.message.chat.type in ['group', 'supergroup']
    
    if action == "toggle_daily":
        # Переключить ежедневные уведомления
        if is_group_chat:
            chat = await ChatRepository.get_by_id(session, chat_id)
            new_value = not chat.daily_notify_enabled
            await ChatRepository.update(
                session,
                chat_id,
                daily_notify_enabled=new_value
            )
            daily_notify = new_value
            notify_online = chat.notify_online
            notification_time = chat.notification_time
            subgroup = None
        else:
            user = await UserRepository.get_by_id(session, user_id)
            new_value = not user.daily_notify_enabled
            await UserRepository.update(
                session,
                user_id,
                daily_notify_enabled=new_value
            )
            daily_notify = new_value
            notify_online = user.notify_online
            notification_time = user.notification_time
            subgroup = user.subgroup
        
        await callback.answer(
            f"Ежедневные уведомления {'включены' if new_value else 'выключены'}"
        )
        await callback.message.edit_text(
            _format_settings_text(daily_notify, notify_online, notification_time, subgroup),
            reply_markup=build_settings_keyboard(daily_notify, notify_online, notification_time, subgroup)
        )
        if keyboard_cleanup_service:
            await keyboard_cleanup_service.schedule_clear(chat_id, callback.message.message_id)
    
    elif action == "toggle_online":
        # Переключить уведомления об онлайн-парах
        if is_group_chat:
            chat = await ChatRepository.get_by_id(session, chat_id)
            new_value = not chat.notify_online
            await ChatRepository.update(
                session,
                chat_id,
                notify_online=new_value
            )
            daily_notify = chat.daily_notify_enabled
            notify_online = new_value
            notification_time = chat.notification_time
            subgroup = None
        else:
            user = await UserRepository.get_by_id(session, user_id)
            new_value = not user.notify_online
            await UserRepository.update(
                session,
                user_id,
                notify_online=new_value
            )
            daily_notify = user.daily_notify_enabled
            notify_online = new_value
            notification_time = user.notification_time
            subgroup = user.subgroup
        
        await callback.answer(
            f"Уведомления об онлайн-парах {'включены' if new_value else 'выключены'}"
        )
        await callback.message.edit_text(
            _format_settings_text(daily_notify, notify_online, notification_time, subgroup),
            reply_markup=build_settings_keyboard(daily_notify, notify_online, notification_time, subgroup)
        )
        if keyboard_cleanup_service:
            await keyboard_cleanup_service.schedule_clear(chat_id, callback.message.message_id)
    
    elif action == "change_time":
        # Изменить время уведомлений
        state_manager.set_state(chat_id, user_id, {
            'action': 'changing_notify_time'
        })
        
        sent = await callback.message.answer(
            "🕐 Укажи время для ежедневных уведомлений в формате ЧЧ:ММ\n"
            "Например: 08:00"
        )
        if keyboard_cleanup_service:
            # На этом сообщении клавиатуры нет, но если появится — очистим
            await keyboard_cleanup_service.schedule_clear(sent.chat.id, sent.message_id)
        await callback.answer()
        return
    
    elif action == "change_subgroup":
        # Изменить подгруппу
        if is_group_chat:
            await callback.answer("Подгруппы доступны только в личных чатах")
            return
        
        await callback.message.edit_text(
            "👥 Выбери свою подгруппу:",
            reply_markup=build_subgroup_keyboard()
        )
        if keyboard_cleanup_service:
            await keyboard_cleanup_service.schedule_clear(chat_id, callback.message.message_id)
        await callback.answer()
        return
    
    elif action == "close":
        # Закрыть настройки
        await callback.message.delete()
        await callback.answer()
        return
    
    # Для остальных действий ответ уже отправлен выше
    # и сообщение отредактировано при необходимости


@router.callback_query(F.data.startswith("subgroup:"))
async def process_subgroup_callback(
    callback: CallbackQuery,
    session: AsyncSession
):
    """Обработка выбора подгруппы"""
    user_id = callback.from_user.id
    action = callback.data.split(":")[1]
    
    if action == "back":
        await cmd_settings(callback.message, session)
        await callback.answer()
        return
    
    # Устанавливаем подгруппу
    subgroup = int(action) if action != "0" else None
    
    await UserRepository.update(session, user_id, subgroup=subgroup)
    
    await callback.answer(
        f"Подгруппа {'не выбрана' if not subgroup else subgroup}"
    )
    
    # Возвращаемся к настройкам
    await cmd_settings(callback.message, session)


@router.message(F.text.regexp(r'^\d{2}:\d{2}$'))
async def process_notification_time(message: Message, session: AsyncSession):
    """Обработка времени уведомлений"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    state = state_manager.get_state(chat_id, user_id)
    if not state or state.get('action') != 'changing_notify_time':
        return
    
    time_str = message.text
    
    # Сохраняем время
    if message.chat.type in ['group', 'supergroup']:
        await ChatRepository.update(session, chat_id, notification_time=time_str)
    else:
        await UserRepository.update(session, user_id, notification_time=time_str)
    
    state_manager.delete_state(chat_id, user_id)
    
    await message.answer(f"✅ Время уведомлений установлено: {time_str}")
    
    # Показываем обновленные настройки
    await cmd_settings(message, session)

"""
Хэндлеры для администраторов
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta

from database.repository import BanRepository, UserRepository, ChatRepository
from database.models import User, Chat, Holiday
from bot.middleware.auth import check_permission
from config import AdminPermissions
from bot.utils import extract_group_from_text, StateFilter
from bot.services.state_manager import state_manager
from bot.utils.message_queue import MessageQueue, MessagePriority
from loguru import logger

router = Router()


@router.message(Command("ban_user"))
async def cmd_ban_user(
    message: Message,
    session: AsyncSession,
    is_global_admin: bool
):
    """Команда /ban_user - забанить пользователя"""
    # Проверка прав
    if not is_global_admin:
        has_perm = await check_permission(
            AdminPermissions.BAN_USER,
            {'is_global_admin': is_global_admin, 'user_id': message.from_user.id},
            session
        )
        if not has_perm:
            await message.answer("🛡️ У вас нет прав для этой команды")
            return
    
    # Парсинг команды: /ban_user @username|id [минуты]
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "Использование: /ban_user @username|id [минуты]\n"
            "Пример: /ban_user @username 60"
        )
        return
    
    target = parts[1]
    duration = int(parts[2]) if len(parts) > 2 else 60
    
    # Определяем user_id
    if target.startswith('@'):
        # По username
        username = target[1:]
        user = await session.execute(
            select(User).where(User.username == username)
        )
        user = user.scalar_one_or_none()
        if not user:
            await message.answer(f"❌ Пользователь {target} не найден")
            return
        user_id = user.userid
    else:
        # По ID
        try:
            user_id = int(target)
        except ValueError:
            await message.answer("❌ Неверный формат ID")
            return
    
    # Баним
    ban_until = int((datetime.now() + timedelta(minutes=duration)).timestamp() * 1000)
    await BanRepository.create(session, user_id, ban_until)
    await session.commit()
    
    await message.answer(
        f"✅ Пользователь {target} забанен на {duration} минут"
    )


@router.message(Command("unban_user"))
async def cmd_unban_user(
    message: Message,
    session: AsyncSession,
    is_global_admin: bool
):
    """Команда /unban_user - разбанить пользователя"""
    if not is_global_admin:
        has_perm = await check_permission(
            AdminPermissions.UNBAN_USER,
            {'is_global_admin': is_global_admin, 'user_id': message.from_user.id},
            session
        )
        if not has_perm:
            await message.answer("🛡️ У вас нет прав для этой команды")
            return
    
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /unban_user @username|id")
        return
    
    target = parts[1]
    
    # Определяем user_id
    if target.startswith('@'):
        username = target[1:]
        user = await session.execute(
            select(User).where(User.username == username)
        )
        user = user.scalar_one_or_none()
        if not user:
            await message.answer(f"❌ Пользователь {target} не найден")
            return
        user_id = user.userid
    else:
        try:
            user_id = int(target)
        except ValueError:
            await message.answer("❌ Неверный формат ID")
            return
    
    # Разбаниваем
    await BanRepository.delete(session, user_id)
    await session.commit()
    
    await message.answer(f"✅ Пользователь {target} разбанен")


@router.message(Command("list_bans"))
async def cmd_list_bans(
    message: Message,
    session: AsyncSession,
    is_global_admin: bool
):
    """Команда /list_bans - список активных банов"""
    if not is_global_admin:
        has_perm = await check_permission(
            AdminPermissions.LIST_BANS,
            {'is_global_admin': is_global_admin, 'user_id': message.from_user.id},
            session
        )
        if not has_perm:
            await message.answer("🛡️ У вас нет прав для этой команды")
            return
    
    current_timestamp = int(datetime.now().timestamp() * 1000)
    bans = await BanRepository.get_all_active(session, current_timestamp)
    
    if not bans:
        await message.answer("Активных банов нет")
        return
    
    text = "📋 Активные баны:\n\n"
    for ban in bans:
        ban_until = datetime.fromtimestamp(ban.ban_until / 1000)
        text += f"• ID {ban.userid} до {ban_until.strftime('%d.%m.%Y %H:%M')}\n"
    
    await message.answer(text)


@router.message(Command("broadcast"))
async def cmd_broadcast(
    message: Message,
    is_global_admin: bool
):
    """Команда /broadcast - рассылка сообщений"""
    if not is_global_admin:
        await message.answer("🛡️ Эта команда доступна только администраторам")
        return
    
    await message.answer(
        "📢 Функция рассылки\n\n"
        "Отправь следующее сообщение, которое будет разослано всем пользователям.\n"
        "Используй /cancel для отмены."
    )
    
    state_manager.set_state(message.chat.id, message.from_user.id, {
        'action': 'awaiting_broadcast'
    })


@router.message(Command("cancel"))
async def cmd_cancel(message: Message):
    """Команда /cancel - отмена текущего действия"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    state = state_manager.get_state(chat_id, user_id)
    if not state:
        await message.answer("❌ Нет активных действий для отмены")
        return
    
    action = state.get('action')
    
    # Удаляем состояние
    state_manager.delete_state(chat_id, user_id)
    
    if action == 'awaiting_broadcast':
        await message.answer("✅ Рассылка отменена")
    elif action == 'awaiting_compare_groups':
        await message.answer("✅ Сравнение групп отменено")
    elif action == 'compare_teacher':
        await message.answer("✅ Сравнение с преподавателем отменено")
    else:
        await message.answer("✅ Действие отменено")


@router.message(Command("stat"))
async def cmd_stat(
    message: Message,
    session: AsyncSession,
    is_global_admin: bool
):
    """Команда /stat - статистика бота"""
    if not is_global_admin:
        has_perm = await check_permission(
            AdminPermissions.STAT_COMMAND,
            {'is_global_admin': is_global_admin, 'user_id': message.from_user.id},
            session
        )
        if not has_perm:
            await message.answer("🛡️ У вас нет прав для этой команды")
            return
    # Считаем статистику
    try:
        total_users = await session.scalar(select(func.count(User.userid)))
        total_chats = await session.scalar(select(func.count(Chat.chatid)))
        users_with_group = await session.scalar(
            select(func.count(User.userid)).where(User.group != "")
        )
        text = (
            f"📊 Статистика бота\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"💬 Всего чатов: {total_chats}\n"
            f"✅ Пользователей с группой: {users_with_group}\n"
        )
    except Exception as e:
        text = (
            f"📊 Статистика бота\n\n"
            f"❌ Ошибка подключения к базе данных\n"
            f"Детали: {str(e)}\n\n"
            f"Убедитесь, что:\n"
            f"• База данных запущена\n"
            f"• Настройки подключения корректны\n"
            f"• Миграции применены"
        )
    
    await message.answer(text)


@router.message(Command("add_holidays"))
async def cmd_add_holidays(
    message: Message,
    session: AsyncSession,
    is_global_admin: bool
):
    """Команда /add_holidays - добавить каникулы"""
    if not is_global_admin:
        has_perm = await check_permission(
            AdminPermissions.ADD_HOLIDAYS,
            {'is_global_admin': is_global_admin, 'user_id': message.from_user.id},
            session
        )
        if not has_perm:
            await message.answer("🛡️ У вас нет прав для этой команды")
            return
    
    # Формат: /add_holidays <group|all> DD.MM.YYYY DD.MM.YYYY <type>
    parts = message.text.split(maxsplit=4)
    if len(parts) < 5:
        await message.answer(
            "Использование: /add_holidays &lt;group|all&gt; DD.MM.YYYY DD.MM.YYYY &lt;тип&gt;\n"
            "Пример: /add_holidays 241-362 01.01.2024 10.01.2024 Зимние каникулы"
        )
        return
    
    group = parts[1]
    start_date = parts[2]
    end_date = parts[3]
    holiday_type = parts[4]
    
    holiday = Holiday(
        group=group,
        start_date=start_date,
        end_date=end_date,
        type=holiday_type
    )
    session.add(holiday)
    await session.commit()
    
    await message.answer(
        f"✅ Каникулы добавлены:\n"
        f"Группа: {group}\n"
        f"Период: {start_date} - {end_date}\n"
        f"Тип: {holiday_type}"
    )


@router.message(StateFilter(['awaiting_broadcast']))
async def process_broadcast_message(
    message: Message,
    session: AsyncSession,
    message_queue: MessageQueue
):
    """Обработка сообщения для рассылки"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    logger.info(f"Processing broadcast message from user {user_id}")
    
    state = state_manager.get_state(chat_id, user_id)
    if not state:
        logger.warning(f"No state found for user {user_id}")
        return
    
    # Удаляем состояние
    state_manager.delete_state(chat_id, user_id)
    
    try:
        # Получаем всех пользователей
        users = await session.execute(select(User).where(User.userid.isnot(None)))
        users = list(users.scalars().all())
        
        # Получаем все чаты
        chats = await session.execute(select(Chat).where(Chat.chatid.isnot(None)))
        chats = list(chats.scalars().all())
        
        total_recipients = len(users) + len(chats)
        logger.info(f"Broadcast: {len(users)} users, {len(chats)} chats, total: {total_recipients}")
        
        if total_recipients == 0:
            await message.answer("❌ Нет получателей для рассылки")
            return
        
        # Отправляем сообщение всем пользователям
        sent_count = 0
        failed_count = 0
        
        # Отправляем пользователям
        for user in users:
            try:
                if message.text:
                    await message_queue.enqueue(
                        message.bot.send_message,
                        user.userid,
                        message.text,
                        priority=MessagePriority.NORMAL
                    )
                elif message.photo:
                    await message_queue.enqueue(
                        message.bot.send_photo,
                        user.userid,
                        photo=message.photo[-1].file_id,
                        caption=message.caption,
                        priority=MessagePriority.NORMAL
                    )
                elif message.video:
                    await message_queue.enqueue(
                        message.bot.send_video,
                        user.userid,
                        video=message.video.file_id,
                        caption=message.caption,
                        priority=MessagePriority.NORMAL
                    )
                elif message.document:
                    await message_queue.enqueue(
                        message.bot.send_document,
                        user.userid,
                        document=message.document.file_id,
                        caption=message.caption,
                        priority=MessagePriority.NORMAL
                    )
                else:
                    # Для других типов медиа отправляем как есть
                    await message_queue.enqueue(
                        message.bot.copy_message,
                        user.userid,
                        chat_id,
                        message.message_id,
                        priority=MessagePriority.NORMAL
                    )
                sent_count += 1
            except Exception as e:
                logger.error(f"Failed to enqueue broadcast to user {user.userid}: {e}")
                failed_count += 1
        
        # Отправляем чатам
        for chat in chats:
            try:
                if message.text:
                    await message_queue.enqueue(
                        message.bot.send_message,
                        chat.chatid,
                        message.text,
                        priority=MessagePriority.NORMAL
                    )
                elif message.photo:
                    await message_queue.enqueue(
                        message.bot.send_photo,
                        chat.chatid,
                        photo=message.photo[-1].file_id,
                        caption=message.caption,
                        priority=MessagePriority.NORMAL
                    )
                elif message.video:
                    await message_queue.enqueue(
                        message.bot.send_video,
                        chat.chatid,
                        video=message.video.file_id,
                        caption=message.caption,
                        priority=MessagePriority.NORMAL
                    )
                elif message.document:
                    await message_queue.enqueue(
                        message.bot.send_document,
                        chat.chatid,
                        document=message.document.file_id,
                        caption=message.caption,
                        priority=MessagePriority.NORMAL
                    )
                else:
                    # Для других типов медиа отправляем как есть
                    await message_queue.enqueue(
                        message.bot.copy_message,
                        chat.chatid,
                        chat_id,
                        message.message_id,
                        priority=MessagePriority.NORMAL
                    )
                sent_count += 1
            except Exception as e:
                logger.error(f"Failed to enqueue broadcast to chat {chat.chatid}: {e}")
                failed_count += 1
        
        # Отправляем отчет администратору
        report = f"📢 Рассылка завершена!\n\n"
        report += f"✅ Успешно отправлено: {sent_count}\n"
        if failed_count > 0:
            report += f"❌ Ошибок: {failed_count}\n"
        report += f"📊 Всего получателей: {total_recipients}"
        
        await message.answer(report)
        
    except Exception as e:
        logger.error(f"Error in broadcast: {e}")
        await message.answer(f"❌ Ошибка при рассылке: {str(e)}")

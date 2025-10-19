"""
Основные хэндлеры команд
"""
import re
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta

from database.repository import UserRepository, ChatRepository
from bot.services.schedule import schedule_service
from bot.services.tutorial import Tutorial
from bot.services.state_manager import state_manager
from bot.utils import (
    extract_group_from_text,
    build_role_selection_keyboard
)
from loguru import logger


router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, session: AsyncSession):
    """Команда /start"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Проверяем, существует ли пользователь
    user = await UserRepository.get_by_id(session, user_id)
    
    if user and user.group:
        # Пользователь уже зарегистрирован
        await message.answer(
            f"👋 С возвращением! Твоя группа: {user.group}\n"
            f"Используй /help для списка команд."
        )
        return
    
    # Новый пользователь - предлагаем выбрать роль
    await message.answer(
        "👋 Привет! Я бот для управления расписанием.\n"
        "Давай начнем с выбора твоей роли:",
        reply_markup=build_role_selection_keyboard()
    )
    
    # Устанавливаем состояние
    state_manager.set_state(chat_id, user_id, {
        'action': 'choose_role'
    })


@router.callback_query(F.data.startswith("role:"))
async def process_role_selection(callback: CallbackQuery, session: AsyncSession):
    """Обработка выбора роли"""
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    role = callback.data.split(":")[1]
    
    # Создаем или обновляем пользователя
    user = await UserRepository.get_by_id(session, user_id)
    if user:
        await UserRepository.update(session, user_id, role=role)
    else:
        await UserRepository.create(
            session,
            user_id=user_id,
            role=role,
            username=callback.from_user.username
        )
    
    await callback.answer()
    await callback.message.edit_text(
        f"✅ Отлично! Ты выбрал роль: {'👨‍🎓 Студент' if role == 'student' else '👨‍🏫 Преподаватель'}\n\n"
        f"Теперь укажи свою группу командой:\n"
        f"/add 241-362"
    )
    
    state_manager.delete_state(chat_id, user_id)


@router.message(Command("help"))
async def cmd_help(message: Message, is_global_admin: bool = False):
    """Команда /help"""
    help_text = """
📚 *Доступные команды:*

*Расписание:*
/day — расписание на сегодня
/nextday — расписание на завтра
/cur — текущее занятие
/date \\[группа\\] ДД\\.ММ\\.ГГГГ — расписание на дату

*Управление:*
/add 000\\-000 — установить свою группу
/change\\_group 000\\-000 — изменить группу
/settings — настройки уведомлений

*Другое:*
/compare\\_groups — сравнить расписания групп
  \\(укажи группы и минуты\\)
/feedback — отправить отзыв
"""
    
    if is_global_admin:
        help_text += """
*Администрирование:*
/asks — просмотр фидбеков
/ban\\_user — забанить пользователя
/unban\\_user — разбанить
/list\\_bans — список банов
/broadcast — рассылка
/add\\_holidays — добавить каникулы
/stat — статистика
"""
    
    await message.answer(
        help_text.strip(),
        parse_mode="MarkdownV2"
    )


@router.message(Command("add"))
async def cmd_add_group(message: Message, session: AsyncSession):
    """Команда /add для установки группы"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Извлекаем группу из команды
    text = message.text
    group = extract_group_from_text(text)
    
    if not group:
        await message.answer(
            "❌ Укажи группу в формате: /add 241-362"
        )
        return
    
    # TODO: Проверить валидность группы через API
    
    # Для группового чата - только админы
    if message.chat.type in ['group', 'supergroup']:
        from bot.middleware.auth import is_group_admin
        if not await is_group_admin(message):
            await message.answer(
                "🔑 Только администраторы группового чата могут устанавливать группу."
            )
            return
        
        # Сохраняем в чат
        thread_id = getattr(message, 'message_thread_id', None)
        chat = await ChatRepository.get_by_id(session, chat_id)
        if chat:
            await ChatRepository.update(session, chat_id, group=group, thread_id=thread_id)
        else:
            await ChatRepository.create(session, chat_id, group, thread_id=thread_id)
        
        await session.commit()
        await message.answer(f"✅ Группа {group} установлена для этого чата!")
    else:
        # Личный чат - сохраняем пользователю
        user = await UserRepository.get_by_id(session, user_id)
        if user:
            await UserRepository.update(session, user_id, group=group)
        else:
            await UserRepository.create(
                session,
                user_id=user_id,
                group=group,
                username=message.from_user.username
            )
        
        await session.commit()
        await message.answer(
            f"✅ Группа {group} сохранена!\n"
            f"Теперь можешь использовать команды расписания."
        )
        
        # Запускаем обучение, если пользователь новый
        if not user or not user.tutorial_completed:
            await UserRepository.update(session, user_id, tutorial_completed=True)
            
            tutorial = Tutorial(message.bot, chat_id, user_id)
            await tutorial.start()


@router.message(Command("change_group"))
async def cmd_change_group(message: Message, session: AsyncSession):
    """Команда /change_group для смены группы"""
    # Аналогично cmd_add_group
    await cmd_add_group(message, session)


@router.message(Command("day"))
async def cmd_day(message: Message, session: AsyncSession):
    """Команда /day - расписание на сегодня"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Извлекаем группу из команды или берем из БД
    text = message.text
    group = extract_group_from_text(text)
    
    if not group:
        # Берем из БД
        if message.chat.type in ['group', 'supergroup']:
            chat = await ChatRepository.get_by_id(session, chat_id)
            group = chat.group if chat else None
        else:
            user = await UserRepository.get_by_id(session, user_id)
            group = user.group if user else None
    
    if not group:
        await message.answer(
            "📚 Поли не знает, к какой группе ты принадлежишь! "
            "Напиши команду /add, чтобы всё настроить"
        )
        return
    
    # Получаем расписание
    today = datetime.now()
    
    # Получаем подгруппу пользователя
    user = await UserRepository.get_by_id(session, user_id)
    subgroup = user.subgroup if user else None
    
    response = await schedule_service.get_day_response(
        session,
        group,
        today,
        subgroup
    )
    
    await message.answer(response)


@router.message(Command("nextday"))
async def cmd_nextday(message: Message, session: AsyncSession):
    """Команда /nextday - расписание на завтра"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Извлекаем группу
    text = message.text
    group = extract_group_from_text(text)
    
    if not group:
        if message.chat.type in ['group', 'supergroup']:
            chat = await ChatRepository.get_by_id(session, chat_id)
            group = chat.group if chat else None
        else:
            user = await UserRepository.get_by_id(session, user_id)
            group = user.group if user else None
    
    if not group:
        await message.answer(
            "📚 Поли не знает, к какой группе ты принадлежишь! "
            "Напиши команду /add, чтобы всё настроить"
        )
        return
    
    # Получаем расписание на завтра
    tomorrow = datetime.now() + timedelta(days=1)
    
    user = await UserRepository.get_by_id(session, user_id)
    subgroup = user.subgroup if user else None
    
    response = await schedule_service.get_day_response(
        session,
        group,
        tomorrow,
        subgroup
    )
    
    await message.answer(response)


@router.message(Command("cur"))
async def cmd_current(message: Message, session: AsyncSession):
    """Команда /cur - текущее занятие"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Извлекаем группу
    text = message.text
    group = extract_group_from_text(text)
    
    if not group:
        if message.chat.type in ['group', 'supergroup']:
            chat = await ChatRepository.get_by_id(session, chat_id)
            group = chat.group if chat else None
        else:
            user = await UserRepository.get_by_id(session, user_id)
            group = user.group if user else None
    
    if not group:
        await message.answer(
            "📚 Поли не знает, к какой группе ты принадлежишь! "
            "Напиши команду /add, чтобы всё настроить"
        )
        return
    
    # Получаем текущее занятие
    response = await schedule_service.get_current_lesson(session, group)
    
    await message.answer(response)


@router.message(Command("date"))
async def cmd_date(message: Message, session: AsyncSession):
    """Команда /date - расписание на конкретную дату"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Извлекаем группу и дату из команды
    text = message.text
    group = extract_group_from_text(text)
    
    # Парсим дату в формате ДД.ММ.ГГГГ или Д.М.ГГГГ
    date_pattern = r'\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b'
    date_match = re.search(date_pattern, text)
    
    if not date_match:
        await message.answer(
            "❌ Укажи дату в формате: /date [группа] ДД.ММ.ГГГГ\n"
            "Примеры:\n"
            "• /date 15.12.2025\n"
            "• /date 241-362 15.12.2025"
        )
        return
    
    # Парсим дату
    try:
        day, month, year = date_match.groups()
        target_date = datetime(int(year), int(month), int(day))
    except (ValueError, TypeError):
        await message.answer(
            "❌ Некорректная дата. Используй формат ДД.ММ.ГГГГ\n"
            "Например: /date 15.12.2025"
        )
        return
    
    # Если группа не указана в команде, берем из БД
    if not group:
        if message.chat.type in ['group', 'supergroup']:
            chat = await ChatRepository.get_by_id(session, chat_id)
            group = chat.group if chat else None
        else:
            user = await UserRepository.get_by_id(session, user_id)
            group = user.group if user else None
    
    if not group:
        await message.answer(
            "📚 Поли не знает, к какой группе ты принадлежишь! "
            "Напиши команду /add, чтобы всё настроить, "
            "или укажи группу в команде: /date 241-362 15.12.2025"
        )
        return
    
    # Получаем расписание на указанную дату
    # Получаем подгруппу пользователя
    user = await UserRepository.get_by_id(session, user_id)
    subgroup = user.subgroup if user else None
    
    response = await schedule_service.get_day_response(
        session,
        group,
        target_date,
        subgroup
    )
    
    await message.answer(response)


@router.message(Command("compare_groups"))
async def cmd_compare_groups(message: Message, session: AsyncSession):
    """Команда /compare_groups - сравнить расписания групп"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Парсим команду: /compare_groups 241-362 241-365 [минуты] [дата]
    parts = message.text.split()
    
    # Извлекаем группы из текста
    group_pattern = r'\b\d{3}-\d{3}\b'
    groups = re.findall(group_pattern, message.text)
    
    if len(groups) < 2:
        # Интерактивный режим
        await message.answer(
            "📊 Сравнение расписаний групп\n\n"
            "Отправь номера групп для сравнения через пробел.\n"
            "Можно также указать минимальную длительность окна (в минутах) и дату.\n\n"
            "Примеры:\n"
            "• 221-361 221-365\n"
            "• 221-361 221-365 60\n"
            "• 221-361 221-365 60 15.10.2025\n"
            "• 221-361 221-365 60 8.10.2025-13.10.2025\n\n"
            "⚠️ Учитываются локации: группы могут встретиться, только если находятся в одном корпусе.\n\n"
            "Используй /cancel для отмены."
        )
        state_manager.set_state(chat_id, user_id, {
            'action': 'awaiting_compare_groups'
        })
        return
    
    # Прямой режим - сразу сравниваем
    # Определяем дату (по умолчанию сегодня)
    date = datetime.now()
    min_duration = 0
    
    # Проверяем, есть ли дата или период в команде (формат ДД.ММ.ГГГГ или Д.М.ГГГГ)
    # Поддержка периодов: 08.10.2025-13.10.2025
    date_pattern = r'\b\d{1,2}\.\d{1,2}\.\d{4}\b'
    date_matches = re.findall(date_pattern, message.text)
    date_range = None
    if date_matches:
        try:
            # Проверяем, есть ли период (дефис между датами)
            period_pattern = r'\b\d{1,2}\.\d{1,2}\.\d{4}\s*-\s*\d{1,2}\.\d{1,2}\.\d{4}\b'
            period_match = re.search(period_pattern, message.text)
            
            if period_match and len(date_matches) >= 2:
                # Парсим период
                start_date = datetime.strptime(date_matches[0], "%d.%m.%Y")
                end_date = datetime.strptime(date_matches[1], "%d.%m.%Y")
                
                # Проверяем, что период не более 10 дней
                days_diff = (end_date - start_date).days
                if days_diff < 0:
                    await message.answer("❌ Начальная дата должна быть раньше конечной")
                    return
                if days_diff > 9:  # 10 дней = 0-9 дней разницы
                    await message.answer("❌ Максимальный период - 10 дней")
                    return
                
                date_range = (start_date, end_date)
                date = start_date  # Используем первую дату как базовую
            else:
                # Одна дата
                date = datetime.strptime(date_matches[0], "%d.%m.%Y")
        except ValueError:
            pass
    
    # Извлекаем минимальную длительность (число без дефисов и точек)
    # Ищем числа, которые не являются частью группы или даты
    text_without_groups = message.text
    for group in groups:
        text_without_groups = text_without_groups.replace(group, '')
    for date_match in date_matches:
        text_without_groups = text_without_groups.replace(date_match, '')
    
    # Теперь ищем оставшиеся числа
    duration_pattern = r'\b(\d{1,3})\b'
    duration_matches = re.findall(duration_pattern, text_without_groups)
    if duration_matches:
        try:
            min_duration = int(duration_matches[0])
        except ValueError:
            pass
    
    # Получаем результаты сравнения
    if date_range:
        response = await schedule_service.compare_groups_period(session, groups, date_range[0], date_range[1], min_duration)
    else:
        response = await schedule_service.compare_groups(session, groups, date, min_duration)
    
    await message.answer(response)


@router.message(lambda m: state_manager.get_state(m.chat.id, m.from_user.id) and 
                state_manager.get_state(m.chat.id, m.from_user.id).get('action') == 'awaiting_compare_groups')
async def process_compare_groups(message: Message, session: AsyncSession):
    """Обработка интерактивного ввода для сравнения групп"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Удаляем состояние
    state_manager.delete_state(chat_id, user_id)
    
    # Извлекаем группы из сообщения
    group_pattern = r'\b\d{3}-\d{3}\b'
    groups = re.findall(group_pattern, message.text)
    
    if len(groups) < 2:
        await message.answer(
            "❌ Нужно указать минимум 2 группы.\n"
            "Примеры:\n"
            "• 221-361 221-365\n"
            "• 221-361 221-365 60\n"
            "• 221-361 221-365 60 15.10.2025\n"
            "• 221-361 221-365 60 8.10.2025-13.10.2025"
        )
        return
    
    # Определяем дату (по умолчанию сегодня)
    date = datetime.now()
    min_duration = 0
    
    # Проверяем, есть ли дата или период в сообщении (формат ДД.ММ.ГГГГ или Д.М.ГГГГ)
    date_pattern = r'\b\d{1,2}\.\d{1,2}\.\d{4}\b'
    date_matches = re.findall(date_pattern, message.text)
    date_range = None
    if date_matches:
        try:
            # Проверяем, есть ли период (дефис между датами)
            period_pattern = r'\b\d{1,2}\.\d{1,2}\.\d{4}\s*-\s*\d{1,2}\.\d{1,2}\.\d{4}\b'
            period_match = re.search(period_pattern, message.text)
            
            if period_match and len(date_matches) >= 2:
                # Парсим период
                start_date = datetime.strptime(date_matches[0], "%d.%m.%Y")
                end_date = datetime.strptime(date_matches[1], "%d.%m.%Y")
                
                # Проверяем, что период не более 10 дней
                days_diff = (end_date - start_date).days
                if days_diff < 0:
                    await message.answer("❌ Начальная дата должна быть раньше конечной")
                    return
                if days_diff > 9:  # 10 дней = 0-9 дней разницы
                    await message.answer("❌ Максимальный период - 10 дней")
                    return
                
                date_range = (start_date, end_date)
                date = start_date  # Используем первую дату как базовую
            else:
                # Одна дата
                date = datetime.strptime(date_matches[0], "%d.%m.%Y")
        except ValueError:
            pass
    
    # Извлекаем минимальную длительность
    text_without_groups = message.text
    for group in groups:
        text_without_groups = text_without_groups.replace(group, '')
    for date_match in date_matches:
        text_without_groups = text_without_groups.replace(date_match, '')
    
    duration_pattern = r'\b(\d{1,3})\b'
    duration_matches = re.findall(duration_pattern, text_without_groups)
    if duration_matches:
        try:
            min_duration = int(duration_matches[0])
        except ValueError:
            pass
    
    # Получаем результаты сравнения
    if date_range:
        response = await schedule_service.compare_groups_period(session, groups, date_range[0], date_range[1], min_duration)
    else:
        response = await schedule_service.compare_groups(session, groups, date, min_duration)
    
    await message.answer(response)

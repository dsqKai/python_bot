"""
Основные хэндлеры команд
"""
import re
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from contextlib import suppress

from database.repository import UserRepository, ChatRepository
from bot.services.schedule import schedule_service
from bot.services.tutorial import Tutorial
from bot.services.onboarding import OnboardingFlow
from bot.services.state_manager import state_manager
from bot.utils import (
    extract_group_from_text,
    build_role_selection_keyboard,
    build_inline_keyboard,
    StateFilter
)
from loguru import logger


router = Router()

COMPARE_TEACHER_ACTION = "compare_teacher"
MAX_COMPARE_TEACHER_PERIOD_DAYS = 10
CHANGE_DATE_CALLBACK = "ct:change_date"
SHOW_TEACHER_SCHEDULE_CALLBACK = "ct:teacher_schedule"


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
    
    # Новый пользователь — запускаем онбординг
    flow = OnboardingFlow(message.bot, chat_id, user_id)
    await flow.start(session)


@router.callback_query(F.data.startswith("role:"))
async def process_role_selection(callback: CallbackQuery, session: AsyncSession):
    """Обработка выбора роли (онбординг)"""
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    role = callback.data.split(":")[1]
    flow = OnboardingFlow(callback.bot, chat_id, user_id)
    await flow.handle_role_selected(session, role, callback)

@router.callback_query(F.data.startswith("onb:"))
async def process_onboarding_callback(callback: CallbackQuery, session: AsyncSession):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    flow = OnboardingFlow(callback.bot, chat_id, user_id)
    handled = await flow.process_callback(session, callback)
    if not handled:
        await callback.answer()


@router.callback_query(F.data.startswith("subg_onb:"))
async def process_onboarding_subgroup(callback: CallbackQuery, session: AsyncSession):
    """Хэндлер для выбора подгруппы во время онбординга"""
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    flow = OnboardingFlow(callback.bot, chat_id, user_id)
    subgroup_raw = callback.data.split(":")[1]
    await flow.handle_subgroup_callback(session, callback, subgroup_raw)


@router.message(StateFilter(['onboarding']))
async def process_onboarding_message(message: Message, session: AsyncSession):
    """Обработка сообщений на шагах онбординга (группа, время)"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    flow = OnboardingFlow(message.bot, chat_id, user_id)
    handled = await flow.process_message(session, message)
    if not handled:
        # Не мешаем остальным хэндлерам
        return


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
/compare\\_teacher — сравнить группу с преподавателем
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
        
        # Если пользователь новый — продолжим онбординг со следующего шага
        if not user or not user.tutorial_completed:
            flow = OnboardingFlow(message.bot, chat_id, user_id)
            # После сохранения группы переходим к выбору подгруппы
            await flow._ask_subgroup()


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


def _is_compare_teacher_flow(message: Message) -> bool:
    state = state_manager.get_state(message.chat.id, message.from_user.id)
    return bool(state and state.get('action') == COMPARE_TEACHER_ACTION)


def _normalize_teacher_name(value: str) -> str:
    return " ".join(value.split()) if value else ""


def _build_cancel_keyboard():
    return [[{"text": "❌ Отмена", "callback_data": "ct:cancel"}]]


def _build_compare_result_keyboard(
    include_schedule_button: bool = False
):
    buttons = []
    
    if include_schedule_button:
        buttons.append([{
            "text": "📋 Расписание преподавателя",
            "callback_data": SHOW_TEACHER_SCHEDULE_CALLBACK
        }])
    
    buttons.append([{
        "text": "🔁 Поменять дату",
        "callback_data": CHANGE_DATE_CALLBACK
    }])
    
    buttons.extend(_build_cancel_keyboard())
    return buttons


async def _send_compare_teacher_prompt(
    target_message: Message,
    text: str,
    buttons: list | None,
    keyboard_cleanup_service=None
):
    markup = build_inline_keyboard(buttons) if buttons else None
    sent = await target_message.answer(text, reply_markup=markup)
    if markup and keyboard_cleanup_service:
        await keyboard_cleanup_service.schedule_clear(sent.chat.id, sent.message_id)
    return sent


def _parse_teacher_date_input(text: str):
    """
    Parse date or date range for compare_teacher flow
    Returns (start_date, end_date, error_message)
    """
    text = text.strip()
    if not text:
        return None, None, "❌ Укажи дату в формате ДД.ММ.ГГГГ или диапазон ДД.ММ.ГГГГ-ДД.ММ.ГГГГ."
    
    date_pattern = r'(\d{1,2})\.(\d{1,2})\.(\d{4})'
    range_pattern = rf'^\s*{date_pattern}\s*-\s*{date_pattern}\s*$'
    single_pattern = rf'^\s*{date_pattern}\s*$'
    
    range_match = re.match(range_pattern, text)
    if range_match:
        day1, month1, year1, day2, month2, year2 = range_match.groups()
        try:
            start_date = datetime(int(year1), int(month1), int(day1))
            end_date = datetime(int(year2), int(month2), int(day2))
        except ValueError:
            return None, None, "❌ Некорректный диапазон дат."
        
        if end_date < start_date:
            return None, None, "❌ Начальная дата должна быть раньше конечной."
        
        if (end_date - start_date).days > MAX_COMPARE_TEACHER_PERIOD_DAYS - 1:
            return None, None, f"❌ Максимальный период — {MAX_COMPARE_TEACHER_PERIOD_DAYS} дней."
        
        return start_date, end_date, None
    
    single_match = re.match(single_pattern, text)
    if single_match:
        day, month, year = single_match.groups()
        try:
            date = datetime(int(year), int(month), int(day))
            return date, None, None
        except ValueError:
            return None, None, "❌ Некорректная дата."
    
    return None, None, "❌ Укажи дату в формате ДД.ММ.ГГГГ или диапазон ДД.ММ.ГГГГ-ДД.ММ.ГГГГ."


async def _transition_to_teacher_step(
    message_obj: Message,
    chat_id: int,
    user_id: int,
    group: str,
    keyboard_cleanup_service=None
):
    state_manager.update_state(chat_id, user_id, {
        'action': COMPARE_TEACHER_ACTION,
        'step': 'teacher',
        'group': group,
        'suggestions': []
    })
    
    text = (
        f"✅ Группа {group} сохранена.\n\n"
        "Теперь введи полное имя преподавателя (Фамилия Имя Отчество)."
    )
    await _send_compare_teacher_prompt(
        message_obj,
        text,
        _build_cancel_keyboard(),
        keyboard_cleanup_service
    )


async def _transition_to_date_step(
    message_obj: Message,
    chat_id: int,
    user_id: int,
    teacher_name: str,
    keyboard_cleanup_service=None
):
    state = state_manager.get_state(chat_id, user_id) or {}
    group = state.get('group')
    
    state_manager.update_state(chat_id, user_id, {
        'action': COMPARE_TEACHER_ACTION,
        'step': 'date',
        'group': group,
        'teacher': teacher_name,
        'suggestions': []
    })
    
    text = (
        f"✅ Преподаватель: {teacher_name}\n\n"
        "Укажи дату в формате ДД.ММ.ГГГГ или диапазон ДД.ММ.ГГГГ-ДД.ММ.ГГГГ "
        f"(до {MAX_COMPARE_TEACHER_PERIOD_DAYS} дней). Можно использовать кнопки ниже."
    )
    buttons = [
        [
            {"text": "Сегодня", "callback_data": "ct:date:today"},
            {"text": "Завтра", "callback_data": "ct:date:tomorrow"}
        ],
        *_build_cancel_keyboard()
    ]
    await _send_compare_teacher_prompt(
        message_obj,
        text,
        buttons,
        keyboard_cleanup_service
    )


async def _run_compare_teacher(
    message_obj: Message,
    session: AsyncSession,
    group: str,
    teacher_name: str,
    start_date: datetime,
    end_date: datetime | None,
    keyboard_cleanup_service=None,
    enable_teacher_schedule: bool = False
):
    if end_date:
        response, has_windows = await schedule_service.compare_group_with_teacher_period(
            session,
            group,
            teacher_name,
            start_date,
            end_date
        )
    else:
        response, has_windows = await schedule_service.compare_group_with_teacher(
            session,
            group,
            teacher_name,
            start_date,
            include_teacher_overview=False
        )
    
    show_schedule_button = enable_teacher_schedule and not has_windows
    markup = build_inline_keyboard(_build_compare_result_keyboard(show_schedule_button))
    sent = await message_obj.answer(response, reply_markup=markup)
    if keyboard_cleanup_service:
        await keyboard_cleanup_service.schedule_clear(sent.chat.id, sent.message_id)


async def _send_teacher_schedule_period(
    message_obj: Message,
    teacher_name: str,
    start_date: datetime,
    end_date: datetime
):
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    
    teacher_schedule = await schedule_service.fetch_schedule_by_teacher(teacher_name)
    if not teacher_schedule:
        await message_obj.answer(f"❌ Не удалось получить расписание преподавателя {teacher_name}")
        return
    
    if start_date == end_date:
        response = (
            f"📚 Расписание преподавателя {teacher_name}\n"
            f"Дата: {start_date.strftime('%d.%m.%Y')} ({schedule_service._get_weekday_name(start_date.weekday())})\n\n"
        )
    else:
        response = (
            f"📚 Расписание преподавателя {teacher_name}\n"
            f"Период: {start_date.strftime('%d.%m.%Y')} – {end_date.strftime('%d.%m.%Y')}\n\n"
        )
    
    schedule_type = '0'
    current_date = start_date
    
    while current_date <= end_date:
        lessons = schedule_service.get_schedule_for_date(teacher_schedule, current_date)
        response += f"📅 {current_date.strftime('%d.%m.%Y')} ({schedule_service._get_weekday_name(current_date.weekday())})\n"
        if not lessons:
            response += "  Занятий нет\n\n"
        else:
            for lesson in lessons:
                formatted = schedule_service.format_lesson(lesson, schedule_type=schedule_type)
                response += formatted + "\n"
            response += "\n"
        current_date += timedelta(days=1)
    
    await message_obj.answer(response.strip())


@router.message(Command("compare_teacher"))
async def cmd_compare_teacher(
    message: Message,
    session: AsyncSession,
    keyboard_cleanup_service=None
):
    """Команда /compare_teacher — сравнить группу с преподавателем"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    default_group = None
    if message.chat.type in ['group', 'supergroup']:
        chat = await ChatRepository.get_by_id(session, chat_id)
        if chat and chat.group:
            default_group = chat.group
    else:
        user = await UserRepository.get_by_id(session, user_id)
        if user and user.group:
            default_group = user.group
    
    state_manager.set_state(chat_id, user_id, {
        'action': COMPARE_TEACHER_ACTION,
        'step': 'group'
    })
    
    text = (
        "🤝 Сравнение расписания группы с преподавателем\n\n"
        "Укажи номер группы. Можно написать вручную или выбрать сохранённую кнопку ниже.\n"
        "После этого бот попросит ввести ФИО преподавателя и дату.\n\n"
        "Используй /cancel для отмены."
    )
    
    buttons = []
    if default_group:
        buttons.append([{
            "text": f"Использовать {default_group}",
            "callback_data": f"ct:group:{default_group}"
        }])
    buttons.extend(_build_cancel_keyboard())
    
    await _send_compare_teacher_prompt(
        message,
        text,
        buttons,
        keyboard_cleanup_service
    )


@router.message(_is_compare_teacher_flow)
async def process_compare_teacher_flow(
    message: Message,
    session: AsyncSession,
    keyboard_cleanup_service=None
):
    """Обработка шагов команды /compare_teacher"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    state = state_manager.get_state(chat_id, user_id)
    
    if not state or state.get('action') != COMPARE_TEACHER_ACTION:
        return
    
    step = state.get('step')
    
    if step == 'group':
        group = extract_group_from_text(message.text)
        if not group:
            await message.answer("❌ Укажи группу в формате 000-000.")
            return
        await _transition_to_teacher_step(
            message,
            chat_id,
            user_id,
            group,
            keyboard_cleanup_service
        )
        return
    
    if step == 'teacher':
        teacher_raw = _normalize_teacher_name(message.text)
        if len(teacher_raw) < 3:
            await message.answer("❌ Укажи полное имя преподавателя (Фамилия Имя Отчество).")
            return
        
        teachers_data = await schedule_service.fetch_teachers()
        if not teachers_data:
            await message.answer("❌ Не удалось получить список преподавателей. Попробуй позже.")
            return
        
        teacher_name = None
        teacher_lower = teacher_raw.lower()
        for teacher in teachers_data:
            name = teacher.get('name') or teacher.get('fullname')
            if name and name.lower() == teacher_lower:
                teacher_name = name
                break
        
        if teacher_name:
            await _transition_to_date_step(
                message,
                chat_id,
                user_id,
                teacher_name,
                keyboard_cleanup_service
            )
            return
        
        suggestions = [
            (teacher.get('name') or teacher.get('fullname'))
            for teacher in teachers_data
            if (teacher.get('name') or teacher.get('fullname', '')).lower().startswith(teacher_lower)
        ]
        suggestions = [s for s in suggestions if s][:3]
        
        state_manager.update_state(chat_id, user_id, {
            'suggestions': suggestions,
            'step': 'teacher',
            'group': state.get('group')
        })
        
        if suggestions:
            buttons = [
                [{
                    "text": suggestion,
                    "callback_data": f"ct:teacher_suggest:{idx}"
                }]
                for idx, suggestion in enumerate(suggestions)
            ]
            buttons.extend(_build_cancel_keyboard())
            await _send_compare_teacher_prompt(
                message,
                "❌ Не нашёл такого преподавателя. Может быть, имелся в виду один из вариантов?",
                buttons,
                keyboard_cleanup_service
            )
        else:
            await message.answer("❌ Не нашёл такого преподавателя. Попробуй снова указать ФИО полностью.")
        return
    
    if step == 'date':
        date_start, date_end, error = _parse_teacher_date_input(message.text)
        if error:
            await message.answer(error)
            return
        
        group = state.get('group')
        teacher_name = state.get('teacher')
        
        if not group or not teacher_name:
            state_manager.delete_state(chat_id, user_id)
            await message.answer("❌ Данные устарели. Запусти /compare_teacher заново.")
            return
        
        await _run_compare_teacher(
            message,
            session,
            group,
            teacher_name,
            date_start,
            date_end,
            keyboard_cleanup_service,
            enable_teacher_schedule=True
        )
        state_manager.update_state(chat_id, user_id, {
            'action': COMPARE_TEACHER_ACTION,
            'step': 'date',
            'group': group,
            'teacher': teacher_name,
            'suggestions': [],
            'period_start': date_start.isoformat(),
            'period_end': (date_end or date_start).isoformat()
        })


@router.callback_query(F.data.startswith("ct:group:"))
async def process_compare_teacher_group_callback(
    callback: CallbackQuery,
    keyboard_cleanup_service=None
):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    state = state_manager.get_state(chat_id, user_id)
    
    if not state or state.get('action') != COMPARE_TEACHER_ACTION:
        await callback.answer("⏱ Время ожидания истекло. Запусти /compare_teacher заново.")
        return
    
    group = callback.data.split(":", 2)[2]
    await _transition_to_teacher_step(
        callback.message,
        chat_id,
        user_id,
        group,
        keyboard_cleanup_service
    )
    with suppress(Exception):
        await callback.message.edit_reply_markup()
    await callback.answer(f"Группа {group} выбрана")


@router.callback_query(F.data.startswith("ct:teacher_suggest:"))
async def process_compare_teacher_suggestion_callback(
    callback: CallbackQuery,
    keyboard_cleanup_service=None
):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    state = state_manager.get_state(chat_id, user_id)
    
    if not state or state.get('action') != COMPARE_TEACHER_ACTION or state.get('step') != 'teacher':
        await callback.answer("⏱ Сессия истекла.")
        return
    
    suggestions = state.get('suggestions') or []
    try:
        idx = int(callback.data.split(":")[2])
    except (ValueError, IndexError):
        await callback.answer("❌ Некорректный выбор.")
        return
    
    if idx < 0 or idx >= len(suggestions):
        await callback.answer("❌ Этот вариант больше недоступен.")
        return
    
    teacher_name = suggestions[idx]
    await _transition_to_date_step(
        callback.message,
        chat_id,
        user_id,
        teacher_name,
        keyboard_cleanup_service
    )
    with suppress(Exception):
        await callback.message.edit_reply_markup()
    await callback.answer(f"Выбран преподаватель: {teacher_name}")


@router.callback_query(F.data.startswith("ct:date:"))
async def process_compare_teacher_date_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    keyboard_cleanup_service=None
):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    state = state_manager.get_state(chat_id, user_id)
    
    if not state or state.get('action') != COMPARE_TEACHER_ACTION or state.get('step') != 'date':
        await callback.answer("⏱ Сессия истекла.")
        return
    
    group = state.get('group')
    teacher_name = state.get('teacher')
    if not group or not teacher_name:
        state_manager.delete_state(chat_id, user_id)
        await callback.answer("❌ Данные устарели.")
        return
    
    token = callback.data.split(":", 2)[2]
    base_date = datetime.now()
    if token == "today":
        start_date = base_date
        end_date = None
        answer_text = "Сегодня"
    elif token == "tomorrow":
        start_date = base_date + timedelta(days=1)
        end_date = None
        answer_text = "Завтра"
    else:
        await callback.answer("❌ Неизвестный выбор.")
        return
    
    await _run_compare_teacher(
        callback.message,
        session,
        group,
        teacher_name,
        start_date,
        end_date,
        keyboard_cleanup_service,
        enable_teacher_schedule=True
    )
    state_manager.update_state(chat_id, user_id, {
        'action': COMPARE_TEACHER_ACTION,
        'step': 'date',
        'group': group,
        'teacher': teacher_name,
        'suggestions': [],
        'period_start': start_date.isoformat(),
        'period_end': (end_date or start_date).isoformat()
    })
    with suppress(Exception):
        await callback.message.edit_reply_markup()
    await callback.answer(f"Дата: {answer_text}")


@router.callback_query(F.data == CHANGE_DATE_CALLBACK)
async def process_compare_teacher_change_date_callback(
    callback: CallbackQuery,
    keyboard_cleanup_service=None
):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    state = state_manager.get_state(chat_id, user_id)
    
    if not state or state.get('action') != COMPARE_TEACHER_ACTION:
        await callback.answer("⏱ Сессия истекла.")
        return
    
    group = state.get('group')
    teacher_name = state.get('teacher')
    if not group or not teacher_name:
        state_manager.delete_state(chat_id, user_id)
        await callback.answer("❌ Данные устарели.")
        return
    
    await _transition_to_date_step(
        callback.message,
        chat_id,
        user_id,
        teacher_name,
        keyboard_cleanup_service
    )
    with suppress(Exception):
        await callback.message.edit_reply_markup()
    await callback.answer("Выбери новую дату")


@router.callback_query(F.data == SHOW_TEACHER_SCHEDULE_CALLBACK)
async def process_compare_teacher_schedule_callback(
    callback: CallbackQuery
):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    state = state_manager.get_state(chat_id, user_id)
    
    if not state or state.get('action') != COMPARE_TEACHER_ACTION:
        await callback.answer("⏱ Сессия истекла.")
        return
    
    teacher_name = state.get('teacher')
    start_iso = state.get('period_start')
    end_iso = state.get('period_end')
    
    if not (teacher_name and start_iso and end_iso):
        await callback.answer("❌ Сначала выполните сравнение за период.")
        return
    
    try:
        start_date = datetime.fromisoformat(start_iso)
        end_date = datetime.fromisoformat(end_iso)
    except ValueError:
        await callback.answer("❌ Данные периода повреждены.")
        return
    
    await _send_teacher_schedule_period(
        callback.message,
        teacher_name,
        start_date,
        end_date
    )
    await callback.answer("Показываю расписание")


@router.callback_query(F.data == "ct:cancel")
async def process_compare_teacher_cancel(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    state = state_manager.get_state(chat_id, user_id)
    
    if state and state.get('action') == COMPARE_TEACHER_ACTION:
        state_manager.delete_state(chat_id, user_id)
        await callback.message.answer("❌ Сравнение с преподавателем отменено.")
        with suppress(Exception):
            await callback.message.edit_reply_markup()
        await callback.answer("Отменено")
    else:
        await callback.answer()

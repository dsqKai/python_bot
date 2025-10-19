"""
Вспомогательные функции для создания клавиатур
"""
from typing import List, Optional
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def build_inline_keyboard(
    buttons: List[List[dict]],
) -> InlineKeyboardMarkup:
    """
    Создать inline клавиатуру из списка кнопок
    
    Args:
        buttons: Список строк кнопок, каждая строка - список dict с text и callback_data
        
    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()
    
    for row in buttons:
        row_buttons = []
        for btn in row:
            row_buttons.append(
                InlineKeyboardButton(
                    text=btn['text'],
                    callback_data=btn.get('callback_data'),
                    url=btn.get('url')
                )
            )
        builder.row(*row_buttons)
    
    return builder.as_markup()


def build_pagination_keyboard(
    current_page: int,
    total_pages: int,
    callback_prefix: str = "page"
) -> InlineKeyboardMarkup:
    """
    Создать клавиатуру с пагинацией
    
    Args:
        current_page: Текущая страница (0-indexed)
        total_pages: Всего страниц
        callback_prefix: Префикс для callback_data
        
    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()
    
    buttons = []
    
    # Кнопка "Назад"
    if current_page > 0:
        buttons.append(
            InlineKeyboardButton(
                text="⏮",
                callback_data=f"{callback_prefix}:{current_page - 1}"
            )
        )
    
    # Информация о странице
    buttons.append(
        InlineKeyboardButton(
            text=f"{current_page + 1}/{total_pages}",
            callback_data="noop"
        )
    )
    
    # Кнопка "Вперед"
    if current_page < total_pages - 1:
        buttons.append(
            InlineKeyboardButton(
                text="⏭",
                callback_data=f"{callback_prefix}:{current_page + 1}"
            )
        )
    
    builder.row(*buttons)
    return builder.as_markup()


def build_settings_keyboard(
    daily_notify_enabled: bool = True,
    notify_online: bool = True,
    notification_time: Optional[str] = None,
    subgroup: Optional[int] = None
) -> InlineKeyboardMarkup:
    """
    Создать клавиатуру настроек
    
    Args:
        daily_notify_enabled: Включены ли ежедневные уведомления
        notify_online: Включены ли уведомления об онлайн парах
        notification_time: Время уведомлений
        subgroup: Выбранная подгруппа
        
    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()
    
    # Ежедневные уведомления
    daily_status = "✅" if daily_notify_enabled else "❌"
    builder.row(
        InlineKeyboardButton(
            text=f"{daily_status} Ежедневные уведомления",
            callback_data="settings:toggle_daily"
        )
    )
    
    # Время уведомлений (если включены)
    if daily_notify_enabled:
        time_text = notification_time if notification_time else "Не установлено"
        builder.row(
            InlineKeyboardButton(
                text=f"⏰ Время: {time_text}",
                callback_data="settings:change_time"
            )
        )
    
    # Уведомления об онлайн парах
    online_status = "✅" if notify_online else "❌"
    builder.row(
        InlineKeyboardButton(
            text=f"{online_status} Онлайн-пары",
            callback_data="settings:toggle_online"
        )
    )
    
    # Подгруппа
    subgroup_text = str(subgroup) if subgroup else "Все"
    builder.row(
        InlineKeyboardButton(
            text=f"👥 Подгруппа: {subgroup_text}",
            callback_data="settings:change_subgroup"
        )
    )
    
    # Закрыть
    builder.row(
        InlineKeyboardButton(
            text="❌ Закрыть",
            callback_data="settings:close"
        )
    )
    
    return builder.as_markup()


def build_subgroup_keyboard() -> InlineKeyboardMarkup:
    """
    Создать клавиатуру выбора подгруппы
    
    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="1️⃣ Подгруппа 1", callback_data="subgroup:1"),
        InlineKeyboardButton(text="2️⃣ Подгруппа 2", callback_data="subgroup:2")
    )
    builder.row(
        InlineKeyboardButton(text="👥 Все", callback_data="subgroup:0")
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="subgroup:back")
    )
    
    return builder.as_markup()


def build_yes_no_keyboard(
    yes_callback: str = "yes",
    no_callback: str = "no"
) -> InlineKeyboardMarkup:
    """
    Создать клавиатуру Да/Нет
    
    Args:
        yes_callback: Callback для кнопки "Да"
        no_callback: Callback для кнопки "Нет"
        
    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="✅ Да", callback_data=yes_callback),
        InlineKeyboardButton(text="❌ Нет", callback_data=no_callback)
    )
    
    return builder.as_markup()


def build_skip_keyboard(callback: str = "skip") -> InlineKeyboardMarkup:
    """
    Создать клавиатуру с кнопкой "Пропустить"
    
    Args:
        callback: Callback для кнопки
        
    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="⏭ Пропустить", callback_data=callback)
    )
    
    return builder.as_markup()


def build_role_selection_keyboard() -> InlineKeyboardMarkup:
    """
    Создать клавиатуру выбора роли
    
    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="👨‍🎓 Студент", callback_data="role:student"),
        InlineKeyboardButton(text="👨‍🏫 Преподаватель", callback_data="role:teacher")
    )
    
    return builder.as_markup()

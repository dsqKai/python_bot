"""
Утилиты для работы с текстом
"""
import re
from typing import List
from datetime import datetime


def escape_markdown_v2(text: str) -> str:
    """
    Экранирование специальных символов для MarkdownV2
    
    Args:
        text: Исходный текст
        
    Returns:
        Экранированный текст
    """
    if not text:
        return ''
    
    special_chars = r'\_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{char}' if char in special_chars else char for char in text)


def escape_html(text: str) -> str:
    """
    Экранирование HTML
    
    Args:
        text: Исходный текст
        
    Returns:
        Экранированный текст
    """
    if not text:
        return ''
    
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&#39;'))


def split_text_into_chunks(text: str, chunk_size: int = 3000) -> List[str]:
    """
    Разбить текст на чанки по размеру
    
    Args:
        text: Исходный текст
        chunk_size: Максимальный размер чанка
        
    Returns:
        Список чанков
    """
    chunks = []
    start_index = 0
    
    while start_index < len(text):
        chunks.append(text[start_index:start_index + chunk_size])
        start_index += chunk_size
    
    return chunks


def split_text_preserving_lines(text: str, max_len: int = 3000) -> List[str]:
    """
    Разбить текст на страницы, сохраняя целостность строк
    
    Args:
        text: Исходный текст
        max_len: Максимальная длина страницы
        
    Returns:
        Список страниц
    """
    lines = text.split('\n')
    pages = []
    current_page = ''
    
    for line in lines:
        if len(current_page) + len(line) + 1 > max_len:
            if current_page:
                pages.append(current_page)
            
            # Если одна строка длиннее max_len
            if len(line) > max_len:
                for i in range(0, len(line), max_len):
                    pages.append(line[i:i + max_len])
                current_page = ''
            else:
                current_page = line
        else:
            current_page += ('\n' if current_page else '') + line
    
    if current_page:
        pages.append(current_page)
    
    return pages


def extract_group_from_text(text: str) -> str:
    """
    Извлечь номер группы из текста (формат: 000-000)
    
    Args:
        text: Исходный текст
        
    Returns:
        Номер группы или None
    """
    if not text:
        return None
    
    # Допускаем цифры, латинские и кириллические буквы (включая Ё/ё)
    pattern = r'\b[0-9A-Za-zА-Яа-яЁё]{3}-[0-9A-Za-zА-Яа-яЁё]{3,4}\b'
    match = re.search(pattern, text)
    
    return match.group(0) if match else None


def format_datetime(dt: datetime, fmt: str = "%d.%m.%Y %H:%M") -> str:
    """
    Форматировать дату и время
    
    Args:
        dt: Объект datetime
        fmt: Формат вывода
        
    Returns:
        Отформатированная строка
    """
    return dt.strftime(fmt)


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    Обрезать текст до указанной длины
    
    Args:
        text: Исходный текст
        max_length: Максимальная длина
        suffix: Суффикс для обрезанного текста
        
    Returns:
        Обрезанный текст
    """
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def clean_whitespace(text: str) -> str:
    """
    Очистить лишние пробелы и переносы строк
    
    Args:
        text: Исходный текст
        
    Returns:
        Очищенный текст
    """
    # Удаляем множественные пробелы
    text = re.sub(r' +', ' ', text)
    # Удаляем множественные переносы строк
    text = re.sub(r'\n\n+', '\n\n', text)
    # Удаляем пробелы в начале и конце строк
    text = '\n'.join(line.strip() for line in text.split('\n'))
    
    return text.strip()


def validate_time_format(time_str: str) -> bool:
    """
    Проверить формат времени (HH:MM)
    
    Args:
        time_str: Строка времени
        
    Returns:
        True если формат правильный
    """
    pattern = r'^([0-1][0-9]|2[0-3]):[0-5][0-9]$'
    return bool(re.match(pattern, time_str))


def validate_date_format(date_str: str) -> bool:
    """
    Проверить формат даты (DD.MM.YYYY)
    
    Args:
        date_str: Строка даты
        
    Returns:
        True если формат правильный
    """
    pattern = r'^(0[1-9]|[12][0-9]|3[01])\.(0[1-9]|1[0-2])\.\d{4}$'
    return bool(re.match(pattern, date_str))


def build_username_mention(username: str, user_id: int) -> str:
    """
    Создать упоминание пользователя
    
    Args:
        username: Username пользователя
        user_id: ID пользователя
        
    Returns:
        Строка упоминания
    """
    if username:
        return f"@{username}"
    return f"ID {user_id}"


def parse_command_args(text: str) -> List[str]:
    """
    Распарсить аргументы команды
    
    Args:
        text: Текст команды
        
    Returns:
        Список аргументов
    """
    # Удаляем команду (первое слово)
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return []
    
    # Разбиваем аргументы
    return parts[1].split()


def contains_any_keyword(text: str, keywords: List[str], case_sensitive: bool = False) -> bool:
    """
    Проверить наличие любого из ключевых слов в тексте
    
    Args:
        text: Исходный текст
        keywords: Список ключевых слов
        case_sensitive: Учитывать регистр
        
    Returns:
        True если найдено хотя бы одно слово
    """
    if not case_sensitive:
        text = text.lower()
        keywords = [k.lower() for k in keywords]
    
    return any(keyword in text for keyword in keywords)

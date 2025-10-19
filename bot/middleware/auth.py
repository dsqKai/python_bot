"""
Middleware для проверки прав доступа
"""
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings, AdminPermissions
from database.repository import AdminRepository


class AuthMiddleware(BaseMiddleware):
    """Middleware для проверки прав доступа"""
    
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        """Добавляем информацию о правах пользователя в data"""
        user_id = event.from_user.id
        session: AsyncSession = data.get('session')
        
        # Проверяем, является ли пользователь глобальным админом
        is_global_admin = user_id in settings.admin_ids_list
        data['is_global_admin'] = is_global_admin
        
        # Получаем права администратора из БД
        permissions = []
        if session and not is_global_admin:
            permissions = await AdminRepository.get_permissions(session, user_id)
        
        data['admin_permissions'] = permissions
        data['user_id'] = user_id
        
        # Продолжаем обработку
        return await handler(event, data)


async def is_group_admin(event: Message | CallbackQuery) -> bool:
    """
    Проверить, является ли пользователь администратором группы
    
    Args:
        event: Событие (Message или CallbackQuery)
        
    Returns:
        True если администратор
    """
    if isinstance(event, CallbackQuery):
        chat = event.message.chat
    else:
        chat = event.chat
    
    if chat.type not in ['group', 'supergroup']:
        return False
    
    try:
        member = await event.bot.get_chat_member(chat.id, event.from_user.id)
        return member.status in ['administrator', 'creator']
    except Exception:
        return False


async def check_permission(
    permission: str,
    data: Dict[str, Any],
    session: AsyncSession
) -> bool:
    """
    Проверить наличие права у пользователя
    
    Args:
        permission: Требуемое право
        data: Данные middleware
        session: Сессия БД
        
    Returns:
        True если есть право
    """
    # Глобальные админы имеют все права
    if data.get('is_global_admin'):
        return True
    
    # Проверяем права из БД
    user_id = data.get('user_id')
    if user_id and session:
        return await AdminRepository.has_permission(session, user_id, permission)
    
    return False

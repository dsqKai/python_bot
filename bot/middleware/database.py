"""
Middleware для работы с базой данных
"""
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Update

from database.session import db_session


class DatabaseMiddleware(BaseMiddleware):
    """Middleware для добавления сессии БД в контекст"""
    
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        """Создание сессии БД для каждого запроса"""
        async for session in db_session.get_session():
            data['session'] = session
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception as e:
                await session.rollback()
                raise

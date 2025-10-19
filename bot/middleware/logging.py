"""
Middleware для логирования
"""
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, Update
from loguru import logger


class LoggingMiddleware(BaseMiddleware):
    """Middleware для логирования событий"""
    
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        """Логирование события"""
        
        # Определяем тип события
        if event.message:
            msg = event.message
            user = msg.from_user
            chat = msg.chat
            
            logger.info(
                f"Message from {user.id} (@{user.username}) "
                f"in chat {chat.id} ({chat.type}): {msg.text[:50] if msg.text else '[media]'}"
            )
        
        elif event.callback_query:
            query = event.callback_query
            user = query.from_user
            
            logger.info(
                f"Callback from {user.id} (@{user.username}): {query.data}"
            )
        
        # Выполняем обработчик
        try:
            result = await handler(event, data)
            return result
        except Exception as e:
            logger.error(f"Error handling event: {e}", exc_info=True)
            raise

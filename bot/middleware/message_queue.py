"""
Middleware для передачи message_queue в обработчики
"""
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from typing import Callable, Dict, Any, Awaitable

from bot.utils.message_queue import MessageQueue


class MessageQueueMiddleware(BaseMiddleware):
    """Middleware для передачи message_queue в обработчики"""
    
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        # Получаем message_queue из контекста диспетчера
        message_queue: MessageQueue = data.get('message_queue')
        
        if message_queue:
            data['message_queue'] = message_queue
        
        return await handler(event, data)

"""
Middleware для передачи KeyboardCleanupService в обработчики
"""
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from typing import Callable, Dict, Any, Awaitable

from bot.services.keyboard_cleanup import KeyboardCleanupService


class KeyboardCleanupMiddleware(BaseMiddleware):
    """Инжектит KeyboardCleanupService в data для handlers"""

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        service: KeyboardCleanupService | None = data.get('keyboard_cleanup_service')
        if service:
            data['keyboard_cleanup_service'] = service
        return await handler(event, data)



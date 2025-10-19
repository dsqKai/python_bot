"""
Middleware для rate limiting и защиты от спама
"""
from typing import Callable, Dict, Any, Awaitable
from datetime import datetime, timedelta
from aiogram import BaseMiddleware
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings, Constants
from database.repository import BanRepository


class RateLimitMiddleware(BaseMiddleware):
    """Middleware для контроля частоты запросов"""
    
    def __init__(self):
        super().__init__()
        # Хранилище счетчиков запросов {user_id: [timestamp1, timestamp2, ...]}
        self.user_requests: Dict[int, list] = {}
    
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        """Проверка rate limit перед обработкой сообщения"""
        user_id = event.from_user.id
        session: AsyncSession = data.get('session')
        
        # Проверяем наличие активного бана
        if session:
            ban = await BanRepository.get_by_id(session, user_id)
            if ban and ban.ban_until > int(datetime.now().timestamp() * 1000):
                # Пользователь забанен
                ban_until_dt = datetime.fromtimestamp(ban.ban_until / 1000)
                await event.answer(
                    f"🚫 Поли заметил слишком много сообщений подряд... "
                    f"Ты временно заблокирован до {ban_until_dt.strftime('%d.%m.%Y %H:%M')}. "
                    f"Дай системе передохнуть!"
                )
                return  # Не обрабатываем сообщение
            elif ban:
                # Бан истек, удаляем
                await BanRepository.delete(session, user_id)
        
        # Очищаем старые запросы (старше окна rate limit)
        now = datetime.now()
        window_start = now - timedelta(seconds=settings.rate_limit_window_seconds)
        
        if user_id in self.user_requests:
            self.user_requests[user_id] = [
                ts for ts in self.user_requests[user_id]
                if ts > window_start
            ]
        else:
            self.user_requests[user_id] = []
        
        # Добавляем текущий запрос
        self.user_requests[user_id].append(now)
        
        # Проверяем лимит
        if len(self.user_requests[user_id]) > settings.rate_limit_messages:
            # Превышен лимит - баним пользователя
            if session:
                ban_until = int(
                    (now + timedelta(minutes=settings.ban_duration_minutes)).timestamp() * 1000
                )
                await BanRepository.create(session, user_id, ban_until)
                await session.commit()
            
            await event.answer(
                "🚫️ Поли заметил спам... Ты временно заблокирован. Попробуй чуть позже!"
            )
            return
        
        # Продолжаем обработку
        return await handler(event, data)

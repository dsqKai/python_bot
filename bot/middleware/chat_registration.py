"""
Middleware для автоматической регистрации чатов
"""
from typing import Callable, Dict, Any, Awaitable
from datetime import datetime
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from database.repository import ChatRepository, UserRepository
from loguru import logger
from bot.services.business_metrics import business_metrics_service


class ChatRegistrationMiddleware(BaseMiddleware):
    """Middleware для автоматической регистрации чатов и пользователей"""
    
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        """Автоматически регистрируем чаты и пользователей при первом сообщении"""
        
        # Обрабатываем только сообщения
        if not isinstance(event, Message):
            return await handler(event, data)
        
        session: AsyncSession = data.get('session')
        if not session:
            return await handler(event, data)
        
        user_id = event.from_user.id
        chat_id = event.chat.id
        
        try:
            # Для групповых чатов - регистрируем чат
            if event.chat.type in ['group', 'supergroup']:
                chat = await ChatRepository.get_by_id(session, chat_id)
                if not chat:
                    # Создаем чат без группы (группу установит администратор)
                    thread_id = getattr(event, 'message_thread_id', None)
                    await ChatRepository.create(
                        session, 
                        chat_id, 
                        group="",  # Пустая группа, будет установлена через /add
                        thread_id=thread_id
                    )
                    await session.commit()
                    logger.info(f"Auto-registered chat {chat_id}")
            
            # Для личных чатов - регистрируем пользователя
            elif event.chat.type == 'private':
                user = await UserRepository.get_by_id(session, user_id)
                if not user:
                    # Создаем пользователя без группы
                    await UserRepository.create(
                        session,
                        user_id=user_id,
                        group="",  # Пустая группа, будет установлена через /add
                        username=event.from_user.username,
                        last_activity=datetime.now()
                    )
                    await session.commit()
                    logger.info(f"Auto-registered user {user_id}")
                    
                    # Отслеживаем нового пользователя в бизнес-метриках
                    business_metrics_service.track_new_user()
                else:
                    # Обновляем время последней активности
                    await UserRepository.update(
                        session,
                        user_id,
                        last_activity=datetime.now()
                    )
                    await session.commit()
        
        except Exception as e:
            logger.error(f"Error in ChatRegistrationMiddleware: {e}")
            # Не прерываем обработку сообщения из-за ошибки регистрации
        
        # Продолжаем обработку
        return await handler(event, data)

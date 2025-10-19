"""
Сервис для очистки inline-клавиатур (reply_markup) по TTL
"""
import asyncio
from typing import Optional

from aiogram import Bot
from loguru import logger

from bot.utils.message_queue import MessageQueue, MessagePriority


class KeyboardCleanupService:
    """Планирует удаление inline-клавиатуры у сообщений через заданный TTL"""

    def __init__(
        self,
        bot: Bot,
        message_queue: MessageQueue,
        default_ttl_seconds: int = 3600
    ):
        self.bot = bot
        self.message_queue = message_queue
        self.default_ttl_seconds = max(0, int(default_ttl_seconds))

    async def schedule_clear(
        self,
        chat_id: int,
        message_id: int,
        ttl_seconds: Optional[int] = None
    ):
        """
        Запланировать очистку reply_markup у сообщения.

        Args:
            chat_id: ID чата
            message_id: ID сообщения
            ttl_seconds: через сколько секунд очистить (если None — берется дефолт)
        """
        delay = self.default_ttl_seconds if ttl_seconds is None else max(0, int(ttl_seconds))
        if delay == 0:
            # Мгновенная очистка
            await self._clear_keyboard(chat_id, message_id)
            return

        asyncio.create_task(self._delayed_clear(delay, chat_id, message_id))

    async def _delayed_clear(self, delay: int, chat_id: int, message_id: int):
        try:
            await asyncio.sleep(delay)
            await self._clear_keyboard(chat_id, message_id)
        except asyncio.CancelledError:
            # Задача отменена — ничего не делаем
            pass
        except Exception as e:
            logger.debug(f"KeyboardCleanupService delayed clear error: {e}")

    async def _clear_keyboard(self, chat_id: int, message_id: int):
        """Очистить клавиатуру, игнорируя ошибки (сообщение могло быть удалено/изменено)."""
        try:
            await self.message_queue.enqueue(
                self.bot.edit_message_reply_markup,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=None,
                priority=MessagePriority.LOW
            )
        except Exception as e:
            # Ошибки тут не критичны
            logger.debug(f"KeyboardCleanupService clear failed for {chat_id}:{message_id} — {e}")



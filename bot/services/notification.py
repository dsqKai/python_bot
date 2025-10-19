"""
Сервис уведомлений
"""
import asyncio
from datetime import datetime, timedelta
from typing import List
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from database.repository import UserRepository, ChatRepository
from bot.services.schedule import schedule_service
from bot.utils.message_queue import MessageQueue, MessagePriority


class NotificationService:
    """Сервис для отправки уведомлений"""
    
    def __init__(self, bot: Bot, message_queue: MessageQueue):
        self.bot = bot
        self.message_queue = message_queue
        self.schedule_service = schedule_service
        self.scheduler = AsyncIOScheduler()
    
    def start(self):
        """Запустить планировщик уведомлений"""
        # Ежедневные уведомления - каждую минуту проверяем
        self.scheduler.add_job(
            self.send_daily_notifications,
            CronTrigger(minute='*'),
            id='daily_notifications'
        )
        
        # Очистка кеша и alerted_lessons - каждый день в 00:01
        self.scheduler.add_job(
            self.cleanup_daily,
            CronTrigger(hour=0, minute=1),
            id='cleanup_daily'
        )
        
        # Удаление старых blocked_users - каждый день в 03:00
        self.scheduler.add_job(
            self.cleanup_blocked_users,
            CronTrigger(hour=3, minute=0),
            id='cleanup_blocked'
        )
        
        self.scheduler.start()
        logger.info("Notification scheduler started")
    
    def stop(self):
        """Остановить планировщик"""
        self.scheduler.shutdown()
        logger.info("Notification scheduler stopped")
    
    async def send_daily_notifications(self):
        """Отправить ежедневные уведомления"""
        from database.session import db_session
        
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        
        async for session in db_session.get_session():
            try:
                # Получаем пользователей с уведомлениями на это время
                users = await UserRepository.get_all_with_notifications(
                    session, 
                    current_time
                )
                
                for user in users:
                    await self._send_daily_schedule(session, user.userid, user.group)
                
                # Получаем чаты с уведомлениями
                chats = await ChatRepository.get_all_with_notifications(
                    session,
                    current_time
                )
                
                for chat in chats:
                    await self._send_daily_schedule(session, chat.chatid, chat.group)
                
                await session.commit()
                
            except Exception as e:
                logger.error(f"Error in send_daily_notifications: {e}")
                await session.rollback()
    
    async def _send_daily_schedule(
        self,
        session: AsyncSession,
        chat_id: int,
        group: str
    ):
        """
        Отправить расписание на день
        
        Args:
            session: Сессия БД
            chat_id: ID чата
            group: Номер группы
        """
        try:
            today = datetime.now()
            response = await self.schedule_service.get_day_response(
                session,
                group,
                today
            )
            
            # Добавляем в очередь с обычным приоритетом
            await self.message_queue.enqueue(
                self.bot.send_message,
                chat_id,
                response,
                priority=MessagePriority.NORMAL
            )
            
        except Exception as e:
            logger.error(f"Error sending daily schedule to {chat_id}: {e}")
    
    async def schedule_online_lesson_notification(
        self,
        session: AsyncSession,
        chat_id: int,
        group: str,
        lesson_time: str,
        lesson_info: str
    ):
        """
        Запланировать уведомление об онлайн-паре за 5 минут
        
        Args:
            session: Сессия БД
            chat_id: ID чата
            group: Номер группы
            lesson_time: Время начала пары (HH:MM)
            lesson_info: Информация о паре
        """
        try:
            # Парсим время
            hour, minute = map(int, lesson_time.split(':'))
            lesson_datetime = datetime.now().replace(
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0
            )
            
            # Время уведомления - за 5 минут
            notification_time = lesson_datetime - timedelta(minutes=5)
            
            # Если время еще не прошло
            if notification_time > datetime.now():
                delay = (notification_time - datetime.now()).total_seconds()
                
                # Планируем асинхронно
                asyncio.create_task(
                    self._send_delayed_notification(
                        delay,
                        chat_id,
                        f"🔔 Напоминание!\n\n{lesson_info}\n\n⏰ Начало через 5 минут!"
                    )
                )
        except Exception as e:
            logger.error(f"Error scheduling online lesson notification: {e}")
    
    async def _send_delayed_notification(
        self,
        delay: float,
        chat_id: int,
        text: str
    ):
        """
        Отправить уведомление с задержкой
        
        Args:
            delay: Задержка в секундах
            chat_id: ID чата
            text: Текст сообщения
        """
        await asyncio.sleep(delay)
        
        await self.message_queue.enqueue(
            self.bot.send_message,
            chat_id,
            text,
            priority=MessagePriority.HIGH
        )
    
    async def cleanup_daily(self):
        """Ежедневная очистка"""
        from database.session import db_session
        from database.models import AlertedLesson
        from sqlalchemy import delete
        
        logger.info("Running daily cleanup...")
        
        async for session in db_session.get_session():
            try:
                # Очищаем таблицу alerted_lessons
                await session.execute(delete(AlertedLesson))
                await session.commit()
                
                # Очищаем кэш расписания
                self.schedule_service.cache.clear()
                
                logger.info("Daily cleanup completed")
                
            except Exception as e:
                logger.error(f"Error in daily cleanup: {e}")
                await session.rollback()
    
    async def cleanup_blocked_users(self):
        """Очистка старых заблокированных пользователей"""
        from database.session import db_session
        from database.models import BlockedUser
        from sqlalchemy import delete
        
        logger.info("Cleaning up old blocked users...")
        
        async for session in db_session.get_session():
            try:
                # Удаляем пользователей, заблокировавших бота более 7 дней назад
                cutoff_date = datetime.now() - timedelta(days=7)
                
                await session.execute(
                    delete(BlockedUser).where(BlockedUser.blocked_at < cutoff_date)
                )
                await session.commit()
                
                logger.info("Blocked users cleanup completed")
                
            except Exception as e:
                logger.error(f"Error cleaning blocked users: {e}")
                await session.rollback()

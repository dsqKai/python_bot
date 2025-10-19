"""
Сервис для сбора бизнес-метрик
"""
import asyncio
from datetime import datetime, timedelta
from typing import Set, Dict
from collections import defaultdict
from loguru import logger
from prometheus_client import Gauge, Counter, Histogram

from database.session import db_session
from database.models import User, Chat, FeedbackMessage, BlockedUser
from sqlalchemy import select, func, and_, or_


# ===== БИЗНЕС-МЕТРИКИ =====

# Активные пользователи
dau_gauge = Gauge('bot_daily_active_users', 'Daily Active Users (last 24h)')
wau_gauge = Gauge('bot_weekly_active_users', 'Weekly Active Users (last 7 days)')
mau_gauge = Gauge('bot_monthly_active_users', 'Monthly Active Users (last 30 days)')

# Новые пользователи
new_users_today = Gauge('bot_new_users_today', 'New users registered today')
new_users_total = Counter('bot_new_users_total', 'Total new users registered')

# Engagement метрики
user_sessions = Counter(
    'bot_user_sessions_total',
    'Total user sessions',
    ['chat_type']
)

messages_per_user = Histogram(
    'bot_messages_per_user',
    'Distribution of messages per user',
    buckets=[1, 5, 10, 20, 50, 100, 200, 500]
)

commands_per_user = Histogram(
    'bot_commands_per_user',
    'Distribution of commands per user',
    buckets=[1, 3, 5, 10, 20, 50, 100]
)

# Функциональные метрики
feature_usage = Counter(
    'bot_feature_usage_total',
    'Feature usage counter',
    ['feature']
)

notification_subscribers = Gauge(
    'bot_notification_subscribers',
    'Users with notifications enabled',
    ['type']
)

# Retention метрики
returning_users_daily = Gauge('bot_returning_users_daily', 'Users who returned within 24h')
returning_users_weekly = Gauge('bot_returning_users_weekly', 'Users who returned within 7 days')

# Churn метрики
blocked_bot_users = Gauge('bot_blocked_users_total', 'Users who blocked the bot')
inactive_users_7d = Gauge('bot_inactive_users_7d', 'Users inactive for 7+ days')
inactive_users_30d = Gauge('bot_inactive_users_30d', 'Users inactive for 30+ days')

# Группы и чаты
total_private_chats = Gauge('bot_total_private_chats', 'Total private chats')
total_group_chats = Gauge('bot_total_group_chats', 'Total group chats')
groups_by_type = Gauge('bot_groups_by_type', 'Groups by study group', ['group_name'])

# Feedback метрики
feedback_messages_total = Counter('bot_feedback_messages_total', 'Total feedback messages received')
feedback_daily = Gauge('bot_feedback_daily', 'Feedback messages in last 24h')

# Конверсия
tutorial_completion_rate = Gauge('bot_tutorial_completion_rate', 'Tutorial completion rate (%)')
group_selection_rate = Gauge('bot_group_selection_rate', 'Users who selected a group (%)')

# Peak hours
active_users_by_hour = Gauge('bot_active_users_by_hour', 'Active users by hour', ['hour'])


class BusinessMetricsService:
    """Сервис для вычисления и обновления бизнес-метрик"""
    
    def __init__(self):
        self.active_users_24h: Set[int] = set()
        self.active_users_7d: Set[int] = set()
        self.active_users_30d: Set[int] = set()
        
        # Счетчики для текущей сессии
        self.user_message_counts: Dict[int, int] = defaultdict(int)
        self.user_command_counts: Dict[int, int] = defaultdict(int)
        self.last_user_activity: Dict[int, datetime] = {}
        
        # Для отслеживания активности по часам
        self.users_by_hour: Dict[int, Set[int]] = defaultdict(set)
        
        self.running = False
        self.update_task = None
    
    def track_user_activity(self, user_id: int, is_command: bool = False, chat_type: str = 'private'):
        """Отслеживание активности пользователя"""
        now = datetime.now()
        
        # Добавляем в активные
        self.active_users_24h.add(user_id)
        self.active_users_7d.add(user_id)
        self.active_users_30d.add(user_id)
        
        # Обновляем время последней активности
        self.last_user_activity[user_id] = now
        
        # Счетчики сообщений/команд
        self.user_message_counts[user_id] += 1
        if is_command:
            self.user_command_counts[user_id] += 1
        
        # Активность по часам
        hour = now.hour
        self.users_by_hour[hour].add(user_id)
        
        # Сессии
        user_sessions.labels(chat_type=chat_type).inc()
    
    def track_feature_usage(self, feature_name: str):
        """Отслеживание использования функций"""
        feature_usage.labels(feature=feature_name).inc()
    
    def track_new_user(self):
        """Отслеживание нового пользователя"""
        new_users_total.inc()
    
    def track_feedback(self):
        """Отслеживание обратной связи"""
        feedback_messages_total.inc()
    
    async def update_db_metrics(self):
        """Обновление метрик из базы данных"""
        try:
            async for session in db_session.get_session():
                # === Общие метрики ===
                
                # Всего пользователей
                total_users = await session.scalar(select(func.count(User.userid)))
                total_private_chats.set(total_users or 0)
                
                # Всего групповых чатов
                total_chats = await session.scalar(select(func.count(Chat.chatid)))
                total_group_chats.set(total_chats or 0)
                
                # === Конверсия ===
                
                # Tutorial completion rate
                if total_users and total_users > 0:
                    completed_tutorial = await session.scalar(
                        select(func.count(User.userid)).where(User.tutorial_completed == True)
                    )
                    tutorial_completion_rate.set(
                        (completed_tutorial / total_users * 100) if completed_tutorial else 0
                    )
                    
                    # Group selection rate
                    selected_group = await session.scalar(
                        select(func.count(User.userid)).where(User.group != "")
                    )
                    group_selection_rate.set(
                        (selected_group / total_users * 100) if selected_group else 0
                    )
                
                # === Подписчики уведомлений ===
                
                daily_notify_users = await session.scalar(
                    select(func.count(User.userid)).where(User.daily_notify_enabled == True)
                )
                notification_subscribers.labels(type='daily').set(daily_notify_users or 0)
                
                online_notify_users = await session.scalar(
                    select(func.count(User.userid)).where(User.notify_online == True)
                )
                notification_subscribers.labels(type='online').set(online_notify_users or 0)
                
                # === Новые пользователи сегодня ===
                
                today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                new_today = await session.scalar(
                    select(func.count(User.userid)).where(User.created_at >= today_start)
                )
                new_users_today.set(new_today or 0)
                
                # === Churn метрики ===
                
                # Заблокировавшие бота
                blocked_count = await session.scalar(select(func.count(BlockedUser.userid)))
                blocked_bot_users.set(blocked_count or 0)
                
                # Неактивные пользователи (используем last_activity если доступно)
                now = datetime.now()
                week_ago = now - timedelta(days=7)
                month_ago = now - timedelta(days=30)
                
                # Неактивны 7+ дней (по last_activity или created_at если last_activity пустое)
                inactive_7d_count = await session.scalar(
                    select(func.count(User.userid)).where(
                        or_(
                            and_(User.last_activity.is_not(None), User.last_activity < week_ago),
                            and_(User.last_activity.is_(None), User.created_at < week_ago)
                        )
                    )
                )
                inactive_users_7d.set(inactive_7d_count or 0)
                
                # Неактивны 30+ дней
                inactive_30d_count = await session.scalar(
                    select(func.count(User.userid)).where(
                        or_(
                            and_(User.last_activity.is_not(None), User.last_activity < month_ago),
                            and_(User.last_activity.is_(None), User.created_at < month_ago)
                        )
                    )
                )
                inactive_users_30d.set(inactive_30d_count or 0)
                
                # === Retention метрики (улучшенные с last_activity) ===
                
                # Пользователи, которые были активны вчера и вернулись сегодня
                yesterday_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
                yesterday_end = now.replace(hour=0, minute=0, second=0, microsecond=0)
                today_start = yesterday_end
                
                # Это требует более сложного запроса с подзапросами
                # Упрощенная версия: пользователи активные за последние 24 часа
                day_ago = now - timedelta(days=1)
                returning_daily_count = await session.scalar(
                    select(func.count(User.userid)).where(
                        and_(
                            User.last_activity.is_not(None),
                            User.last_activity >= day_ago
                        )
                    )
                )
                returning_users_daily.set(returning_daily_count or 0)
                
                # Пользователи активные за последние 7 дней
                returning_weekly_count = await session.scalar(
                    select(func.count(User.userid)).where(
                        and_(
                            User.last_activity.is_not(None),
                            User.last_activity >= week_ago
                        )
                    )
                )
                returning_users_weekly.set(returning_weekly_count or 0)
                
                # === Feedback метрики ===
                
                # Feedback за последние 24 часа
                day_ago = datetime.now() - timedelta(days=1)
                feedback_count = await session.scalar(
                    select(func.count(FeedbackMessage.id)).where(
                        FeedbackMessage.timestamp >= day_ago
                    )
                )
                feedback_daily.set(feedback_count or 0)
                
                # === Группы по типам ===
                
                # Топ групп по количеству пользователей
                result = await session.execute(
                    select(User.group, func.count(User.userid))
                    .where(User.group != "")
                    .group_by(User.group)
                    .order_by(func.count(User.userid).desc())
                    .limit(20)  # Топ 20 групп
                )
                
                for group_name, count in result.fetchall():
                    if group_name:
                        groups_by_type.labels(group_name=group_name).set(count)
                
        except Exception as e:
            logger.error(f"Error updating DB metrics: {e}", exc_info=True)
    
    async def update_runtime_metrics(self):
        """Обновление метрик времени выполнения"""
        try:
            # DAU/WAU/MAU
            dau_gauge.set(len(self.active_users_24h))
            wau_gauge.set(len(self.active_users_7d))
            mau_gauge.set(len(self.active_users_30d))
            
            # Messages per user (обновляем гистограмму)
            for user_id, count in self.user_message_counts.items():
                messages_per_user.observe(count)
            
            # Commands per user
            for user_id, count in self.user_command_counts.items():
                commands_per_user.observe(count)
            
            # Active users by hour
            for hour, users in self.users_by_hour.items():
                active_users_by_hour.labels(hour=str(hour).zfill(2)).set(len(users))
            
            # Returning users обновляются из БД в update_db_metrics()
            # используя поле last_activity
            
        except Exception as e:
            logger.error(f"Error updating runtime metrics: {e}", exc_info=True)
    
    async def cleanup_old_data(self):
        """Очистка старых данных для экономии памяти"""
        try:
            now = datetime.now()
            
            # Очищаем активных пользователей по периодам
            # (в реальности нужно проверять реальное время активности)
            # Это упрощенная версия - данные сбрасываются при рестарте
            
            # Очищаем счетчики сообщений раз в сутки
            if now.hour == 0 and now.minute < 10:
                self.user_message_counts.clear()
                self.user_command_counts.clear()
                self.users_by_hour.clear()
                logger.info("Business metrics daily cleanup completed")
            
        except Exception as e:
            logger.error(f"Error cleaning up metrics data: {e}", exc_info=True)
    
    async def update_loop(self):
        """Главный цикл обновления метрик"""
        logger.info("Business metrics service started")
        
        while self.running:
            try:
                # Обновляем метрики из БД (раз в 5 минут)
                await self.update_db_metrics()
                
                # Обновляем runtime метрики (каждую минуту)
                await self.update_runtime_metrics()
                
                # Очистка старых данных
                await self.cleanup_old_data()
                
                # Спим 1 минуту
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in business metrics update loop: {e}", exc_info=True)
                await asyncio.sleep(60)
        
        logger.info("Business metrics service stopped")
    
    def start(self):
        """Запуск сервиса"""
        if not self.running:
            self.running = True
            self.update_task = asyncio.create_task(self.update_loop())
            logger.info("Business metrics service starting...")
    
    async def stop(self):
        """Остановка сервиса"""
        if self.running:
            self.running = False
            if self.update_task:
                self.update_task.cancel()
                try:
                    await self.update_task
                except asyncio.CancelledError:
                    pass
            logger.info("Business metrics service stopped")


# Глобальный экземпляр сервиса
business_metrics_service = BusinessMetricsService()


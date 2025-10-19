"""
Middleware для сбора метрик Prometheus
"""
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Update, Message, CallbackQuery
from prometheus_client import Counter, Histogram, Gauge
import time

from bot.services.business_metrics import business_metrics_service

# Определяем метрики

# Счетчик обработанных сообщений
messages_total = Counter(
    'bot_messages_total',
    'Total number of messages processed',
    ['type', 'chat_type', 'status']
)

# Счетчик команд
commands_total = Counter(
    'bot_commands_total',
    'Total number of commands executed',
    ['command', 'status']
)

# Счетчик callback запросов
callbacks_total = Counter(
    'bot_callbacks_total',
    'Total number of callback queries',
    ['callback_data', 'status']
)

# Гистограмма времени обработки
request_duration_seconds = Histogram(
    'bot_request_duration_seconds',
    'Time spent processing requests',
    ['type']
)

# Счетчик ошибок
errors_total = Counter(
    'bot_errors_total',
    'Total number of errors',
    ['type', 'handler']
)

# Активные пользователи (гаuge для текущего значения)
active_users = Gauge(
    'bot_active_users',
    'Number of active users'
)

# Счетчик уникальных пользователей за сессию
unique_users = Gauge(
    'bot_unique_users_total',
    'Total number of unique users'
)

# Используем set для отслеживания уникальных пользователей
_unique_user_ids = set()


class MetricsMiddleware(BaseMiddleware):
    """Middleware для сбора метрик"""
    
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        """Сбор метрик для события"""
        
        start_time = time.time()
        event_type = None
        status = 'success'
        
        try:
            # Определяем тип события и собираем метрики
            if event.message:
                event_type = 'message'
                msg: Message = event.message
                user_id = msg.from_user.id if msg.from_user else None
                chat_type = msg.chat.type
                
                # Отслеживаем уникальных пользователей
                if user_id:
                    if user_id not in _unique_user_ids:
                        _unique_user_ids.add(user_id)
                        unique_users.set(len(_unique_user_ids))
                
                # Увеличиваем счетчик сообщений
                messages_total.labels(
                    type='text' if msg.text else 'media',
                    chat_type=chat_type,
                    status='received'
                ).inc()
                
                # Если это команда - отслеживаем отдельно
                if msg.text and msg.text.startswith('/'):
                    command = msg.text.split()[0].split('@')[0]
                    commands_total.labels(
                        command=command,
                        status='received'
                    ).inc()
                    
                    # Бизнес-метрики: отслеживаем активность пользователя
                    business_metrics_service.track_user_activity(
                        user_id=user_id,
                        is_command=True,
                        chat_type=chat_type
                    )
                    
                    # Отслеживаем использование конкретных функций
                    feature_map = {
                        '/start': 'onboarding',
                        '/help': 'help',
                        '/settings': 'settings',
                        '/feedback': 'feedback',
                        '/schedule': 'schedule_view',
                        '/tomorrow': 'schedule_view',
                        '/week': 'schedule_view',
                        '/notify': 'notifications',
                    }
                    if command in feature_map:
                        business_metrics_service.track_feature_usage(feature_map[command])
                else:
                    # Обычное сообщение (не команда)
                    business_metrics_service.track_user_activity(
                        user_id=user_id,
                        is_command=False,
                        chat_type=chat_type
                    )
            
            elif event.callback_query:
                event_type = 'callback'
                query: CallbackQuery = event.callback_query
                user_id = query.from_user.id if query.from_user else None
                
                # Отслеживаем уникальных пользователей
                if user_id:
                    if user_id not in _unique_user_ids:
                        _unique_user_ids.add(user_id)
                        unique_users.set(len(_unique_user_ids))
                
                # Увеличиваем счетчик callback'ов
                callback_data = query.data[:50] if query.data else 'unknown'  # Ограничиваем длину
                callbacks_total.labels(
                    callback_data=callback_data,
                    status='received'
                ).inc()
                
                # Бизнес-метрики: отслеживаем активность
                from_chat = query.message.chat if query.message else None
                chat_type = from_chat.type if from_chat else 'unknown'
                business_metrics_service.track_user_activity(
                    user_id=user_id,
                    is_command=False,
                    chat_type=chat_type
                )
                
                # Отслеживаем использование функций через callback
                if callback_data.startswith('settings_'):
                    business_metrics_service.track_feature_usage('settings')
                elif callback_data.startswith('feedback_'):
                    business_metrics_service.track_feature_usage('feedback')
                elif callback_data.startswith('schedule_'):
                    business_metrics_service.track_feature_usage('schedule_view')
            
            # Выполняем обработчик
            result = await handler(event, data)
            
            # Успешная обработка
            if event_type == 'message' and event.message:
                messages_total.labels(
                    type='text' if event.message.text else 'media',
                    chat_type=event.message.chat.type,
                    status='processed'
                ).inc()
                
                if event.message.text and event.message.text.startswith('/'):
                    command = event.message.text.split()[0].split('@')[0]
                    commands_total.labels(
                        command=command,
                        status='success'
                    ).inc()
            
            elif event_type == 'callback' and event.callback_query:
                callback_data = event.callback_query.data[:50] if event.callback_query.data else 'unknown'
                callbacks_total.labels(
                    callback_data=callback_data,
                    status='processed'
                ).inc()
            
            return result
            
        except Exception as e:
            status = 'error'
            
            # Увеличиваем счетчик ошибок
            error_type = type(e).__name__
            handler_name = handler.__name__ if hasattr(handler, '__name__') else 'unknown'
            
            errors_total.labels(
                type=error_type,
                handler=handler_name
            ).inc()
            
            # Отмечаем неудачную обработку команды
            if event_type == 'message' and event.message:
                if event.message.text and event.message.text.startswith('/'):
                    command = event.message.text.split()[0].split('@')[0]
                    commands_total.labels(
                        command=command,
                        status='error'
                    ).inc()
            
            raise
            
        finally:
            # Записываем время обработки
            if event_type:
                duration = time.time() - start_time
                request_duration_seconds.labels(type=event_type).observe(duration)


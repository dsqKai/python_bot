"""
Главный файл приложения
Запуск: python main.py
"""
import asyncio
import sys
from loguru import logger

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import settings
from database.session import db_session
from database.models import Base

# Middleware
from bot.middleware.database import DatabaseMiddleware
from bot.middleware.logging import LoggingMiddleware
from bot.middleware.rate_limit import RateLimitMiddleware
from bot.middleware.auth import AuthMiddleware
from bot.middleware.chat_registration import ChatRegistrationMiddleware
from bot.middleware.message_queue import MessageQueueMiddleware
from bot.middleware.keyboard_cleanup import KeyboardCleanupMiddleware
from bot.middleware.metrics import MetricsMiddleware

# Handlers
from bot.handlers import commands, settings as settings_handlers, feedback, admin

# Services
from bot.utils.message_queue import MessageQueue
from bot.services.notification import NotificationService
from bot.services.keyboard_cleanup import KeyboardCleanupService
from bot.services.metrics_server import MetricsServer
from bot.services.business_metrics import business_metrics_service


# Настройка логирования
logger.remove()

# Логи в stdout (для консоли) - красивый формат
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO"
)

# Логи в файл в JSON формате (для Loki)
logger.add(
    "logs/bot.log",
    rotation="10 MB",
    retention="7 days",
    level="DEBUG",
    serialize=True  # JSON формат для парсинга в Loki
)


async def init_database():
    """Инициализация базы данных"""
    logger.info("Initializing database...")
    
    # Здесь можно добавить автоматическое создание таблиц (для разработки)
    # В продакшене лучше использовать Alembic миграции
    # from sqlalchemy import create_engine
    # engine = create_engine(settings.database_url_sync)
    # Base.metadata.create_all(engine)
    
    logger.info("Database initialized")


async def on_startup(dp: Dispatcher):
    """Действия при запуске бота"""
    logger.info("Starting bot...")
    
    # Получаем бота из контекста диспетчера
    bot = dp['bot']
    
    # Инициализируем базу данных
    await init_database()
    
    # Запускаем HTTP сервер для метрик
    logger.info("Starting metrics server...")
    metrics_server: MetricsServer = dp['metrics_server']
    await metrics_server.start()
    logger.info("Metrics server start completed")
    
    # Запускаем очередь сообщений
    message_queue: MessageQueue = dp['message_queue']
    await message_queue.start()
    
    # Запускаем сервис уведомлений
    notification_service: NotificationService = dp['notification_service']
    notification_service.start()
    
    # Запускаем сервис бизнес-метрик
    business_metrics_service.start()
    
    # Запускаем cleanup task для state manager
    from bot.services.state_manager import state_manager
    await state_manager.start_cleanup_task()
    
    logger.info("Bot started successfully!")
    
    # Отправляем уведомление админам
    for admin_id in settings.admin_ids_list:
        try:
            await bot.send_message(admin_id, "🤖 Бот запущен!")
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")


async def on_shutdown(dp: Dispatcher):
    """Действия при остановке бота"""
    logger.info("Shutting down bot...")
    
    # Останавливаем сервис уведомлений
    notification_service: NotificationService = dp['notification_service']
    notification_service.stop()
    
    # Останавливаем сервис бизнес-метрик
    await business_metrics_service.stop()
    
    # Останавливаем очередь сообщений
    message_queue: MessageQueue = dp['message_queue']
    await message_queue.stop()
    
    # Останавливаем HTTP сервер метрик
    metrics_server: MetricsServer = dp['metrics_server']
    await metrics_server.stop()
    
    # Закрываем соединение с БД
    await db_session.close()
    
    logger.info("Bot stopped")


async def main():
    """Главная функция"""
    # Создаем бота
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML
        )
    )
    
    # Создаем диспетчер
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Создаем очередь сообщений
    message_queue = MessageQueue(
        rate_limit=settings.message_queue_rate_limit,
        max_workers=settings.message_queue_max_workers
    )
    
    # Создаем сервис уведомлений
    notification_service = NotificationService(bot, message_queue)
    # Сервис очистки клавиатур
    keyboard_cleanup_service = KeyboardCleanupService(
        bot,
        message_queue,
        default_ttl_seconds=settings.inline_keyboard_ttl_seconds
    )
    
    # Создаем HTTP сервер для метрик
    metrics_server = MetricsServer(host='0.0.0.0', port=8000)
    
    # Сохраняем в контексте диспетчера
    dp['bot'] = bot
    dp['message_queue'] = message_queue
    dp['notification_service'] = notification_service
    dp['metrics_server'] = metrics_server
    dp['keyboard_cleanup_service'] = keyboard_cleanup_service
    
    # Регистрируем middleware (порядок важен!)
    dp.update.middleware(MetricsMiddleware())  # Метрики - первым для точного измерения
    dp.update.middleware(LoggingMiddleware())
    dp.update.middleware(DatabaseMiddleware())
    dp.message.middleware(ChatRegistrationMiddleware())
    dp.message.middleware(RateLimitMiddleware())
    dp.message.middleware(AuthMiddleware())
    dp.message.middleware(MessageQueueMiddleware())
    dp.message.middleware(KeyboardCleanupMiddleware())
    dp.callback_query.middleware(AuthMiddleware())
    dp.callback_query.middleware(MessageQueueMiddleware())
    dp.callback_query.middleware(KeyboardCleanupMiddleware())
    
    # Регистрируем роутеры
    dp.include_router(commands.router)
    dp.include_router(settings_handlers.router)
    dp.include_router(feedback.router)
    dp.include_router(admin.router)
    
    # Регистрируем startup/shutdown
    async def startup_wrapper():
        await on_startup(dp)
    
    async def shutdown_wrapper():
        await on_shutdown(dp)
    
    dp.startup.register(startup_wrapper)
    dp.shutdown.register(shutdown_wrapper)
    
    # Запускаем polling
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types()
        )
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}", exc_info=True)

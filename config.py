"""
Конфигурация приложения
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    """Настройки приложения из переменных окружения"""
    
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False
    )
    
    # Telegram Bot
    bot_token: str
    
    # Database
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: str
    db_name: str = "schedulebot"
    
    # Admin
    admin_user_ids: str = ""
    
    # API (optional)
    api_username: str = ""
    api_password: str = ""
    
    # Rate Limiting
    rate_limit_messages: int = 20
    rate_limit_window_seconds: int = 60
    ban_duration_minutes: int = 5
    
    # Broadcast
    broadcast_batch_size: int = 20
    broadcast_interval_seconds: int = 1
    
    # Message Queue
    message_queue_max_workers: int = 5
    message_queue_rate_limit: int = 30
    # Inline keyboard
    inline_keyboard_ttl_seconds: int = 3600
    
    @property
    def database_url(self) -> str:
        """Формирует URL для подключения к PostgreSQL"""
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )
    
    @property
    def database_url_sync(self) -> str:
        """Синхронный URL для Alembic"""
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )
    
    @property
    def admin_ids_list(self) -> List[int]:
        """Список ID администраторов"""
        if not self.admin_user_ids:
            return []
        return [int(x.strip()) for x in self.admin_user_ids.split(",") if x.strip()]


# Глобальный объект настроек
settings = Settings()


# Константы
class Constants:
    """Константы приложения"""
    
    # Time windows
    RATE_LIMIT_WINDOW_MS = 60000  # 1 минута
    NOTIFICATION_COOLDOWN_MS = 60000  # 1 минута
    DEFAULT_BAN_DURATION_MIN = 60  # 60 минут
    
    # Timeouts
    COMPARE_GROUPS_TIMEOUT = 60000
    FEEDBACK_TIMEOUT = 60000
    
    # Cache TTL
    SEMESTER_CACHE_TTL_DAYS = 14
    GLOBAL_GROUPS_TTL_DAYS = 7
    GLOBAL_GROUPS_PRUNE_DAYS = 180
    
    # Retry settings
    RETRY_COUNT = 3
    RETRY_DELAY_MS = 5000
    
    # Schedule times (по типам расписания)
    SCHEDULE_TIMES = {
        '0': {
            1: '09:00-10:30',
            2: '10:40-12:10',
            3: '12:20-13:50',
            4: '14:30-16:00',
            5: '16:10-17:40',
            6: '17:50-19:20',
            7: '19:30-21:00',
        },
        '1': {
            1: '09:00-10:30',
            2: '10:40-12:10',
            3: '12:20-13:50',
            4: '14:30-16:00',
            5: '16:10-17:40',
            6: '18:20-19:40',
            7: '19:50-21:10',
        },
        '2': {
            1: '09:00-10:30',
            2: '10:40-12:10',
            3: '12:20-13:50',
            4: '14:30-16:00',
            5: '16:10-17:40',
            6: '18:30-20:00',
            7: '20:10-21:40',
        },
    }


# Права администраторов
class AdminPermissions:
    """Типы прав администраторов"""
    BAN_USER = 'ban_user'
    UNBAN_USER = 'unban_user'
    LIST_BANS = 'list_bans'
    ADD_HOLIDAYS = 'add_holidays'
    LIST_HOLIDAYS = 'list_holidays'
    BROADCAST = 'broadcast'
    FEEDBACK_READ = 'feedback_read'
    FEEDBACK_REPLY = 'feedback_reply'
    LIST_BLOCKED = 'list_blocked'
    STAT_COMMAND = 'stat_command'

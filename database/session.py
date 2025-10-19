"""
Управление сессиями базы данных
"""
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker
)
from sqlalchemy.pool import NullPool

from config import settings


class DatabaseSession:
    """Менеджер сессий базы данных"""
    
    def __init__(self):
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            echo=False,
            poolclass=NullPool,  # Для асинхронной работы
            pool_pre_ping=True,
        )
        
        self.async_session_maker = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Получить сессию базы данных"""
        async with self.async_session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
    
    async def close(self):
        """Закрыть соединение с базой данных"""
        await self.engine.dispose()


# Глобальный объект для работы с БД
db_session = DatabaseSession()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency для получения сессии БД"""
    async for session in db_session.get_session():
        yield session

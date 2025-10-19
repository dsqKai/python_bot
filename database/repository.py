"""
Репозитории для работы с базой данных
"""
from typing import Optional, List
from datetime import datetime
from sqlalchemy import select, delete, update, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    User, Chat, BlockedUser, Holiday, SemesterBoundary,
    PersonalizedName, GlobalGroup, Ban, Pattern, AlertedLesson,
    AdminUser, AdminPermission, FeedbackMessage
)


class UserRepository:
    """Репозиторий для работы с пользователями"""
    
    @staticmethod
    async def get_by_id(session: AsyncSession, user_id: int) -> Optional[User]:
        """Получить пользователя по ID"""
        result = await session.execute(
            select(User).where(User.userid == user_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def create(session: AsyncSession, user_id: int, **kwargs) -> User:
        """Создать пользователя"""
        user = User(userid=user_id, **kwargs)
        session.add(user)
        await session.flush()
        return user
    
    @staticmethod
    async def update(session: AsyncSession, user_id: int, **kwargs) -> Optional[User]:
        """Обновить пользователя"""
        await session.execute(
            update(User).where(User.userid == user_id).values(**kwargs)
        )
        return await UserRepository.get_by_id(session, user_id)
    
    @staticmethod
    async def delete(session: AsyncSession, user_id: int):
        """Удалить пользователя"""
        await session.execute(delete(User).where(User.userid == user_id))
    
    @staticmethod
    async def get_all_with_notifications(session: AsyncSession, notification_time: str) -> List[User]:
        """Получить всех пользователей с уведомлениями на определенное время"""
        result = await session.execute(
            select(User).where(
                and_(
                    User.daily_notify_enabled == True,
                    User.notification_time == notification_time,
                    User.group != ""
                )
            )
        )
        return list(result.scalars().all())


class ChatRepository:
    """Репозиторий для работы с чатами"""
    
    @staticmethod
    async def get_by_id(session: AsyncSession, chat_id: int) -> Optional[Chat]:
        """Получить чат по ID"""
        result = await session.execute(
            select(Chat).where(Chat.chatid == chat_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def create(session: AsyncSession, chat_id: int, group: str, **kwargs) -> Chat:
        """Создать чат"""
        chat = Chat(chatid=chat_id, group=group, **kwargs)
        session.add(chat)
        await session.flush()
        return chat
    
    @staticmethod
    async def update(session: AsyncSession, chat_id: int, **kwargs):
        """Обновить чат"""
        await session.execute(
            update(Chat).where(Chat.chatid == chat_id).values(**kwargs)
        )
    
    @staticmethod
    async def delete(session: AsyncSession, chat_id: int):
        """Удалить чат"""
        await session.execute(delete(Chat).where(Chat.chatid == chat_id))
    
    @staticmethod
    async def get_all_with_notifications(session: AsyncSession, notification_time: str) -> List[Chat]:
        """Получить все чаты с уведомлениями на определенное время"""
        result = await session.execute(
            select(Chat).where(
                and_(
                    Chat.daily_notify_enabled == True,
                    Chat.notification_time == notification_time
                )
            )
        )
        return list(result.scalars().all())


class BanRepository:
    """Репозиторий для работы с банами"""
    
    @staticmethod
    async def get_by_id(session: AsyncSession, user_id: int) -> Optional[Ban]:
        """Получить бан по ID пользователя"""
        result = await session.execute(
            select(Ban).where(Ban.userid == user_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def create(session: AsyncSession, user_id: int, ban_until: int) -> Ban:
        """Создать бан"""
        ban = Ban(userid=user_id, ban_until=ban_until)
        session.add(ban)
        await session.flush()
        return ban
    
    @staticmethod
    async def delete(session: AsyncSession, user_id: int):
        """Удалить бан"""
        await session.execute(delete(Ban).where(Ban.userid == user_id))
    
    @staticmethod
    async def get_all_active(session: AsyncSession, current_timestamp: int) -> List[Ban]:
        """Получить все активные баны"""
        result = await session.execute(
            select(Ban).where(Ban.ban_until > current_timestamp)
        )
        return list(result.scalars().all())


class PatternRepository:
    """Репозиторий для работы с паттернами"""
    
    @staticmethod
    async def get_all(session: AsyncSession) -> List[Pattern]:
        """Получить все паттерны"""
        result = await session.execute(select(Pattern))
        return list(result.scalars().all())
    
    @staticmethod
    async def create(session: AsyncSession, pattern: str, response: str) -> Pattern:
        """Создать паттерн"""
        pat = Pattern(pattern=pattern, response=response)
        session.add(pat)
        await session.flush()
        return pat
    
    @staticmethod
    async def delete_by_pattern(session: AsyncSession, pattern: str):
        """Удалить паттерн"""
        await session.execute(delete(Pattern).where(Pattern.pattern == pattern))


class FeedbackRepository:
    """Репозиторий для работы с обратной связью"""
    
    @staticmethod
    async def create(
        session: AsyncSession,
        user_id: int,
        user_message_id: Optional[int] = None,
        media_ids: Optional[str] = None,
        text: Optional[str] = None
    ) -> FeedbackMessage:
        """Создать фидбек"""
        feedback = FeedbackMessage(
            user_id=user_id,
            user_message_id=user_message_id,
            media_ids=media_ids,
            text=text
        )
        session.add(feedback)
        await session.flush()
        return feedback
    
    @staticmethod
    async def get_by_id(session: AsyncSession, feedback_id: int) -> Optional[FeedbackMessage]:
        """Получить фидбек по ID"""
        result = await session.execute(
            select(FeedbackMessage).where(FeedbackMessage.id == feedback_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_all(session: AsyncSession) -> List[FeedbackMessage]:
        """Получить все фидбеки"""
        result = await session.execute(
            select(FeedbackMessage).order_by(FeedbackMessage.id.asc())
        )
        return list(result.scalars().all())
    
    @staticmethod
    async def delete(session: AsyncSession, feedback_id: int):
        """Удалить фидбек"""
        await session.execute(delete(FeedbackMessage).where(FeedbackMessage.id == feedback_id))


class GlobalGroupRepository:
    """Репозиторий для работы со списком групп"""
    
    @staticmethod
    async def get_all(session: AsyncSession) -> List[GlobalGroup]:
        """Получить все группы"""
        result = await session.execute(select(GlobalGroup))
        return list(result.scalars().all())
    
    @staticmethod
    async def get_by_name(session: AsyncSession, group_name: str) -> Optional[GlobalGroup]:
        """Получить группу по имени"""
        result = await session.execute(
            select(GlobalGroup).where(GlobalGroup.group_name == group_name)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def upsert(session: AsyncSession, group_name: str, updated_at: datetime):
        """Создать или обновить группу"""
        # Для PostgreSQL можно использовать ON CONFLICT
        from sqlalchemy.dialects.postgresql import insert
        
        stmt = insert(GlobalGroup).values(
            group_name=group_name,
            updated_at=updated_at
        ).on_conflict_do_update(
            index_elements=['group_name'],
            set_={'updated_at': updated_at}
        )
        await session.execute(stmt)


class AdminRepository:
    """Репозиторий для работы с администраторами"""
    
    @staticmethod
    async def get_permissions(session: AsyncSession, user_id: int) -> List[str]:
        """Получить права администратора"""
        result = await session.execute(
            select(AdminPermission.command).where(AdminPermission.userid == user_id)
        )
        return [row[0] for row in result.all()]
    
    @staticmethod
    async def has_permission(session: AsyncSession, user_id: int, permission: str) -> bool:
        """Проверить наличие права"""
        result = await session.execute(
            select(AdminPermission).where(
                and_(
                    AdminPermission.userid == user_id,
                    AdminPermission.command == permission
                )
            )
        )
        return result.scalar_one_or_none() is not None

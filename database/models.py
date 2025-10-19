"""
SQLAlchemy модели для PostgreSQL
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    BigInteger, String, Integer, Boolean, DateTime, Text, 
    ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Базовый класс для всех моделей"""
    pass


class User(Base):
    """Модель пользователя"""
    __tablename__ = "users"
    
    userid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    group: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    role: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    daily_notify_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notification_time: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    notify_online: Mapped[bool] = mapped_column(Boolean, default=True)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tutorial_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    subgroup: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="1 или 2 — выбранная подгруппа")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_activity: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, comment="Время последней активности пользователя")
    
    def __repr__(self) -> str:
        return f"User(userid={self.userid}, group={self.group})"


class Chat(Base):
    """Модель группового чата"""
    __tablename__ = "chats"
    
    chatid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    thread_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    group: Mapped[str] = mapped_column(String(50), nullable=False)
    daily_notify_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notification_time: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    notify_online: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    def __repr__(self) -> str:
        return f"Chat(chatid={self.chatid}, group={self.group})"


class BlockedUser(Base):
    """Модель заблокированного пользователя (заблокировал бота)"""
    __tablename__ = "blocked_users"
    
    userid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    blocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    
    __table_args__ = (
        Index('idx_blocked_at', 'blocked_at'),
    )


class Holiday(Base):
    """Модель праздников и каникул"""
    __tablename__ = "holidays"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group: Mapped[str] = mapped_column(String(50), nullable=False)
    start_date: Mapped[str] = mapped_column(String(20), nullable=False)
    end_date: Mapped[str] = mapped_column(String(20), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)


class SemesterBoundary(Base):
    """Модель границ семестра"""
    __tablename__ = "semester_boundaries"
    
    group: Mapped[str] = mapped_column(String(50), primary_key=True)
    first_date: Mapped[str] = mapped_column(String(20), nullable=False)
    last_date: Mapped[str] = mapped_column(String(20), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PersonalizedName(Base):
    """Модель персонализированных имен"""
    __tablename__ = "personalized_names"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)


class GlobalGroup(Base):
    """Модель списка групп"""
    __tablename__ = "global_groups"
    
    group_name: Mapped[str] = mapped_column(String(50), primary_key=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Ban(Base):
    """Модель временного бана за спам"""
    __tablename__ = "bans"
    
    userid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ban_until: Mapped[int] = mapped_column(BigInteger, nullable=False)  # Unix timestamp


class Pattern(Base):
    """Модель кастомных паттернов ответов"""
    __tablename__ = "patterns"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)


class AlertedLesson(Base):
    """Модель уведомленных уроков (для предотвращения дублей)"""
    __tablename__ = "alerted_lessons"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chatid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    date: Mapped[str] = mapped_column(String(20), nullable=False)
    start_time: Mapped[str] = mapped_column(String(20), nullable=False)
    sbj: Mapped[str] = mapped_column(Text, nullable=False)


class AdminUser(Base):
    """Модель администратора"""
    __tablename__ = "admin_users"
    
    userid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    # Связь с правами
    permissions: Mapped[list["AdminPermission"]] = relationship(
        "AdminPermission", 
        back_populates="admin",
        cascade="all, delete-orphan"
    )


class AdminPermission(Base):
    """Модель прав администратора"""
    __tablename__ = "admin_permissions"
    
    userid: Mapped[int] = mapped_column(
        BigInteger, 
        ForeignKey("admin_users.userid", ondelete="CASCADE"),
        primary_key=True
    )
    command: Mapped[str] = mapped_column(String(50), primary_key=True)
    
    # Связь с администратором
    admin: Mapped["AdminUser"] = relationship("AdminUser", back_populates="permissions")
    
    __table_args__ = (
        UniqueConstraint('userid', 'command', name='uq_userid_command'),
    )


class FeedbackMessage(Base):
    """Модель сообщения обратной связи"""
    __tablename__ = "feedback_messages"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    media_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

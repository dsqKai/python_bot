"""
Сервис для работы с обратной связью
"""
import json
from typing import Optional, List
from aiogram import Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from database.repository import FeedbackRepository, UserRepository
from bot.utils import build_pagination_keyboard, escape_html
from bot.services.business_metrics import business_metrics_service


class FeedbackService:
    """Сервис для обработки обратной связи"""
    
    def __init__(self, bot: Bot):
        self.bot = bot
        self.feedback_pagination_data = {}  # {message_id: {data}}
    
    async def create_feedback(
        self,
        session: AsyncSession,
        message: Message
    ) -> int:
        """
        Создать запись обратной связи
        
        Args:
            session: Сессия БД
            message: Сообщение от пользователя
            
        Returns:
            ID созданной записи
        """
        user_id = message.from_user.id
        user_message_id = message.message_id
        text = message.text or message.caption
        
        # Собираем информацию о медиа
        media_ids = {}
        if message.photo:
            media_ids['photo'] = message.photo[-1].file_id
        elif message.video:
            media_ids['video'] = message.video.file_id
        elif message.document:
            media_ids['document'] = message.document.file_id
        elif message.audio:
            media_ids['audio'] = message.audio.file_id
        elif message.voice:
            media_ids['voice'] = message.voice.file_id
        elif message.video_note:
            media_ids['video_note'] = message.video_note.file_id
        
        media_json = json.dumps(media_ids) if media_ids else None
        
        # Создаем запись
        feedback = await FeedbackRepository.create(
            session,
            user_id=user_id,
            user_message_id=user_message_id,
            media_ids=media_json,
            text=text
        )
        
        await session.commit()
        
        # Отслеживаем в бизнес-метриках
        business_metrics_service.track_feedback()
        
        return feedback.id
    
    async def get_feedbacks_list(
        self,
        session: AsyncSession,
        page: int = 0,
        page_size: int = 10
    ) -> tuple[List, int]:
        """
        Получить список фидбеков с пагинацией
        
        Args:
            session: Сессия БД
            page: Номер страницы
            page_size: Размер страницы
            
        Returns:
            (список фидбеков, общее количество)
        """
        all_feedbacks = await FeedbackRepository.get_all(session)
        total = len(all_feedbacks)
        
        start_idx = page * page_size
        end_idx = start_idx + page_size
        
        return all_feedbacks[start_idx:end_idx], total
    
    def build_feedbacks_keyboard(
        self,
        feedbacks: List,
        current_page: int,
        total_pages: int
    ) -> InlineKeyboardMarkup:
        """
        Создать клавиатуру для списка фидбеков
        
        Args:
            feedbacks: Список фидбеков на текущей странице
            current_page: Текущая страница
            total_pages: Всего страниц
            
        Returns:
            InlineKeyboardMarkup
        """
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        
        builder = InlineKeyboardBuilder()
        
        # Кнопки для каждого фидбека
        for fb in feedbacks:
            builder.row(
                InlineKeyboardButton(
                    text=f"#{fb.id}",
                    callback_data=f"ask_view_{fb.id}"
                )
            )
        
        # Навигация
        nav_buttons = []
        if current_page > 0:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="⏮",
                    callback_data=f"fb_pg:{current_page - 1}"
                )
            )
        if current_page < total_pages - 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="⏭",
                    callback_data=f"fb_pg:{current_page + 1}"
                )
            )
        
        if nav_buttons:
            builder.row(*nav_buttons)
        
        return builder.as_markup()
    
    async def send_feedback_to_admins(
        self,
        session: AsyncSession,
        feedback_id: int,
        admin_chat_id: int
    ) -> Optional[int]:
        """
        Отправить фидбек администратору
        
        Args:
            session: Сессия БД
            feedback_id: ID фидбека
            admin_chat_id: ID чата администратора
            
        Returns:
            ID отправленного сообщения или None
        """
        feedback = await FeedbackRepository.get_by_id(session, feedback_id)
        if not feedback:
            return None
        
        # Получаем информацию о пользователе
        user = await UserRepository.get_by_id(session, feedback.user_id)
        username = f"@{user.username}" if user and user.username else f"ID {feedback.user_id}"
        
        # Формируем текст
        text = (
            f"🧾 Фидбек №{feedback.id}\n"
            f"👤 От пользователя: {username}\n"
            f"🕒 Время: {feedback.timestamp.strftime('%Y-%m-%d %H:%M')}\n\n"
            f"{feedback.text or '(пусто)'}"
        )
        
        # Клавиатура с кнопкой "Ответить"
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text="Ответить",
                callback_data=f"ask_reply_{feedback.id}"
            )
        )
        keyboard = builder.as_markup()
        
        try:
            # Если есть медиа - отправляем с медиа
            if feedback.media_ids:
                media = json.loads(feedback.media_ids)
                
                if 'photo' in media:
                    msg = await self.bot.send_photo(
                        admin_chat_id,
                        photo=media['photo'],
                        caption=escape_html(text),
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
                elif 'video' in media:
                    msg = await self.bot.send_video(
                        admin_chat_id,
                        video=media['video'],
                        caption=escape_html(text),
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
                elif 'document' in media:
                    msg = await self.bot.send_document(
                        admin_chat_id,
                        document=media['document'],
                        caption=escape_html(text),
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
                else:
                    # Остальные типы медиа или текст
                    msg = await self.bot.send_message(
                        admin_chat_id,
                        text=escape_html(text),
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
            else:
                # Только текст
                msg = await self.bot.send_message(
                    admin_chat_id,
                    text=escape_html(text),
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            
            return msg.message_id
            
        except Exception as e:
            logger.error(f"Error sending feedback to admin: {e}")
            return None
    
    async def send_reply_to_user(
        self,
        session: AsyncSession,
        feedback_id: int,
        reply_message: Message,
        admin_username: Optional[str] = None
    ) -> bool:
        """
        Отправить ответ на фидбек пользователю
        
        Args:
            session: Сессия БД
            feedback_id: ID фидбека
            reply_message: Сообщение-ответ от админа
            admin_username: Username администратора
            
        Returns:
            True если успешно отправлено
        """
        feedback = await FeedbackRepository.get_by_id(session, feedback_id)
        if not feedback:
            return False
        
        user_id = feedback.user_id
        admin_tag = f"@{admin_username}" if admin_username else f"ID {reply_message.from_user.id}"
        
        # Формируем текст ответа
        text = reply_message.text or reply_message.caption or ""
        caption_text = f"Ответ на твой фидбек #{feedback_id} от {admin_tag}:\n\n{text}"
        
        try:
            # Пытаемся отправить с reply
            reply_to = feedback.user_message_id
            
            if reply_message.photo:
                await self.bot.send_photo(
                    user_id,
                    photo=reply_message.photo[-1].file_id,
                    caption=caption_text,
                    reply_to_message_id=reply_to
                )
            elif reply_message.video:
                await self.bot.send_video(
                    user_id,
                    video=reply_message.video.file_id,
                    caption=caption_text,
                    reply_to_message_id=reply_to
                )
            elif reply_message.document:
                await self.bot.send_document(
                    user_id,
                    document=reply_message.document.file_id,
                    caption=caption_text,
                    reply_to_message_id=reply_to
                )
            elif reply_message.text:
                await self.bot.send_message(
                    user_id,
                    text=caption_text,
                    reply_to_message_id=reply_to
                )
            else:
                await self.bot.send_message(
                    user_id,
                    text=caption_text
                )
            
            # Удаляем фидбек из БД
            await FeedbackRepository.delete(session, feedback_id)
            await session.commit()
            
            return True
            
        except Exception as e:
            # Если не получилось с reply - пробуем без него
            logger.warning(f"Failed to send reply with reply_to: {e}")
            
            try:
                if reply_message.photo:
                    await self.bot.send_photo(
                        user_id,
                        photo=reply_message.photo[-1].file_id,
                        caption=caption_text
                    )
                elif reply_message.text:
                    await self.bot.send_message(user_id, text=caption_text)
                
                await FeedbackRepository.delete(session, feedback_id)
                await session.commit()
                return True
                
            except Exception as e2:
                logger.error(f"Failed to send reply completely: {e2}")
                # Всё равно удаляем фидбек
                await FeedbackRepository.delete(session, feedback_id)
                await session.commit()
                return False

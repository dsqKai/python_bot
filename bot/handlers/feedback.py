"""
Хэндлеры для обратной связи
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.feedback import FeedbackService
from bot.services.state_manager import state_manager
from bot.middleware.auth import check_permission
from config import AdminPermissions
from bot.utils import StateFilter


router = Router()


@router.message(Command("feedback"))
async def cmd_feedback(message: Message):
    """Команда /feedback - отправить отзыв"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if message.chat.type != 'private':
        await message.answer(
            "📩 Эта команда работает только в личном чате со мной"
        )
        return
    
    # Устанавливаем состояние
    state_manager.set_state(chat_id, user_id, {
        'action': 'awaiting_feedback'
    })
    
    await message.answer(
        "💬 Отправь свой отзыв, предложение или сообщение об ошибке.\n"
        "Можешь прикрепить фото, видео или документ."
    )


@router.message(Command("asks"))
async def cmd_asks(
    message: Message,
    session: AsyncSession,
    is_global_admin: bool,
    admin_permissions: list
):
    """Команда /asks - просмотр фидбеков (только для админов)"""
    # Проверяем права
    if not is_global_admin:
        has_permission = await check_permission(
            AdminPermissions.FEEDBACK_READ,
            {'is_global_admin': is_global_admin, 'user_id': message.from_user.id},
            session
        )
        if not has_permission:
            await message.answer(
                "🛡️ Эта команда доступна только администраторам"
            )
            return
    
    # Получаем список фидбеков
    feedback_service = FeedbackService(message.bot)
    feedbacks, total = await feedback_service.get_feedbacks_list(session, page=0)
    
    if not feedbacks:
        await message.answer("Нет непрочитанных фидбеков.")
        return
    
    # Формируем сообщение
    total_pages = (total + 9) // 10
    keyboard = feedback_service.build_feedbacks_keyboard(feedbacks, 0, total_pages)
    
    text = f"Непрочитанные фидбеки: {total}\nСтраница 1 из {total_pages}"
    
    sent_msg = await message.answer(text, reply_markup=keyboard)
    
    # Сохраняем данные пагинации
    feedback_service.feedback_pagination_data[sent_msg.message_id] = {
        'feedbacks': feedbacks,
        'current_page': 0,
        'page_size': 10,
        'total_pages': total_pages,
        'user_id': message.from_user.id,
        'chat_id': message.chat.id
    }


@router.callback_query(F.data.startswith("fb_pg:"))
async def process_feedback_pagination(
    callback: CallbackQuery,
    session: AsyncSession
):
    """Обработка пагинации фидбеков"""
    feedback_service = FeedbackService(callback.bot)
    
    message_id = callback.message.message_id
    pag_data = feedback_service.feedback_pagination_data.get(message_id)
    
    if not pag_data:
        await callback.answer("Время кнопок истекло.")
        return
    
    if callback.from_user.id != pag_data['user_id']:
        await callback.answer("Эти кнопки доступны только инициатору.")
        return
    
    new_page = int(callback.data.split(":")[1])
    
    # Получаем новые данные
    feedbacks, total = await feedback_service.get_feedbacks_list(
        session,
        page=new_page
    )
    
    total_pages = (total + 9) // 10
    keyboard = feedback_service.build_feedbacks_keyboard(feedbacks, new_page, total_pages)
    
    text = f"Непрочитанные фидбеки: {total}\nСтраница {new_page + 1} из {total_pages}"
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()
    except Exception:
        await callback.answer("Ошибка при обновлении")


@router.callback_query(F.data.startswith("ask_view_"))
async def process_ask_view(
    callback: CallbackQuery,
    session: AsyncSession
):
    """Просмотр фидбека"""
    feedback_id = int(callback.data.split("_")[2])
    
    feedback_service = FeedbackService(callback.bot)
    msg_id = await feedback_service.send_feedback_to_admins(
        session,
        feedback_id,
        callback.message.chat.id
    )
    
    if msg_id:
        await callback.answer("Фидбек отображен")
    else:
        await callback.answer("Фидбек не найден")


@router.callback_query(F.data.startswith("ask_reply_"))
async def process_ask_reply(
    callback: CallbackQuery,
    session: AsyncSession
):
    """Начать ответ на фидбек"""
    feedback_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    
    # Удаляем клавиатуру
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    
    # Устанавливаем состояние
    state_manager.set_state(chat_id, user_id, {
        'action': 'replying_feedback',
        'feedback_id': feedback_id
    })
    
    await callback.answer()
    await callback.bot.send_message(
        chat_id,
        "Отправь ответ (текст, фото, документ и т.п.) в этот чат."
    )


@router.message(StateFilter(['awaiting_feedback', 'replying_feedback']))
async def process_message(message: Message, session: AsyncSession):
    """Обработка сообщений в состоянии ожидания фидбека"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    state = state_manager.get_state(chat_id, user_id)
    if not state:
        return
    
    action = state.get('action')
    
    # Обработка создания фидбека
    if action == 'awaiting_feedback':
        feedback_service = FeedbackService(message.bot)
        feedback_id = await feedback_service.create_feedback(session, message)
        
        state_manager.delete_state(chat_id, user_id)
        
        await message.answer(
            f"✅ Спасибо за обратную связь! Твой фидбек #{feedback_id} принят.\n"
            f"Администратор ответит в ближайшее время."
        )
    
    # Обработка ответа на фидбек
    elif action == 'replying_feedback':
        feedback_id = state.get('feedback_id')
        
        feedback_service = FeedbackService(message.bot)
        success = await feedback_service.send_reply_to_user(
            session,
            feedback_id,
            message,
            message.from_user.username
        )
        
        state_manager.delete_state(chat_id, user_id)
        
        if success:
            await message.answer("✅ Ответ отправлен, фидбек удалён из базы.")
        else:
            await message.answer(
                "⚠️ Не удалось отправить ответ (пользователь, возможно, "
                "заблокировал бота). Фидбек удалён."
            )

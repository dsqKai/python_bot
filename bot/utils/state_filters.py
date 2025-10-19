"""
Фильтры состояний для обработчиков
"""
from typing import List
from aiogram.types import Message, CallbackQuery

from bot.services.state_manager import state_manager


class StateFilter:
    """Общий фильтр для проверки состояния пользователя"""
    
    def __init__(self, required_actions: List[str]):
        """
        Args:
            required_actions: Список действий, при которых фильтр должен срабатывать
        """
        self.required_actions = required_actions
    
    def __call__(self, message: Message) -> bool:
        """Проверяет, находится ли пользователь в нужном состоянии"""
        user_id = message.from_user.id
        chat_id = message.chat.id
        
        state = state_manager.get_state(chat_id, user_id)
        if not state:
            return False
        
        action = state.get('action')
        return action in self.required_actions


class CallbackStateFilter:
    """Фильтр состояний для callback запросов"""
    
    def __init__(self, required_actions: List[str]):
        """
        Args:
            required_actions: Список действий, при которых фильтр должен срабатывать
        """
        self.required_actions = required_actions
    
    def __call__(self, callback: CallbackQuery) -> bool:
        """Проверяет, находится ли пользователь в нужном состоянии"""
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        
        state = state_manager.get_state(chat_id, user_id)
        if not state:
            return False
        
        action = state.get('action')
        return action in self.required_actions


def has_state(required_actions: List[str]) -> StateFilter:
    """
    Удобная функция для создания фильтра состояний
    
    Args:
        required_actions: Список действий
        
    Returns:
        StateFilter: Настроенный фильтр
    """
    return StateFilter(required_actions)


def has_callback_state(required_actions: List[str]) -> CallbackStateFilter:
    """
    Удобная функция для создания фильтра состояний для callback
    
    Args:
        required_actions: Список действий
        
    Returns:
        CallbackStateFilter: Настроенный фильтр
    """
    return CallbackStateFilter(required_actions)

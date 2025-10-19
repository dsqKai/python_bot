"""
Менеджер состояний для интерактивных команд
"""
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import asyncio


class InteractiveStateManager:
    """Менеджер временных состояний для многошаговых команд"""
    
    def __init__(self, ttl_seconds: int = 60):
        """
        Args:
            ttl_seconds: Время жизни состояния в секундах
        """
        self.ttl = ttl_seconds
        self.states: Dict[str, Dict[str, Any]] = {}
        self._cleanup_task = None
        
    async def start_cleanup_task(self):
        """Запустить задачу очистки состояний"""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    def _get_key(self, chat_id: int, user_id: int) -> str:
        """Получить ключ для состояния"""
        return f"{chat_id}:{user_id}"
    
    def set_state(
        self,
        chat_id: int,
        user_id: int,
        state: Dict[str, Any]
    ):
        """
        Установить состояние
        
        Args:
            chat_id: ID чата
            user_id: ID пользователя
            state: Данные состояния
        """
        key = self._get_key(chat_id, user_id)
        state['expires_at'] = datetime.now() + timedelta(seconds=self.ttl)
        self.states[key] = state
    
    def get_state(
        self,
        chat_id: int,
        user_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Получить состояние
        
        Args:
            chat_id: ID чата
            user_id: ID пользователя
            
        Returns:
            Данные состояния или None
        """
        key = self._get_key(chat_id, user_id)
        state = self.states.get(key)
        
        if state:
            # Проверяем срок действия
            if datetime.now() < state.get('expires_at', datetime.now()):
                return state
            else:
                # Удаляем устаревшее состояние
                del self.states[key]
        
        return None
    
    def update_state(
        self,
        chat_id: int,
        user_id: int,
        new_data: Dict[str, Any]
    ):
        """
        Обновить состояние
        
        Args:
            chat_id: ID чата
            user_id: ID пользователя
            new_data: Новые данные для обновления
        """
        key = self._get_key(chat_id, user_id)
        state = self.states.get(key)
        
        if state:
            state.update(new_data)
            state['expires_at'] = datetime.now() + timedelta(seconds=self.ttl)
            self.states[key] = state
    
    def delete_state(
        self,
        chat_id: int,
        user_id: int
    ):
        """
        Удалить состояние
        
        Args:
            chat_id: ID чата
            user_id: ID пользователя
        """
        key = self._get_key(chat_id, user_id)
        if key in self.states:
            del self.states[key]
    
    def cleanup_expired(self):
        """Очистить устаревшие состояния"""
        now = datetime.now()
        expired_keys = [
            key for key, state in self.states.items()
            if state.get('expires_at', now) < now
        ]
        
        for key in expired_keys:
            del self.states[key]
    
    async def _cleanup_loop(self):
        """Периодическая очистка устаревших состояний"""
        while True:
            await asyncio.sleep(30)  # Каждые 30 секунд
            self.cleanup_expired()


# Глобальный экземпляр
state_manager = InteractiveStateManager()

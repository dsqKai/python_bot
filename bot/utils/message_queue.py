"""
Очередь сообщений для обхода лимитов Telegram API
Telegram имеет лимит ~30 сообщений в секунду
"""
import asyncio
from typing import Callable, Any, Optional, Dict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from loguru import logger


class MessagePriority(Enum):
    """Приоритет сообщения"""
    HIGH = 1      # Важные уведомления
    NORMAL = 2    # Обычные сообщения
    LOW = 3       # Массовые рассылки


@dataclass(order=True)
class QueuedMessage:
    """Сообщение в очереди"""
    priority: int = field(compare=True)
    timestamp: float = field(compare=True)
    func: Callable = field(compare=False)
    args: tuple = field(default_factory=tuple, compare=False)
    kwargs: dict = field(default_factory=dict, compare=False)
    retry_count: int = field(default=0, compare=False)
    max_retries: int = field(default=3, compare=False)


class MessageQueue:
    """
    Асинхронная очередь сообщений с rate limiting
    Использует asyncio.PriorityQueue для управления приоритетами
    """
    
    def __init__(
        self,
        rate_limit: int = 30,  # сообщений в секунду
        max_workers: int = 5,
        retry_delay: float = 1.0
    ):
        self.rate_limit = rate_limit
        self.max_workers = max_workers
        self.retry_delay = retry_delay
        
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.workers: list[asyncio.Task] = []
        self.running = False
        
        # Статистика
        self.sent_count = 0
        self.failed_count = 0
        self.retry_count = 0
        
        # Rate limiting
        self.last_send_times: list[float] = []
        self.lock = asyncio.Lock()
    
    async def start(self):
        """Запустить обработку очереди"""
        if self.running:
            return
        
        self.running = True
        logger.info(f"Starting message queue with {self.max_workers} workers")
        
        # Создаем воркеры
        for i in range(self.max_workers):
            worker = asyncio.create_task(self._worker(i))
            self.workers.append(worker)
    
    async def stop(self):
        """Остановить обработку очереди"""
        self.running = False
        
        # Ждем завершения всех воркеров
        for worker in self.workers:
            worker.cancel()
        
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()
        
        logger.info(
            f"Message queue stopped. Sent: {self.sent_count}, "
            f"Failed: {self.failed_count}, Retries: {self.retry_count}"
        )
    
    async def enqueue(
        self,
        func: Callable,
        *args,
        priority: MessagePriority = MessagePriority.NORMAL,
        max_retries: int = 3,
        **kwargs
    ):
        """
        Добавить сообщение в очередь
        
        Args:
            func: Функция отправки (например, bot.send_message)
            *args: Позиционные аргументы
            priority: Приоритет сообщения
            max_retries: Максимальное количество попыток
            **kwargs: Именованные аргументы
        """
        message = QueuedMessage(
            priority=priority.value,
            timestamp=datetime.now().timestamp(),
            func=func,
            args=args,
            kwargs=kwargs,
            max_retries=max_retries
        )
        
        await self.queue.put(message)
    
    async def _worker(self, worker_id: int):
        """Воркер для обработки сообщений из очереди"""
        logger.debug(f"Worker {worker_id} started")
        
        while self.running:
            try:
                # Получаем сообщение из очереди
                message = await asyncio.wait_for(
                    self.queue.get(),
                    timeout=1.0
                )
                
                # Проверяем rate limit
                await self._wait_for_rate_limit()
                
                # Отправляем сообщение
                success = await self._send_message(message)
                
                # Если неудачно и есть попытки - возвращаем в очередь
                if not success and message.retry_count < message.max_retries:
                    message.retry_count += 1
                    self.retry_count += 1
                    
                    # Небольшая задержка перед повтором
                    await asyncio.sleep(self.retry_delay * message.retry_count)
                    await self.queue.put(message)
                    
                    logger.warning(
                        f"Message retry {message.retry_count}/{message.max_retries}"
                    )
                
                self.queue.task_done()
                
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
        
        logger.debug(f"Worker {worker_id} stopped")
    
    async def _wait_for_rate_limit(self):
        """Ожидание для соблюдения rate limit"""
        async with self.lock:
            now = datetime.now().timestamp()
            
            # Удаляем старые записи (старше 1 секунды)
            self.last_send_times = [
                t for t in self.last_send_times 
                if now - t < 1.0
            ]
            
            # Если достигли лимита - ждем
            if len(self.last_send_times) >= self.rate_limit:
                wait_time = 1.0 - (now - self.last_send_times[0])
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    self.last_send_times.clear()
            
            # Записываем время отправки
            self.last_send_times.append(datetime.now().timestamp())
    
    async def _send_message(self, message: QueuedMessage) -> bool:
        """
        Отправить сообщение
        
        Returns:
            True если успешно, False если ошибка
        """
        try:
            # Вызываем функцию отправки
            await message.func(*message.args, **message.kwargs)
            self.sent_count += 1
            return True
            
        except Exception as e:
            self.failed_count += 1
            
            # Проверяем тип ошибки
            error_str = str(e).lower()
            
            # Если пользователь заблокировал бота - не повторяем
            if any(x in error_str for x in ['blocked', 'user is deactivated', 'chat not found']):
                logger.warning(f"User blocked bot or chat not found: {e}")
                return True  # Не повторяем
            
            # Если флуд контроль - увеличиваем задержку
            if 'too many requests' in error_str or 'retry after' in error_str:
                logger.warning(f"Rate limit hit: {e}")
                await asyncio.sleep(5)  # Ждем 5 секунд
            
            if 'message is not modified' in error_str:
                logger.debug(f"Ignoring noop edit: {e}")
                return True
            
            logger.error(f"Failed to send message: {e}")
            return False
    
    def get_stats(self) -> Dict[str, int]:
        """Получить статистику очереди"""
        return {
            "queue_size": self.queue.qsize(),
            "sent_count": self.sent_count,
            "failed_count": self.failed_count,
            "retry_count": self.retry_count,
            "workers": len(self.workers)
        }

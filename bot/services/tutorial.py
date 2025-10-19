"""
Интерактивное обучение для новых пользователей
"""
import asyncio
import re
from typing import Optional, List, Dict
from aiogram import Bot
from aiogram.types import Message, CallbackQuery
from loguru import logger

from bot.utils import escape_markdown_v2, build_skip_keyboard
from bot.services.state_manager import state_manager


class TutorialStep:
    """Шаг обучения"""
    
    def __init__(
        self,
        instruction: str,
        example: str,
        regex_pattern: str
    ):
        self.instruction = instruction
        self.example = example
        self.regex = re.compile(regex_pattern, re.IGNORECASE)


class Tutorial:
    """Интерактивное обучение пользователя"""
    
    def __init__(self, bot: Bot, chat_id: int, user_id: int):
        self.bot = bot
        self.chat_id = chat_id
        self.user_id = user_id
        self.current_step = 0
        self.tutorial_message_ids: List[int] = []
        
        # Шаги обучения
        self.steps = [
            TutorialStep(
                instruction=(
                    "📅 Твое расписание на день\n"
                    "Хочешь узнать, какие пары тебя ждут сегодня? "
                    "Просто введи команду /day — и бот покажет все занятия, "
                    "их время, преподавателей и аудитории.\n"
                    "Так ты сможешь легко спланировать свой день и ничего не пропустить! 🚀"
                ),
                example="/day",
                regex_pattern=r'^/day\s*$'
            ),
            TutorialStep(
                instruction=(
                    "📚 Расписание другой группы\n"
                    "Нужно посмотреть расписание другой группы? "
                    "Просто введи команду с номером группы, например: /day 241-362. "
                    "Так ты сможешь быстро переключаться между группами или сравнивать расписания! 🔄"
                ),
                example="/day 241-362",
                regex_pattern=r'^/day\s+[0-9A-Za-zА-Яа-яЁё]{3}-[0-9A-Za-zА-Яа-яЁё]{3,4}$'
            ),
            TutorialStep(
                instruction=(
                    "🕑 Какая сейчас пара?\n"
                    "Введи /cur — и бот покажет, какая пара идёт прямо сейчас. "
                    "Если занятие активно, ты увидишь предмет, преподавателя и аудиторию. "
                    "Ничего не пропустишь! ✅"
                ),
                example="/cur",
                regex_pattern=r'^/cur\s*$'
            ),
            TutorialStep(
                instruction=(
                    "ℹ️ Все команды под рукой\n"
                    "Чтобы узнать, что умеет бот, просто введи /help — "
                    "я покажу все доступные команды. С ними управлять расписанием — легко! 🚀"
                ),
                example="/help",
                regex_pattern=r'^/help\s*$'
            )
        ]
    
    async def start(self):
        """Начать обучение"""
        # Устанавливаем состояние
        state_manager.set_state(self.chat_id, self.user_id, {
            'tutorial': True,
            'step': 0
        })
        
        # Отправляем приветствие
        try:
            await self.bot.send_message(
                self.chat_id,
                escape_markdown_v2(
                    "👋 Привет! Я твой помощник по учебному расписанию!\n"
                    "Сейчас я кратко расскажу, как быстро узнавать свои пары, "
                    "проверять текущее занятие и настраивать группу. Поехали!"
                ),
                parse_mode="MarkdownV2"
            )
        except Exception as e:
            logger.error(f"Error sending tutorial welcome: {e}")
        
        # Отправляем первый шаг
        await self.send_current_step()
    
    async def send_current_step(self):
        """Отправить текущий шаг"""
        if self.current_step >= len(self.steps):
            await self.finish_tutorial()
            return
        
        step = self.steps[self.current_step]
        
        try:
            # Экранируем основной текст, но для кода используем правильный markdown
            instruction_escaped = escape_markdown_v2(step.instruction)
            example_escaped = escape_markdown_v2(step.example)
            msg = await self.bot.send_message(
                self.chat_id,
                f"{instruction_escaped}\nПример: `{example_escaped}`",
                parse_mode="MarkdownV2",
                reply_markup=build_skip_keyboard("tutorial:skip")
            )
            
            self.tutorial_message_ids.append(msg.message_id)
            
            # Обновляем состояние
            state_manager.update_state(
                self.chat_id,
                self.user_id,
                {'current_message_id': msg.message_id}
            )
            
        except Exception as e:
            logger.error(f"Error sending tutorial step: {e}")
    
    async def process_message(self, message: Message) -> bool:
        """
        Обработать сообщение в контексте обучения
        
        Args:
            message: Сообщение пользователя
            
        Returns:
            True если сообщение обработано обучением
        """
        if not message.text:
            return False
        
        step = self.steps[self.current_step]
        
        if step.regex.match(message.text):
            # Правильная команда
            await self.remove_tutorial_messages()
            
            # Переходим к следующему шагу
            self.current_step += 1
            
            if self.current_step < len(self.steps):
                state_manager.update_state(
                    self.chat_id,
                    self.user_id,
                    {'step': self.current_step}
                )
                
                # Небольшая задержка перед следующим шагом
                await asyncio.sleep(1.5)
                await self.send_current_step()
            else:
                await self.finish_tutorial()
            
            # Возвращаем False чтобы команда выполнилась
            return False
        else:
            # Неправильная команда
            try:
                # Экранируем текст, но для кода используем правильный markdown
                error_text = escape_markdown_v2(
                    f"❌ Ой, кажется, такой команды нет!\n"
                    f"Попробуй вот так: \n"
                )
                example_escaped = escape_markdown_v2(step.example)
                error_text += f"`{example_escaped}`,\n"
                error_text += escape_markdown_v2("Если что — /help всегда выручит! 💡")
                
                error_msg = await self.bot.send_message(
                    self.chat_id,
                    error_text,
                    parse_mode="MarkdownV2",
                    reply_markup=build_skip_keyboard("tutorial:skip")
                )
                self.tutorial_message_ids.append(error_msg.message_id)
            except Exception as e:
                logger.error(f"Error sending tutorial error message: {e}")
            
            return True  # Блокируем обработку команды
    
    async def process_callback(self, callback: CallbackQuery) -> bool:
        """
        Обработать callback в контексте обучения
        
        Args:
            callback: Callback query
            
        Returns:
            True если callback обработан обучением
        """
        if callback.data == "tutorial:skip":
            await callback.answer("Обучение пропущено.")
            await self.finish(
                "📚 Кажется, ты пропустил обучение!\n"
                "Ничего страшного — я всё равно помогу. "
                "Введи /help, и я расскажу, как работать с ботом. 😊"
            )
            return True
        
        return False
    
    async def remove_tutorial_messages(self):
        """Удалить сообщения обучения"""
        for message_id in self.tutorial_message_ids:
            try:
                await self.bot.delete_message(self.chat_id, message_id)
            except Exception:
                pass  # Игнорируем ошибки удаления
        
        self.tutorial_message_ids.clear()
    
    async def finish(self, final_message: str):
        """
        Завершить обучение
        
        Args:
            final_message: Финальное сообщение
        """
        await self.remove_tutorial_messages()
        
        try:
            await self.bot.send_message(
                self.chat_id,
                escape_markdown_v2(final_message),
                parse_mode="MarkdownV2"
            )
        except Exception as e:
            logger.error(f"Error sending tutorial final message: {e}")
        
        # Удаляем состояние
        state_manager.delete_state(self.chat_id, self.user_id)
    
    async def finish_tutorial(self):
        """Успешное завершение обучения"""
        await self.finish(
            "🎉 Обучение пройдено! Теперь ты знаешь, как пользоваться ботом.\n"
            "Если что-то забудешь — просто введи /help, и я напомню. Удачного дня! ✨"
        )

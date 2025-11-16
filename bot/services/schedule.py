"""
Сервис для работы с расписанием
"""
import re
import json
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta
from loguru import logger

from config import Constants
from database.models import SemesterBoundary, Holiday
from database.repository import GlobalGroupRepository
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from bot.services.api_client import api_client


class ScheduleCache:
    """Кэш расписаний"""
    
    def __init__(self):
        self.cache: Dict[str, Tuple[any, datetime]] = {}
    
    def get(self, key: str) -> Optional[any]:
        """Получить из кэша"""
        if key in self.cache:
            data, expires_at = self.cache[key]
            if datetime.now() < expires_at:
                return data
            else:
                del self.cache[key]
        return None
    
    def set(self, key: str, data: any, ttl_hours: int = 24):
        """Сохранить в кэш"""
        expires_at = datetime.now() + timedelta(hours=ttl_hours)
        self.cache[key] = (data, expires_at)
    
    def clear(self):
        """Очистить кэш"""
        self.cache.clear()


class ScheduleService:
    """Сервис для получения и обработки расписания"""
    
    def __init__(self):
        self.cache = ScheduleCache()
        self.times = Constants.SCHEDULE_TIMES
        self.api = api_client
    
    async def fetch_schedule(self, group: str, is_session: bool = False) -> Optional[Dict]:
        """
        Получить расписание группы
        
        Args:
            group: Номер группы
            is_session: Флаг сессии (экзамены)
            
        Returns:
            Данные расписания или None
        """
        # Проверяем кэш
        cache_key = f"schedule:{group}:{is_session}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        
        # Endpoint согласно спецификации: GET /api/v1/schedules/group/number/{number}
        endpoint = f"/api/v1/schedules/group/number/{group}"
        
        # Добавляем параметр session если нужно
        params = {}
        if is_session:
            params["session"] = 1
        
        # Выполняем запрос через API клиент
        data = await self.api.get(endpoint, params=params)
        
        if data:
            # Сохраняем в кэш
            self.cache.set(cache_key, data)
        else:
            logger.warning(f"Failed to fetch schedule for group {group}")
        
        return data
    
    async def is_holiday_or_vacation(
        self,
        session: AsyncSession,
        date: datetime,
        group: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Проверить, является ли дата праздником или каникулами
        
        Args:
            session: Сессия БД
            date: Дата для проверки
            group: Номер группы
            
        Returns:
            (is_holiday, holiday_type)
        """
        date_str = date.strftime("%d.%m.%Y")
        
        result = await session.execute(
            select(Holiday).where(
                ((Holiday.group == group) | (Holiday.group == "all")) &
                (Holiday.start_date <= date_str) &
                (Holiday.end_date >= date_str)
            )
        )
        holiday = result.scalar_one_or_none()
        
        if holiday:
            return True, holiday.type
        return False, None
    
    def get_schedule_for_date(
        self,
        schedule_data: Dict,
        date: datetime
    ) -> List[Dict]:
        """
        Получить расписание на конкретную дату
        
        Args:
            schedule_data: Данные расписания (Week format)
            date: Дата
            
        Returns:
            Список занятий
        """
        if not schedule_data:
            return []
        
        # Маппинг дней недели на английские названия
        weekday_names = {
            0: 'monday',
            1: 'tuesday', 
            2: 'wednesday',
            3: 'thursday',
            4: 'friday',
            5: 'saturday',
            6: 'sunday'
        }
        
        # Получаем название дня недели
        weekday = date.weekday()  # 0 = понедельник
        weekday_name = weekday_names.get(weekday, '')
        
        # Получаем данные для этого дня недели
        day_data = schedule_data.get(weekday_name, {})
        
        if not day_data or not isinstance(day_data, dict):
            return []
        
        lessons = []
        
        # Получаем все пары на этот день
        for pair_num, pair_list in day_data.items():
            if not isinstance(pair_list, list):
                continue
            
            # Обрабатываем каждую пару
            for pair in pair_list:
                if self._is_lesson_on_date(pair, date):
                    # Добавляем номер пары в данные
                    pair_with_num = pair.copy()
                    pair_with_num['pair_number'] = int(pair_num)
                    lessons.append(pair_with_num)
        
        # Сортируем по номеру пары
        lessons.sort(key=lambda x: x.get('pair_number', 0))
        
        return lessons
    
    def _is_lesson_on_date(self, lesson: Dict, date: datetime) -> bool:
        """
        Проверить, проводится ли занятие в указанную дату
        
        Args:
            lesson: Данные занятия (Pair согласно API)
            date: Дата
            
        Returns:
            True если занятие проводится
        """
        # Проверяем поля start_date и end_date согласно спецификации API
        start_date_str = lesson.get('start_date')
        end_date_str = lesson.get('end_date')
        
        # Если нет ограничений по дате - занятие проводится
        if not start_date_str or not end_date_str:
            return True
        
        try:
            # Формат даты в API: "2025-02-01"
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
            
            # Проверяем попадает ли дата в диапазон
            return start_date.date() <= date.date() <= end_date.date()
            
        except ValueError as e:
            logger.warning(f"Invalid date format in lesson: {e}")
            return True
    
    def format_lesson(
        self,
        lesson: Dict,
        lesson_number: int = None,
        schedule_type: str = '0',
        subgroup: Optional[int] = None
    ) -> str:
        """
        Форматировать занятие для вывода
        
        Args:
            lesson: Данные занятия (Pair согласно API)
            lesson_number: Номер пары (если None, берется из lesson['pair_number'])
            schedule_type: Тип расписания (0, 1, 2)
            subgroup: Фильтр по подгруппе
            
        Returns:
            Отформатированная строка
        """
        # Получаем номер пары
        if lesson_number is None:
            lesson_number = lesson.get('pair_number', 1)
        
        # Получаем время занятия
        time_slot = self.times.get(schedule_type, {}).get(lesson_number, "??:??-??:??")
        
        # Название предмета (согласно API)
        subject = lesson.get('subject', 'Предмет не указан')
        
        # Тип занятия (согласно API)
        lesson_type = lesson.get('type', '')
        
        # Преподаватели (согласно API - массив)
        teachers = lesson.get('teachers', [])
        
        # Аудитории (согласно API - массив)
        rooms = lesson.get('rooms', [])
        
        # Локация (согласно API)
        location = lesson.get('location', '')
        
        # Ссылка (согласно API)
        link = lesson.get('link', '')
        
        # Формируем строку
        result = f"🕐 {time_slot}\n"
        result += f"📚 {subject}"
        
        # Добавляем тип занятия
        if lesson_type:
            result += f" ({lesson_type})"
        result += "\n"
        
        # Преподаватели
        if teachers:
            if isinstance(teachers, list):
                teachers_str = ", ".join(teachers)
            else:
                teachers_str = str(teachers)
            result += f"👨‍🏫 {teachers_str}\n"
        
        # Аудитории и локация
        if rooms:
            if isinstance(rooms, list):
                rooms_str = ", ".join(rooms)
            else:
                rooms_str = str(rooms)
            
            # Проверяем онлайн по ссылке или названию аудитории
            if link and ('http://' in link or 'https://' in link):
                result += f"💻 Онлайн: {link}\n"
            else:
                result += f"🏛 {rooms_str}"
                if location:
                    result += f" ({location})"
                result += "\n"
        elif location:
            result += f"🏛 {location}\n"
        
        # Ссылка (если есть и не была использована выше)
        if link and not (rooms and ('http://' in link or 'https://' in link)):
            result += f"🔗 {link}\n"
        
        return result
    
    def _get_online_lesson_info(self, auditories: str) -> Optional[str]:
        """
        Извлечь информацию об онлайн-занятии
        
        Args:
            auditories: Строка с аудиториями
            
        Returns:
            Информация об онлайн или None
        """
        if not auditories:
            return None
        
        keywords = ['online', 'вебинар', 'webinar', 'zoom', 'teams', 'meet']
        auditories_lower = auditories.lower()
        
        for keyword in keywords:
            if keyword in auditories_lower:
                # Пытаемся извлечь URL
                url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
                urls = re.findall(url_pattern, auditories)
                
                if urls:
                    return urls[0]
                return "Да"
        
        return None
    
    async def get_day_response(
        self,
        session: AsyncSession,
        group: str,
        date: datetime,
        subgroup: Optional[int] = None,
        is_session: bool = False
    ) -> str:
        """
        Получить текст расписания на день
        
        Args:
            session: Сессия БД
            group: Номер группы
            date: Дата
            subgroup: Фильтр по подгруппе
            is_session: Флаг сессии (экзамены)
            
        Returns:
            Текст сообщения
        """
        # Проверяем праздники
        is_holiday, holiday_type = await self.is_holiday_or_vacation(session, date, group)
        if is_holiday:
            return f"🎉 {date.strftime('%d.%m.%Y')} - {holiday_type}!\nЗанятий нет."
        
        # Получаем расписание
        schedule_data = await self.fetch_schedule(group, is_session)
        if not schedule_data:
            return f"❌ Не удалось получить расписание для группы {group}"
        
        # Получаем занятия на дату
        lessons = self.get_schedule_for_date(schedule_data, date)
        
        if not lessons:
            return f"📅 {date.strftime('%d.%m.%Y')} ({self._get_weekday_name(date.weekday())})\n\nЗанятий нет 🎉"
        
        # Формируем ответ
        response = f"📅 {date.strftime('%d.%m.%Y')} ({self._get_weekday_name(date.weekday())})\n"
        response += f"Группа: {group}\n\n"
        
        # Тип расписания (можно получить из данных или использовать по умолчанию)
        schedule_type = '0'  # По умолчанию используем стандартное расписание
        
        for lesson in lessons:
            formatted = self.format_lesson(lesson, schedule_type=schedule_type, subgroup=subgroup)
            if formatted:
                response += formatted + "\n"
        
        return response.strip()
    
    def _get_weekday_name(self, weekday: int) -> str:
        """Получить название дня недели"""
        names = [
            "Понедельник", "Вторник", "Среда", 
            "Четверг", "Пятница", "Суббота", "Воскресенье"
        ]
        return names[weekday]
    
    async def get_current_lesson(
        self,
        session: AsyncSession,
        group: str,
        is_session: bool = False
    ) -> str:
        """
        Получить текущее занятие
        
        Args:
            session: Сессия БД
            group: Номер группы
            is_session: Флаг сессии (экзамены)
            
        Returns:
            Текст сообщения
        """
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        
        # Получаем расписание
        schedule_data = await self.fetch_schedule(group, is_session)
        if not schedule_data:
            return f"❌ Не удалось получить расписание для группы {group}"
        
        # Получаем занятия на сегодня
        lessons = self.get_schedule_for_date(schedule_data, now)
        
        if not lessons:
            return "📚 Сейчас занятий нет"
        
        # Тип расписания
        schedule_type = '0'
        times = self.times.get(schedule_type, {})
        
        # Ищем текущее занятие
        for lesson in lessons:
            pair_number = lesson.get('pair_number', 0)
            time_slot = times.get(pair_number, "")
            if not time_slot:
                continue
            
            start_time, end_time = time_slot.split('-')
            
            # Сравниваем время
            if start_time <= current_time <= end_time:
                response = f"⏰ Текущее занятие ({time_slot}):\n\n"
                response += self.format_lesson(lesson, schedule_type=schedule_type)
                return response
        
        return "📚 Сейчас окно между парами"
    
    async def fetch_groups(self) -> Optional[List[Dict]]:
        """
        Получить список всех групп
        
        Returns:
            Список групп или None
        """
        # Проверяем кэш
        cache_key = "groups:all"
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        
        # Endpoint: GET /api/v1/groups/
        endpoint = "/api/v1/groups/"
        
        # Выполняем запрос через API клиент
        data = await self.api.get(endpoint)
        
        if data and "groups" in data:
            groups_data = data["groups"]
            
            # Сохраняем в кэш на 7 дней
            self.cache.set(cache_key, groups_data, ttl_hours=168)
            
            return groups_data
        
        return None
    
    async def fetch_teachers(self) -> Optional[List[Dict]]:
        """
        Получить список всех преподавателей
        
        Returns:
            Список преподавателей или None
        """
        # Проверяем кэш
        cache_key = "teachers:all"
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        
        # Endpoint: GET /api/v1/teachers/
        endpoint = "/api/v1/teachers/"
        
        # Выполняем запрос через API клиент
        data = await self.api.get(endpoint)
        
        if data and "teachers" in data:
            teachers_data = data["teachers"]
            
            # Сохраняем в кэш на 7 дней
            self.cache.set(cache_key, teachers_data, ttl_hours=168)
            
            return teachers_data
        
        return None
    
    async def fetch_schedule_by_teacher(
        self, 
        teacher_fullname: str, 
        is_session: bool = False
    ) -> Optional[Dict]:
        """
        Получить расписание преподавателя
        
        Args:
            teacher_fullname: ФИО преподавателя
            is_session: Флаг сессии
            
        Returns:
            Данные расписания или None
        """
        # Проверяем кэш
        cache_key = f"schedule:teacher:{teacher_fullname}:{is_session}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        
        # Endpoint: GET /api/v1/schedules/teacher/fn/{fn}
        endpoint = f"/api/v1/schedules/teacher/fn/{teacher_fullname}"
        
        params = {}
        if is_session:
            params["session"] = 1
        
        # Выполняем запрос через API клиент
        data = await self.api.get(endpoint, params=params)
        
        if data:
            # Сохраняем в кэш
            self.cache.set(cache_key, data)
        
        return data
    
    async def fetch_schedule_by_room(
        self, 
        room_number: str, 
        is_session: bool = False
    ) -> Optional[Dict]:
        """
        Получить расписание аудитории
        
        Args:
            room_number: Номер аудитории
            is_session: Флаг сессии
            
        Returns:
            Данные расписания или None
        """
        # Проверяем кэш
        cache_key = f"schedule:room:{room_number}:{is_session}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        
        # Endpoint: GET /api/v1/schedules/room/number/{number}
        endpoint = f"/api/v1/schedules/room/number/{room_number}"
        
        params = {}
        if is_session:
            params["session"] = 1
        
        # Выполняем запрос через API клиент
        data = await self.api.get(endpoint, params=params)
        
        if data:
            # Сохраняем в кэш
            self.cache.set(cache_key, data)
        
        return data
    
    def _time_to_minutes(self, time_str: str) -> int:
        """Конвертировать время HH:MM в минуты от начала дня"""
        hours, minutes = map(int, time_str.split(':'))
        return hours * 60 + minutes
    
    def _minutes_to_time(self, minutes: int) -> str:
        """Конвертировать минуты от начала дня в HH:MM"""
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours:02d}:{mins:02d}"
    
    def _get_busy_intervals(self, lessons: List[Dict], schedule_type: str = '0') -> List[Tuple[int, int, Optional[str]]]:
        """
        Получить занятые временные интервалы в минутах с локацией
        
        Args:
            lessons: Список занятий
            schedule_type: Тип расписания
            
        Returns:
            Список кортежей (start_minutes, end_minutes, location)
        """
        times = self.times.get(schedule_type, {})
        intervals = []
        
        for lesson in lessons:
            pair_num = lesson.get('pair_number', 0)
            time_slot = times.get(pair_num, "")
            if not time_slot:
                continue
            
            start_time, end_time = time_slot.split('-')
            start_minutes = self._time_to_minutes(start_time)
            end_minutes = self._time_to_minutes(end_time)
            location = lesson.get('location', '')
            intervals.append((start_minutes, end_minutes, location))
        
        # Сортируем и объединяем пересекающиеся интервалы с одинаковой локацией
        if not intervals:
            return []
        
        intervals.sort()
        merged = [intervals[0]]
        
        for current in intervals[1:]:
            last = merged[-1]
            # Если интервалы пересекаются или идут встык И имеют одинаковую локацию, объединяем
            if current[0] <= last[1] and current[2] == last[2]:
                merged[-1] = (last[0], max(last[1], current[1]), last[2])
            else:
                merged.append(current)
        
        return merged
    
    def _get_group_location_timeline(
        self, 
        busy_intervals: List[Tuple[int, int, str]],
        day_start: int,
        day_end: int
    ) -> List[Tuple[int, int, Optional[str]]]:
        """
        Построить временную линию локаций группы на день
        
        Args:
            busy_intervals: Занятые интервалы с локациями
            day_start: Начало дня в минутах
            day_end: Конец дня в минутах
            
        Returns:
            Список (start, end, location) где location - где находится группа в это время
            None означает что у группы нет пар в этот день вообще
        """
        if not busy_intervals:
            # У группы нет пар вообще - можно встретиться где угодно
            return [(day_start, day_end, None)]
        
        # Собираем все уникальные локации за день
        locations_in_day = set(loc for _, _, loc in busy_intervals if loc)
        
        # Если у группы все пары без указания локации
        if not locations_in_day:
            return [(day_start, day_end, "")]
        
        # Строим временную линию
        timeline = []
        current_time = day_start
        
        # Сортируем интервалы по времени
        sorted_intervals = sorted(busy_intervals, key=lambda x: x[0])
        
        for i, (start, end, location) in enumerate(sorted_intervals):
            # Период до пары - группа находится в локации этой пары
            # (они уже приехали или приедут к началу)
            if current_time < start:
                timeline.append((current_time, start, location))
            
            # Период самой пары
            timeline.append((start, end, location))
            current_time = end
            
            # После пары группа остается в этой локации до следующей пары
            # или до конца дня
            if i < len(sorted_intervals) - 1:
                next_start, next_end, next_location = sorted_intervals[i + 1]
                if next_location != location:
                    # Следующая пара в другой локации - нужно время на переезд
                    # В промежутке группа недоступна для встреч
                    timeline.append((end, next_start, f"переезд_{location}_to_{next_location}"))
                else:
                    # Следующая пара в той же локации
                    timeline.append((end, next_start, location))
            else:
                # Последняя пара - группа остается в этой локации до конца дня
                if current_time < day_end:
                    timeline.append((current_time, day_end, location))
        
        return timeline
    
    def _find_free_intervals_with_location(
        self, 
        all_busy_intervals: List[List[Tuple[int, int, str]]], 
        min_duration: int = 0
    ) -> List[Tuple[int, int, Dict[str, int]]]:
        """
        Найти общие свободные интервалы с учетом локаций
        
        Args:
            all_busy_intervals: Список занятых интервалов с локацией для каждой группы
            min_duration: Минимальная длительность окна в минутах
            
        Returns:
            Список свободных интервалов (start_minutes, end_minutes, location_info)
        """
        # Рабочий день: 9:00 - 21:00
        day_start = self._time_to_minutes("09:00")
        day_end = self._time_to_minutes("21:00")
        
        # Строим временные линии для каждой группы
        timelines = []
        for busy_intervals in all_busy_intervals:
            timeline = self._get_group_location_timeline(busy_intervals, day_start, day_end)
            timelines.append(timeline)
        
        # Создаем список всех временных точек
        time_points = set([day_start, day_end])
        for timeline in timelines:
            for start, end, _ in timeline:
                time_points.add(start)
                time_points.add(end)
        
        time_points = sorted(time_points)
        
        # Анализируем каждый временной интервал
        free_intervals = []
        
        for i in range(len(time_points) - 1):
            interval_start = time_points[i]
            interval_end = time_points[i + 1]
            
            if interval_end - interval_start < min_duration:
                continue
            
            # Определяем где находится каждая группа в этот интервал
            groups_locations = {}
            
            for group_idx, timeline in enumerate(timelines):
                for start, end, location in timeline:
                    # Проверяем пересечение с текущим интервалом
                    if start <= interval_start and end >= interval_end:
                        groups_locations[group_idx] = location
                        break
            
            # Проверяем условия для общего окна
            if len(groups_locations) != len(timelines):
                continue
            
            locations = list(groups_locations.values())
            
            # Фильтруем периоды переезда
            if any(loc and loc.startswith("переезд_") for loc in locations):
                continue
            
            # Проверяем, заняты ли группы
            is_any_busy = False
            for group_idx, busy_intervals in enumerate(all_busy_intervals):
                for start, end, _ in busy_intervals:
                    if start < interval_end and end > interval_start:
                        is_any_busy = True
                        break
                if is_any_busy:
                    break
            
            if is_any_busy:
                continue
            
            # Если все локации None - у всех групп нет пар вообще
            if all(loc is None for loc in locations):
                free_intervals.append((interval_start, interval_end, {"Любая": len(timelines)}))
            # Если все локации одинаковые (и не None)
            elif len(set(locations)) == 1 and locations[0]:
                free_intervals.append((interval_start, interval_end, {locations[0]: len(timelines)}))
        
        return free_intervals
    
    def _find_free_intervals(
        self, 
        all_busy_intervals: List[List[Tuple[int, int, str]]], 
        min_duration: int = 0
    ) -> List[Tuple[int, int]]:
        """
        Найти общие свободные интервалы (упрощенная версия без учета локации)
        
        Args:
            all_busy_intervals: Список занятых интервалов для каждой группы
            min_duration: Минимальная длительность окна в минутах
            
        Returns:
            Список свободных интервалов (start_minutes, end_minutes)
        """
        # Рабочий день: 9:00 - 21:00
        day_start = self._time_to_minutes("09:00")
        day_end = self._time_to_minutes("21:00")
        
        # Объединяем все занятые интервалы от всех групп (игнорируя локацию)
        all_busy = []
        for busy_intervals in all_busy_intervals:
            for start, end, _ in busy_intervals:
                all_busy.append((start, end))
        
        if not all_busy:
            # Весь день свободен
            duration = day_end - day_start
            if duration >= min_duration:
                return [(day_start, day_end)]
            return []
        
        # Сортируем и объединяем
        all_busy.sort()
        merged = [all_busy[0]]
        
        for current in all_busy[1:]:
            last = merged[-1]
            if current[0] <= last[1]:
                merged[-1] = (last[0], max(last[1], current[1]))
            else:
                merged.append(current)
        
        # Находим свободные промежутки
        free_intervals = []
        
        # Проверяем начало дня
        if merged[0][0] > day_start:
            duration = merged[0][0] - day_start
            if duration >= min_duration:
                free_intervals.append((day_start, merged[0][0]))
        
        # Проверяем промежутки между занятиями
        for i in range(len(merged) - 1):
            gap_start = merged[i][1]
            gap_end = merged[i + 1][0]
            duration = gap_end - gap_start
            if duration >= min_duration:
                free_intervals.append((gap_start, gap_end))
        
        # Проверяем конец дня
        if merged[-1][1] < day_end:
            duration = day_end - merged[-1][1]
            if duration >= min_duration:
                free_intervals.append((merged[-1][1], day_end))
        
        return free_intervals
    
    async def compare_groups(
        self,
        session: AsyncSession,
        groups: List[str],
        date: datetime,
        min_duration: int = 0,
        is_session: bool = False
    ) -> str:
        """
        Сравнить расписания нескольких групп и найти общие свободные окна
        
        Args:
            session: Сессия БД
            groups: Список групп для сравнения
            date: Дата для проверки
            min_duration: Минимальная длительность окна в минутах
            is_session: Флаг сессии
            
        Returns:
            Текст с результатами сравнения
        """
        if len(groups) < 2:
            return "❌ Для сравнения нужно указать минимум 2 группы"
        
        # Получаем расписания для всех групп
        schedules = {}
        for group in groups:
            schedule_data = await self.fetch_schedule(group, is_session)
            if not schedule_data:
                return f"❌ Не удалось получить расписание для группы {group}"
            lessons = self.get_schedule_for_date(schedule_data, date)
            schedules[group] = lessons
        
        # Определяем занятые временные интервалы для каждой группы
        schedule_type = '0'
        times = self.times.get(schedule_type, {})
        
        all_busy_intervals = []
        for group in groups:
            lessons = schedules[group]
            busy_intervals = self._get_busy_intervals(lessons, schedule_type)
            all_busy_intervals.append(busy_intervals)
        
        # Находим общие свободные окна с учетом локации
        free_intervals_with_loc = self._find_free_intervals_with_location(all_busy_intervals, min_duration)
        
        # Формируем ответ
        response = f"📊 Сравнение расписаний на {date.strftime('%d.%m.%Y')}\n"
        response += f"Группы: {', '.join(groups)}\n"
        if min_duration > 0:
            response += f"Минимальная длительность окна: {min_duration} мин\n"
        response += f"📍 Учитываются локации корпусов\n"
        response += "\n"
        
        if free_intervals_with_loc:
            response += "✅ Общие свободные окна:\n"
            for start, end, loc_info in free_intervals_with_loc:
                start_time = self._minutes_to_time(start)
                end_time = self._minutes_to_time(end)
                duration = end - start
                
                # Определяем локацию
                locations = list(loc_info.keys())
                if locations:
                    if locations[0] == "Любая":
                        loc_str = "обе группы свободны, можно выбрать любую локацию"
                    else:
                        loc_str = f"обе группы в {locations[0]}"
                    response += f"🕐 {start_time} - {end_time} ({duration} мин) — {loc_str}\n"
                else:
                    response += f"🕐 {start_time} - {end_time} ({duration} мин)\n"
        else:
            if min_duration > 0:
                response += f"❌ Нет общих свободных окон длительностью от {min_duration} минут\n"
            else:
                response += "❌ Нет общих свободных окон\n"
        
        # Показываем расписание каждой группы
        response += "\n📚 Расписание по группам:\n\n"
        for group in groups:
            lessons = schedules[group]
            response += f"Группа {group}:\n"
            if not lessons:
                response += "  Занятий нет\n"
            else:
                for lesson in lessons:
                    pair_num = lesson.get('pair_number', 0)
                    time_slot = times.get(pair_num, "??:??-??:??")
                    subject = lesson.get('subject', 'Предмет не указан')
                    location = lesson.get('location', '')
                    rooms = lesson.get('rooms', [])
                    
                    # Формируем строку с локацией/аудиторией
                    location_str = ""
                    if location:
                        location_str = f" [{location}]"
                    elif rooms:
                        if isinstance(rooms, list) and rooms:
                            location_str = f" [{rooms[0]}]"
                        elif isinstance(rooms, str):
                            location_str = f" [{rooms}]"
                    
                    response += f"  {time_slot}: {subject}{location_str}\n"
            response += "\n"
        
        return response.strip()
    
    async def compare_groups_period(
        self,
        session: AsyncSession,
        groups: List[str],
        start_date: datetime,
        end_date: datetime,
        min_duration: int = 0,
        is_session: bool = False
    ) -> str:
        """
        Сравнить расписания нескольких групп за период и найти общие свободные окна
        
        Args:
            session: Сессия БД
            groups: Список групп для сравнения
            start_date: Начальная дата периода
            end_date: Конечная дата периода
            min_duration: Минимальная длительность окна в минутах
            is_session: Флаг сессии
            
        Returns:
            Текст с результатами сравнения
        """
        if len(groups) < 2:
            return "❌ Для сравнения нужно указать минимум 2 группы"
        
        # Получаем расписания для всех групп
        schedules = {}
        for group in groups:
            schedule_data = await self.fetch_schedule(group, is_session)
            if not schedule_data:
                return f"❌ Не удалось получить расписание для группы {group}"
            schedules[group] = schedule_data
        
        # Формируем ответ
        response = f"📊 Сравнение расписаний на период\n"
        response += f"с {start_date.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')}\n"
        response += f"Группы: {', '.join(groups)}\n"
        if min_duration > 0:
            response += f"Минимальная длительность окна: {min_duration} мин\n"
        response += f"📍 Учитываются локации корпусов\n"
        response += "\n"
        
        # Проходим по каждому дню в периоде
        current_date = start_date
        days_processed = 0
        
        schedule_type = '0'
        times = self.times.get(schedule_type, {})
        
        while current_date <= end_date:
            # Получаем занятия для каждой группы на текущую дату
            day_schedules = {}
            for group in groups:
                lessons = self.get_schedule_for_date(schedules[group], current_date)
                day_schedules[group] = lessons
            
            # Определяем занятые временные интервалы для каждой группы
            all_busy_intervals = []
            for group in groups:
                lessons = day_schedules[group]
                busy_intervals = self._get_busy_intervals(lessons, schedule_type)
                all_busy_intervals.append(busy_intervals)
            
            # Находим общие свободные окна с учетом локации
            free_intervals_with_loc = self._find_free_intervals_with_location(all_busy_intervals, min_duration)
            
            # Добавляем информацию о дне, если есть свободные окна
            if free_intervals_with_loc:
                response += f"\n📅 {current_date.strftime('%d.%m.%Y')} ({self._get_weekday_name(current_date.weekday())})\n"
                for start, end, loc_info in free_intervals_with_loc:
                    start_time = self._minutes_to_time(start)
                    end_time = self._minutes_to_time(end)
                    duration = end - start
                    
                    # Определяем локацию
                    locations = list(loc_info.keys())
                    if locations:
                        if locations[0] == "Любая":
                            loc_str = "обе группы свободны, можно выбрать любую локацию"
                        else:
                            loc_str = f"обе группы в {locations[0]}"
                        response += f"🕐 {start_time} - {end_time} ({duration} мин) — {loc_str}\n"
                    else:
                        response += f"🕐 {start_time} - {end_time} ({duration} мин)\n"
            
            current_date += timedelta(days=1)
            days_processed += 1
        
        if days_processed == 0:
            response += "\n❌ Нет дней для анализа\n"
        
        return response.strip()


# Глобальный экземпляр сервиса расписания
schedule_service = ScheduleService()
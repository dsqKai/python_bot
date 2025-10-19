# Инструкция по работе с миграциями Alembic

## Созданная миграция

Создана начальная миграция `91430c8f04b4_initial_migration.py`, которая включает все таблицы из ваших моделей:

- `users` - пользователи бота
- `chats` - групповые чаты
- `blocked_users` - заблокированные пользователи
- `holidays` - праздники и каникулы
- `semester_boundaries` - границы семестров
- `personalized_names` - персонализированные имена
- `global_groups` - список групп
- `bans` - временные баны
- `patterns` - кастомные паттерны ответов
- `alerted_lessons` - уведомленные уроки
- `admin_users` - администраторы
- `admin_permissions` - права администраторов
- `feedback_messages` - сообщения обратной связи

## Команды для работы с миграциями

### Применение миграций
```bash
# Применить все миграции
python3 -m alembic upgrade head

# Применить конкретную миграцию
python3 -m alembic upgrade 91430c8f04b4
```

### Откат миграций
```bash
# Откатить все миграции
python3 -m alembic downgrade base

# Откатить до предыдущей миграции
python3 -m alembic downgrade -1
```

### Просмотр SQL без применения
```bash
# Показать SQL для применения миграций
python3 -m alembic upgrade head --sql

# Показать SQL для отката миграций
python3 -m alembic downgrade base --sql
```

### Создание новых миграций
```bash
# Создать пустую миграцию
python3 -m alembic revision -m "Описание изменений"

# Автоматически создать миграцию на основе изменений в моделях
python3 -m alembic revision --autogenerate -m "Описание изменений"
```

### Проверка статуса
```bash
# Показать текущую версию
python3 -m alembic current

# Показать историю миграций
python3 -m alembic history

# Показать доступные миграции
python3 -m alembic heads
```

## Настройка

Перед применением миграций убедитесь, что:

1. Настроен файл `.env` с параметрами подключения к базе данных
2. База данных PostgreSQL запущена и доступна
3. Пользователь имеет права на создание таблиц

## Структура файлов

- `alembic.ini` - конфигурация Alembic
- `alembic/env.py` - настройки окружения для миграций
- `alembic/versions/` - папка с файлами миграций
- `database/models.py` - модели SQLAlchemy
- `config.py` - настройки приложения
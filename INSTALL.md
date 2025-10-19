# Инструкция по установке и запуску

## Требования

- Python 3.11+
- PostgreSQL 13+
- pip
- virtualenv (опционально)

## Установка

### 1. Клонирование репозитория

```bash
cd python_bot
```

### 2. Создание виртуального окружения

```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows
```

### 3. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 4. Настройка PostgreSQL

Создайте базу данных:

```bash
sudo -u postgres psql
CREATE DATABASE schedulebot;
CREATE USER schedulebot_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE schedulebot TO schedulebot_user;
\q
```

### 5. Настройка окружения

Скопируйте файл `.env.example` в `.env`:

```bash
cp .env.example .env
```

Отредактируйте `.env` и укажите ваши настройки:

```env
BOT_TOKEN=your_telegram_bot_token
DB_HOST=localhost
DB_PORT=5432
DB_USER=schedulebot_user
DB_PASSWORD=your_password
DB_NAME=schedulebot
ADMIN_USER_IDS=your_telegram_id
```

### 6. Применение миграций

```bash
alembic upgrade head
```

Если миграций нет, создайте первую:

```bash
alembic revision --autogenerate -m "Initial migration"
alembic upgrade head
```

### 7. Запуск бота

```bash
python main.py
```

## Запуск через Docker

### 1. Подготовка

Убедитесь, что у вас установлены Docker и Docker Compose.

### 2. Настройка .env

Создайте `.env` файл как описано выше.

### 3. Запуск

```bash
docker-compose up -d
```

### 4. Просмотр логов

```bash
docker-compose logs -f bot
```

### 5. Остановка

```bash
docker-compose down
```

## Управление миграциями

### Создание новой миграции

```bash
alembic revision --autogenerate -m "описание изменений"
```

### Применение миграций

```bash
alembic upgrade head
```

### Откат последней миграции

```bash
alembic downgrade -1
```

### Просмотр истории миграций

```bash
alembic history
```

## Проверка работы

После запуска бота:

1. Найдите своего бота в Telegram
2. Отправьте команду `/start`
3. Следуйте инструкциям для настройки

## Устранение неполадок

### Ошибка подключения к БД

Проверьте:
- Запущен ли PostgreSQL: `sudo systemctl status postgresql`
- Правильность настроек в `.env`
- Доступность базы данных: `psql -h localhost -U schedulebot_user -d schedulebot`

### Ошибки при запуске бота

Проверьте:
- Правильность токена бота
- Наличие всех зависимостей: `pip list`
- Логи в папке `logs/`

### Ошибки миграций

Если миграции не применяются:
```bash
alembic stamp head
alembic revision --autogenerate -m "fix"
alembic upgrade head
```

## Разработка

### Структура проекта

```
python_bot/
├── main.py                 # Точка входа
├── config.py               # Конфигурация
├── bot/                    # Код бота
│   ├── handlers/           # Обработчики
│   ├── services/           # Бизнес-логика
│   ├── middleware/         # Middleware
│   └── utils/              # Утилиты
├── database/               # База данных
│   ├── models.py           # Модели
│   ├── repository.py       # Репозитории
│   └── session.py          # Сессии
└── alembic/                # Миграции
```

### Добавление новой команды

1. Создайте хэндлер в `bot/handlers/`
2. Зарегистрируйте роутер в `main.py`
3. При необходимости добавьте модели в `database/models.py`
4. Создайте миграцию: `alembic revision --autogenerate -m "add feature"`

### Логирование

Логи пишутся в:
- Консоль (уровень INFO)
- Файл `logs/bot.log` (уровень DEBUG)

Настройка логирования в `main.py`.

## Дополнительная информация

- [Документация aiogram](https://docs.aiogram.dev/)
- [Документация SQLAlchemy](https://docs.sqlalchemy.org/)
- [Документация Alembic](https://alembic.sqlalchemy.org/)

# Инвестиционный процессор

Веб-приложение для управления инвестиционными проектами с AI-анализом и финансовым моделированием.

---

## Стек технологий

| Слой | Технология |
|------|-----------|
| **Backend** | Python 3.11 · FastAPI · SQLAlchemy 2 |
| **База данных** | SQLite (dev) / PostgreSQL (prod) |
| **AI** | Anthropic Claude API (`claude-sonnet-4-6`) |
| **Финансовые расчёты** | `numpy-financial` (backend) · vanilla JS (frontend, real-time) |
| **Frontend** | HTML5 · Alpine.js 3 · Font Awesome |
| **Веб-сервер** | Nginx (reverse proxy + static) |
| **Контейнеризация** | Docker · Docker Compose |

---

## Быстрый старт (локально)

```bash
# 1. Клонируй репозиторий
git clone <repo-url>
cd invest-ai

# 2. Создай файл .env
cp .env.example .env
# Отредактируй .env: добавь ANTHROPIC_API_KEY

# 3. Запусти через Docker Compose
docker compose up -d

# Приложение доступно на http://localhost
# API документация: http://localhost/api/docs
```

Без Docker (для разработки):

```bash
cd backend
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Запуск backend
uvicorn app.main:app --reload --port 8000

# Frontend — открой frontend/main.html в браузере
# или запусти простой HTTP-сервер:
cd ../frontend && python -m http.server 3000
```

---

## Структура проекта

```
invest-ai/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI приложение, CORS, роуты
│   │   ├── config.py            # Настройки из .env (pydantic-settings)
│   │   ├── database.py          # SQLAlchemy engine, сессии, init_db
│   │   ├── models/
│   │   │   └── project.py       # ORM-модель Project
│   │   ├── schemas/
│   │   │   ├── project.py       # Pydantic DTO (Create/Update/Read)
│   │   │   └── finance.py       # FinancialModelInput · FinancialMetrics
│   │   ├── api/v1/
│   │   │   ├── projects.py      # CRUD проектов + смена статуса
│   │   │   ├── finance.py       # POST /finance/calculate
│   │   │   └── ai.py            # AI: описание, риски, анализ
│   │   └── services/
│   │       ├── finance_service.py  # NPV, IRR, DCF, DPP, PI, LTV/CAC
│   │       └── ai_service.py       # Anthropic Claude API обёртка
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/
│   ├── main.html              # Дашборд (KPI + последние проекты)
│   ├── new.html               # Визард создания проекта (5 шагов + Alpine.js)
│   ├── project-list.html      # Портфель проектов с фильтрами
│   ├── project.html           # Детальная карточка проекта
│   ├── export.html            # Экспорт отчётов
│   └── js/
│       └── finance.js         # Финансовый движок (real-time расчёты)
│
├── nginx/
│   └── nginx.conf             # Reverse proxy + раздача статики
│
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## API Endpoints

### Проекты

| Метод | URL | Описание |
|-------|-----|---------|
| `GET` | `/api/v1/projects/` | Список проектов (фильтр `?status=draft`) |
| `POST` | `/api/v1/projects/` | Создать проект |
| `GET` | `/api/v1/projects/{id}` | Детали проекта |
| `PUT` | `/api/v1/projects/{id}` | Обновить проект |
| `PATCH` | `/api/v1/projects/{id}/status` | Сменить статус |
| `DELETE` | `/api/v1/projects/{id}` | Удалить проект |

### Финансовые расчёты

| Метод | URL | Описание |
|-------|-----|---------|
| `POST` | `/api/v1/finance/calculate` | Рассчитать NPV/IRR/LTV/CAC и др. |

### AI (требует `ANTHROPIC_API_KEY`)

| Метод | URL | Описание |
|-------|-----|---------|
| `POST` | `/api/v1/ai/generate-description` | Сгенерировать описание проекта |
| `POST` | `/api/v1/ai/generate-risks` | Сгенерировать риски и допущения |
| `POST` | `/api/v1/ai/analyze` | Анализ аномалий и AI-комментарий |

Swagger UI: `http://localhost/api/docs`

---

## Финансовая модель (Шаг 3 визарда)

### Рассчитываемые метрики

| Метрика | Формула |
|---------|---------|
| **Ставка дисконтирования** | `Key Rate + Risk Premium` |
| **DCF** | `CF_q / (1 + r_q)^t` |
| **NPV** | `Σ DCF_q + Начальные инвестиции` |
| **DPP** | Квартал, когда кумулятивный DCF ≥ 0 |
| **PI** | `1 + NPV / |Инвестиции|` |
| **IRR** | Метод Ньютона-Рафсона по квартальным CF |
| **CAC** | `Маркетинговые затраты / Кол-во новых пользователей` |
| **ARPU** | `Выручка / Платящие пользователи` (за квартал) |
| **Lifetime** | `1 / |Avg Churn|` в кварталах → лет |
| **LTV** | `ARPU_месяц / Churn_месяц` |
| **LTV/CAC** | `LTV / CAC` |

### Модели выручки

- **Subscription** — цена за пользователя в месяц × платящие × 3 (квартал), с опциональной годовой индексацией
- **Transactional** — кол-во транзакций × средний чек
- **Hybrid** — сумма подписочной и транзакционной составляющих

### Расчёт в реальном времени

Все метрики пересчитываются мгновенно при каждом изменении поля через `Alpine.js $watch` + `finance.js`. Обращений к серверу не требуется — серверный расчёт используется только для финальной валидации при сохранении.

---

## Развёртывание на VPS

```bash
# На сервере:
git clone <repo-url> /opt/invest-ai
cd /opt/invest-ai
cp .env.example .env
nano .env   # заполни ANTHROPIC_API_KEY и SECRET_KEY

docker compose up -d
```

### Обновление

```bash
cd /opt/invest-ai
git pull origin main
docker compose build backend
docker compose up -d --no-deps backend
```

### HTTPS (рекомендуется)

Используй Certbot с Nginx или Traefik как reverse proxy с автоматическим получением сертификатов Let's Encrypt.

---

## Статусы проекта

```
draft  →  pending_approval  →  approved
                           ↘  rejected
```

---

## Переменные окружения

| Переменная | Обязательна | Описание |
|-----------|------------|---------|
| `ANTHROPIC_API_KEY` | Для AI функций | Ключ Anthropic Console |
| `DATABASE_URL` | Нет (SQLite по умолчанию) | URL базы данных |
| `SECRET_KEY` | В production | Ключ для подписи JWT |
| `CORS_ORIGINS` | Нет | Список разрешённых origins |

---

## Roadmap

- [ ] Аутентификация (JWT + роли)
- [ ] Страница портфеля с live-фильтрами (Alpine.js)
- [ ] Экспорт PDF/Excel (WeasyPrint / openpyxl)
- [ ] История изменений проекта
- [ ] Дашборд с агрегированными KPI из БД
- [ ] PostgreSQL migration (Alembic)
- [ ] CI/CD через GitHub Actions

# Обновление: Доработки апрель 2026 (Вариант B)

Дата: 04.05.2026  
Ветка: `claude/investment-processor-extended-K60uY`  
Коммит: `5f4b286`

---

## Патчи после опытной эксплуатации (04.05.2026)

Коммиты: `97b59f5` → `253748e`

### Исправления интерфейса

**Раздел «План / Факт» — полный редизайн (`40c81b8`)**  
Таблица переработана в формат электронной таблицы: строки = метрики, столбцы = месяцы. Каждая метрика имеет три ряда — план (синий фон), факт (зелёный) и отклонение % (авторасчёт, зелёный/красный). Кнопка «+12 мес.» расширяет горизонт вправо без ограничений. Добавление метрик — строка ввода в конце таблицы. Первый столбец (название метрики) зафиксирован при горизонтальном скролле. Данные автоматически подгружаются из API и восстанавливают диапазон периодов по сохранённым значениям.

**График план/факт — исправление дублирования меток оси Y (`a71937f`)**  
Колбэк форматирования исправлен с `toFixed(0)` на `toFixed(1)` с удалением `.0` — 2000 → «2K», 2500 → «2.5K», 2200 → «2.2K». Исчезли дублирующиеся метки «2K» при значениях в диапазоне 2000–2999.

**Статус «В зоне риска» — однострочный бейдж (`253748e`)**  
В `.status-pill` добавлен `white-space: nowrap` в `main.html` и `project-list.html` — многословные статусы больше не переносятся на вторую строку.

**Попап колокольчика — фиксированное позиционирование (`253748e`)**  
Переключено с `position:absolute` (обрезался `overflow:hidden` родительского `.app-window`) на `position:fixed` с координатами, вычисляемыми из `getBoundingClientRect()` в момент открытия. Применено на всех 4 страницах. Ширина попапа увеличена до 360px, внутренние отступы — 24px по горизонтали.

**Выравнивание текста на странице операционного проекта (`a71937f`)**  
Значения в полях «Базовое значение», «Целевое значение», «Экономика / Payback», «Stop-loss», «Stage-gates» теперь выровнены по левому краю — CSS `.info-row .val` изменён с `text-align:right` на `text-align:left`.

**Ключевая метрика `__custom__` на странице операционного проекта (`a71937f`)**  
При отображении `op_metrics === '__custom__'` (артефакт старых данных до введения конвертации) теперь показывается значение `op_metrics_custom` или прочерк вместо технического сентинела.

**Кнопки действий на странице операционного проекта (`97b59f5`)**  
Добавлены кнопки «Утвердить», «Отклонить», «В черновик» для CFO и менеджеров — ранее страница была полностью read-only.

---

### Исправления бэкенда и инфраструктуры

**Постоянство настроек (бюджет и ключи) (`77a25af`)**  
`settings_store.py`: путь по умолчанию для `settings.json` изменён с относительного (`settings.json` в рабочей директории контейнера) на `/data/settings.json` — тот же Docker volume `db_data`, что и SQLite база. Настройки теперь переживают `docker compose up --build` и обновления кода.  
> ⚠️ После первого деплоя с этим изменением нужно однократно повторно ввести инвестиционный бюджет и API-ключи в настройках.

**Исправление healthcheck (`d8e5d2a`)**  
Docker healthcheck заменён с `curl -f http://...` (curl отсутствует в python-образе) на `python -c "import urllib.request; urllib.request.urlopen(...)"`. Статус контейнера больше не показывает `(unhealthy)`.

**Лимит загрузки файлов nginx (`229fed6`)**  
В `nginx.conf` для `location /api/` добавлен `client_max_body_size 26m` — устранена ошибка 413 при загрузке вложений.

**Исправление сохранения данных план/факт (`c6108a6`)**  
`saveFact()` переписан: отправляет все записи из `factEntries` (ранее итерировал `_edits`, который не заполнялся при добавлении строк через форму). Данные теперь не теряются после перезагрузки страницы.

---

## 1. Поддержка Anthropic Claude с выбором провайдера AI

Добавлена возможность работы с двумя AI-провайдерами одновременно — OpenAI и Anthropic. Провайдер выбирается в настройках, исторические ключи сохраняются.

**Что изменилось:**
- `backend/requirements.txt` — добавлен пакет `anthropic>=0.30.0`
- `backend/app/config.py` — добавлено поле `ANTHROPIC_API_KEY`
- `backend/app/settings_store.py` — новые функции `get/set_anthropic_key()`, `get/set_ai_provider()`
- `backend/app/services/ai_service.py` — реализован диспетчер `_chat()`: при провайдере `"anthropic"` использует `claude-sonnet-4-6`, при `"openai"` — GPT; все 5 AI-функций не изменились
- `backend/app/api/v1/settings.py` — поля `anthropic_api_key` и `ai_provider` в схемах чтения/записи; `test_connection()` тестирует активный провайдер
- `backend/app/api/v1/ai.py` — `_check_api_key()` проверяет ключ активного провайдера
- `backend/app/api/v1/stats.py` — поле `ai_provider` в ответе; `ai_active` срабатывает при наличии любого из ключей
- `frontend/settings.html` — переключатель провайдера (OpenAI / Anthropic Claude), условный ввод ключа, кнопка проверки подключения
- `frontend/main.html` — индикатор AI показывает «Claude Sonnet 4.6 активен» или «GPT-5.4 активен» в зависимости от настройки

---

## 2. KPI «Согласовано инвестиций»

На главном экране карточка «Всего проектов» заменена на «Согласовано инвестиций».

**Что изменилось:**
- `backend/app/api/v1/stats.py` — добавлено поле `total_approved_investments`: сумма `initialInvestment` всех проектов со статусом `approved`
- `frontend/main.html` — новая карточка KPI с форматированием суммы (млн/млрд ₽) и подписью «Проектов: N»

---

## 3. Модель уведомлений

Создана инфраструктура in-app уведомлений, на которую опираются уведомления о смене статуса и траншах.

**Новые файлы:**
- `backend/app/models/notification.py` — модель `Notification` (user_id, project_id, title, message, link, is_read, created_at)
- `backend/app/services/notification_service.py` — функции `create_notification()`, `notify_approvers()` (всем CFO/менеджерам), `notify_owner()` (владельцу проекта)

---

## 4. Колокольчик уведомлений в шапке

Во все основные страницы добавлен виджет уведомлений с бейджем непрочитанных и раскрывающимся списком.

**Новые файлы:**
- `backend/app/api/v1/notifications.py` — эндпоинты:
  - `GET /notifications` — список (50 новейших)
  - `GET /notifications/unread-count`
  - `PATCH /notifications/read-all`
  - `PATCH /notifications/{id}/read`
  - `DELETE /notifications/{id}`

**Что изменилось:**
- `backend/app/api/v1/projects.py` — при переходе в `pending_approval` уведомляются все CFO/менеджеры; при `approved`/`rejected`/`draft` — владелец проекта
- `frontend/main.html` — виджет `bellApp()` в шапке, полинг раз в 30 с
- `frontend/project-list.html` — тот же виджет
- `frontend/project.html` — тот же виджет (был добавлен ранее)
- `frontend/op-project.html` — тот же виджет

---

## 5. Комментарии к карточке проекта

Каждый проект получил раздел обсуждения: текстовые комментарии с автором и датой.

**Новые файлы:**
- `backend/app/models/comment.py` — модель `Comment` (project_id, user_id, text, created_at)
- `backend/app/api/v1/comments.py` — `GET` и `POST /projects/{id}/comments`

**Что изменилось:**
- `frontend/project.html` — раздел «Комментарии»: textarea (отправка Ctrl+Enter), список с именем автора и датой, компонент `commentsApp()`

---

## 6. Вложения (инвестиционный контракт)

Поддержка загрузки и скачивания файлов к проекту с авторизацией.

**Новые файлы:**
- `backend/app/models/attachment.py` — модель `Attachment` (project_id, UUID-имя на диске, оригинальное имя, размер, дата)
- `backend/app/api/v1/attachments.py` — эндпоинты:
  - `POST /projects/{id}/attachments` — загрузка (PDF/DOCX/MD, ≤ 25 МБ), сохранение в `/data/attachments/{project_id}/`
  - `GET /projects/{id}/attachments` — список файлов
  - `GET /attachments/{id}/download` — скачивание через `FileResponse` (требует JWT, не StaticFiles)
  - `DELETE /attachments/{id}` — только CFO/менеджер

**Что изменилось:**
- `backend/app/main.py` — создание директории `/data/attachments`, подключение роутера
- `frontend/project.html` — раздел «Контракт»: кнопка загрузки, список файлов с размером и датой, скачивание через fetch-blob + `URL.createObjectURL` (браузер не передаёт Bearer при прямой навигации по ссылке)

---

## 7. Траншевая логика (расширенный вариант 4.2)

Полноценное управление траншами с чек-листом триггерных метрик, историей и блокировкой одобрения.

**Новые файлы:**
- `backend/app/models/tranche.py` — три модели:
  - `Tranche` (project_id, amount, planned_date, status: requested/approved/paid, description, order_index)
  - `TriggerChecklistItem` (tranche_id, metric_name, target_value, actual_value, is_met, notes)
  - `TrancheHistory` (tranche_id, user_id, event_type, comment, created_at)
- `backend/app/api/v1/tranches.py` — эндпоинты:
  - `GET/POST /projects/{id}/tranches`
  - `PUT/DELETE /tranches/{id}`
  - `PATCH /tranches/{id}/status` — проверяет чек-лист; если хотя бы один пункт `is_met=False` → 400
  - `GET/PUT /tranches/{id}/triggers` — bulk replace чек-листа
  - `GET /tranches/{id}/history`
  - При переводе в `paid` — уведомление CFO/менеджерам о следующем запрошенном транше

**Что изменилось:**
- `frontend/project.html` — раздел «Транши»: список с суммой/датой/статус-бейджем, вложенный чек-лист триггеров, история, кнопка «Одобрить» заблокирована пока не выполнены все триггеры, итоговая сумма agreed + paid

---

## 8. План vs Факт (расширенный вариант 5.2)

Помесячный учёт плановых и фактических показателей с импортом, прогнозом и AI-комментарием.

**Новые файлы:**
- `backend/app/models/fact_entry.py` — модель `FactEntry` (project_id, year, month, metric_name, plan_value, fact_value, created_at, updated_at); уникальный индекс по (project_id, year, month, metric_name)
- `backend/app/api/v1/fact.py` — эндпоинты:
  - `GET /projects/{id}/fact` — все записи с отклонением (абс. и %)
  - `PUT /projects/{id}/fact` — bulk upsert (совместимо с SQLite и PostgreSQL — без `ON CONFLICT`)
  - `POST /projects/{id}/fact/import` — CSV (year/месяц/metric_name/value) или Excel (openpyxl)
  - `GET /projects/{id}/fact/forecast` — линейный прогноз на 6 месяцев по каждой метрике (не сохраняется в БД)
  - `POST /projects/{id}/fact/ai-commentary` — AI-анализ отклонений через `ai_service.analyze_project`

**Что изменилось:**
- `frontend/project.html` — раздел «Факт»: редактируемая сетка метрик × месяцы, цветовые отклонения (зелёный/красный), кнопка импорта CSV/Excel, график Chart.js 4 (план vs факт), AI-комментарий по аномалиям

---

## 9. История статусов проекта

Каждое изменение статуса проекта теперь фиксируется с датой и именем пользователя.

**Что изменилось:**
- `backend/app/models/project.py` — поле `status_history: JSON`
- `backend/app/database.py` — миграция `ALTER TABLE projects ADD COLUMN status_history JSON`
- `backend/app/api/v1/projects.py` — при смене статуса добавляется запись `{status, changed_at, changed_by, changed_by_id}` (присваивание нового списка, не `.append()` — SQLAlchemy не видит мутации JSON in-place)
- `frontend/op-project.html` — отображается полная история статусов

---

## 10. Карточка операционного проекта (read-only)

Отдельная страница просмотра для операционных проектов.

**Новые файлы:**
- `frontend/op-project.html` — компонент `opProjectApp()`:
  - Загружает проект по `?id=`, редиректит на `/project?id=` если тип не `operational`
  - Read-only разделы: идентификация инициативы, описание запроса, драйверы ценности/метрики, экономика и управление
  - Value Score: 5 критериев с индикаторами-точками и итоговым баллом
  - AI Risk Score из `risks_data`
  - История статусов
  - Виджет уведомлений в шапке

**Что изменилось:**
- `frontend/project-list.html` — клик по строке проекта роутит на `/op-project?id=` для операционных и `/project?id=` для инвестиционных
- `frontend/main.html` — аналогичная маршрутизация в функции `openProject(p)`

---

## Технические изменения

| Файл | Изменение |
|---|---|
| `backend/requirements.txt` | `anthropic>=0.30.0` |
| `backend/app/main.py` | 5 новых роутеров, директория вложений |
| `backend/app/models/__init__.py` | Регистрация всех 7 моделей в правильном порядке |
| `backend/app/database.py` | Импорт всех моделей через `from . import models`; ALTER для `status_history` |
| `.env.example` | `ANTHROPIC_API_KEY=sk-ant-api03-...` |

---

## Затронутые файлы

**Изменено (17):** `.env.example`, `backend/requirements.txt`, `backend/app/config.py`, `backend/app/database.py`, `backend/app/main.py`, `backend/app/models/__init__.py`, `backend/app/models/project.py`, `backend/app/settings_store.py`, `backend/app/services/ai_service.py`, `backend/app/api/v1/ai.py`, `backend/app/api/v1/projects.py`, `backend/app/api/v1/settings.py`, `backend/app/api/v1/stats.py`, `frontend/main.html`, `frontend/project-list.html`, `frontend/project.html`, `frontend/settings.html`

**Создано (12):** `backend/app/models/comment.py`, `attachment.py`, `tranche.py`, `fact_entry.py`, `notification.py`, `backend/app/services/notification_service.py`, `backend/app/api/v1/comments.py`, `attachments.py`, `tranches.py`, `fact.py`, `notifications.py`, `frontend/op-project.html`

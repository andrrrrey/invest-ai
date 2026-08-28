# Подключение помощника Hermes — пошаговая инструкция

Инструкция по подключению Hermes к Mattermost, по доступу сторонних ИИ-программ
через MCP и по просмотру логов/аудита.

Большинство параметров теперь можно задать в UI: **Настройки** (роль CFO) →
карточки «Помощник Hermes — Mattermost» и «Режимы Hermes». Значения, заданные
переменными окружения, **имеют приоритет** над UI (в UI такие поля помечаются и
блокируются).

---

## 0. Предусловия

**Сетевая доступность** (обязательно для Q&A и кнопок):
- Mattermost-сервер (напр. `https://mmdev.pravo.tech`) должен **достучаться до
  бэкенда** по HTTPS (slash-команда и нажатия кнопок). Бэкенд должен быть на
  публичном домене; `localhost` не подойдёт — нужен публичный URL или туннель
  (ngrok/cloudflared).
- Бэкенд должен иметь исходящий доступ к Mattermost (карточки, DM, оповещения).

**AI-провайдер** (Настройки, роль CFO): провайдер **RouterAI**, ключ RouterAI,
включить «AI-функции» (`ai_enabled`), «Проверить соединение». Без этого агент
Hermes вернёт ошибку.

---

## Навигация по Mattermost UI (куда кликать)

Ниже пути для сервера Mattermost. `<team>` — идентификатор команды из адресной
строки (например, `pravotech` в `mmdev.pravo.tech/pravotech/...`), `<mm>` —
базовый адрес сервера Mattermost.

**Где меню:**
- Меню интеграций — значок-сетка (▦, product menu) вверху слева рядом с логотипом
  → **Integrations**. Прямая ссылка: `<mm>/<team>/integrations`.
- **System Console** (админка, нужны права системного администратора): та же
  сетка ▦ → **System Console**, или `<mm>/admin_console`.

**Шаг 0. Включить интеграции** (System Console, нужен админ):
`System Console → Integrations → Integration Management` — включить (ON):
- **Enable Bot Account Creation**
- **Enable Custom Slash Commands**
- **Enable Incoming Webhooks**
- **Enable integrations to override usernames** и **… override profile picture
  icons** (чтобы сообщения бота выглядели корректно)

Если бэкенд **не** на публичном доверенном домене (внутренний хост/порт):
`System Console → Environment → Developer → Allow untrusted internal connections`
— добавьте хост бэкенда. Иначе Mattermost не сможет вызвать slash-команду и
обработать нажатия кнопок.

**Прямые пути для создания интеграций:**
- Бот: `<mm>/<team>/integrations/bots/add`
- Slash-команда: `<mm>/<team>/integrations/commands/add`
- Incoming webhook: `<mm>/<team>/integrations/incoming_webhooks/add`

**Куда потом вставлять** (в нашем UI: Настройки → «Помощник Hermes — Mattermost»):
токен бота → **Токен бота**; токен slash-команды → **Токен slash-команды /
кнопок**; URL incoming webhook → **Webhook служебного канала**; адрес сервера
Mattermost → **URL сервера Mattermost**; публичный адрес бэкенда → **Внешний URL
бэкенда**. Кнопки согласования отдельной настройки в Mattermost не требуют —
их шлёт бот автоматически.

---

## 1. Hermes в Mattermost

Настраиваются 4 интеграции. Токены/URL вводятся в **Настройки → «Помощник Hermes
— Mattermost»** (или через переменные окружения — см. таблицу в конце).

### 1.1. Бот-аккаунт (карточки и личные сообщения)
1. System Console → Integrations → Bot Accounts → включить.
2. Integrations → Bot Accounts → Add Bot Account (имя `hermes`), скопировать
   **Access Token**.
3. Добавить бота в ту же команду (team), что и согласующие.
4. В UI: поля **URL сервера Mattermost** (`https://mmdev.pravo.tech`) и
   **Токен бота**.

### 1.2. Slash-команда (вопросы и аналитика)
1. Integrations → Slash Commands → Add.
2. Trigger Word: `hermes`; Request URL:
   `https://<ваш-бэкенд>/api/v1/mattermost/hermes`; Method: **POST**.
3. Скопировать **Token** → в UI поле **Токен slash-команды / кнопок**.
4. Проверка: `/hermes сводка по портфелю` → приватный ответ.

### 1.2a. Ответы на обычные сообщения / DM (WebSocket)
Кроме slash-команды, бот может отвечать на **обычные сообщения** — если написать
ему в личку (DM) или упомянуть `@hermes <вопрос>` в канале. Это работает через
постоянное WebSocket-подключение бота к Mattermost и **дополнительной настройки
в Mattermost не требует** — нужен только настроенный бот (п.1.1: **URL сервера
Mattermost** + **Токен бота**).

- Включается флагом **«Ответы на обычные сообщения»** (Настройки → «Режимы
  Hermes», по умолчанию включён) или переменной `HERMES_CHAT_ENABLED`.
- Бэкенду нужен **исходящий доступ** к Mattermost по WebSocket
  (`wss://<mm>/api/v4/websocket`).
- При нескольких воркерах uvicorn слушатель автоматически запускается **только
  в одном** процессе (межпроцессная блокировка) — дублей ответов не будет.
- Проверка: напишите боту `hermes` в личные сообщения: «сводка по портфелю».

### 1.3. Карточки согласования с кнопками
Дополнительной настройки в Mattermost не нужно — карточку отправляет бот
автоматически при переходе проекта в «на согласовании». В UI заполнить
**Внешний URL этого бэкенда** (напр. `https://invest.example.com`) — на него
Mattermost шлёт нажатия (`/api/v1/mattermost/actions`). Проверка подлинности —
тем же токеном slash-команды. Нажавший сопоставляется с аккаунтом системы по
email; решение применяется, только если у него роль `cfo`/`manager`.

### 1.4. Оповещения об ошибках
1. Создать канал (напр. `hermes-alerts`).
2. Integrations → Incoming Webhooks → Add → скопировать URL
   (`https://mmdev.pravo.tech/hooks/xxxx`).
3. В UI: поле **Webhook служебного канала**. Кнопка **«Тестовое оповещение»**
   проверит доставку.

### 1.5. Режимы (Настройки → «Режимы Hermes»)
- **Обезличивание данных** — по умолчанию включено (рекомендуется).
- **Округлять суммы** — опционально.
- **Напоминания по дедлайнам** — фоновая рассылка (по умолчанию выкл.).
- **Действия на запись** — разрешить обновление факта/статуса майлстоунов
  помощником (по умолчанию выкл.). Согласование помощнику недоступно всегда.

> Если бэкенд в Docker и вы меняли переменные окружения — выполните
> `docker compose up -d backend`. Изменения в UI применяются сразу.

---

## 2. Подключение сторонних программ по MCP

MCP-сервер работает по транспорту **stdio** — MCP-клиент сам запускает процесс.
Сервер стартует в окружении бэкенда (доступ к БД/настройкам) и требует пакет
`mcp` (уже в `requirements.txt`).

Проверка вручную:
```
docker compose exec backend python -m app.mcp.server
```

Пример конфигурации MCP-клиента (Claude Desktop, `claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "hermes-invest": {
      "command": "docker",
      "args": ["compose", "-f", "/путь/к/docker-compose.yml",
               "exec", "-T", "backend", "python", "-m", "app.mcp.server"]
    }
  }
}
```
Локальный запуск (venv):
```json
{
  "mcpServers": {
    "hermes-invest": {
      "command": "/путь/venv/bin/python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/путь/backend",
      "env": { "DATABASE_URL": "sqlite:////data/invest_ai.db",
               "SETTINGS_PATH": "/data/settings.json" }
    }
  }
}
```
Клиент увидит 6 read-only инструментов (`list_projects`, `get_project`,
`get_portfolio_stats`, `list_pending_approvals`, `get_project_facts`,
`get_milestones`) и, если включён режим записи, ещё 2 (`update_fact`,
`update_milestone_status`). Каждый вызов пишется в аудит (`actor_type=ai_gateway`).

---

## 3. Логи и аудит

**А. Экран аудита в UI (проще всего):** Настройки → «Аудит» (или пункт «Аудит» в
меню, виден CFO). Таблица журнала `audit_log` с фильтрами по действию, результату
и актору + пагинация. Там же:
- **Скачать CSV** — выгрузка событий аудита по текущим фильтрам.
- блок **«Системные логи»** — предпросмотр/скачивание технических JSON-логов
  (фильтр по уровню и подстроке) и **отправка разработчику на email**
  (нужен настроенный SMTP). Логи пишутся в файл `LOG_FILE`
  (по умолчанию `/data/logs/app.log`, на постоянном volume). Можно задать
  `DEVELOPER_EMAIL` в `.env` для префилла поля адреса.

**Б. Подробные (JSON) логи — stdout контейнера:**
```
docker compose logs -f backend
```
Каждая строка — JSON (`ts`, `level`, `logger`, `msg`, `event`/`request`/`audit`).
Логгеры: `hermes.request`, `hermes.ai`, `hermes.audit`, `hermes.agent`,
`hermes.mattermost`, `hermes.approval`, `hermes.scheduler`, `hermes.alert`.
Примеры:
```
docker compose logs backend | grep '"logger": "hermes.ai"'
docker compose logs backend | grep '"result": "error"'
```
Детализация: `LOG_LEVEL=DEBUG` в `.env`.

**В. Журнал аудита через API (CFO):**
```
curl -s "https://<бэкенд>/api/v1/audit/?action=hermes.answer&result=error" \
  -H "Authorization: Bearer <JWT CFO>"
```
Полезные `action`: `ai.chat`, `mcp.tool_call`, `hermes.answer`,
`hermes.approval_card_sent`, `status.change`, `write.fact`, `write.milestone`,
`hermes.deadline_reminder`.

**Г. Ошибки** дополнительно приходят в служебный канал Mattermost (п. 1.4).

Конфиденциальные данные в логи/аудит не попадают — только метки и метаданные.

---

## Переменные окружения (альтернатива UI; имеют приоритет)

| Переменная | Назначение |
|-----------|-----------|
| `MATTERMOST_BASE_URL` | URL сервера Mattermost (bot API) |
| `MATTERMOST_BOT_TOKEN` | Токен бот-аккаунта |
| `MATTERMOST_COMMAND_TOKEN` | Токен slash-команды и кнопок |
| `MATTERMOST_INTEGRATION_URL` | Внешний URL бэкенда для callback-ов кнопок |
| `MATTERMOST_ALERT_WEBHOOK` | Incoming webhook служебного канала |
| `ROUTERAI_API_KEY` | Ключ RouterAI (можно задать в UI) |
| `SETTINGS_ENCRYPTION_KEY` | Шифрование секретов в `/data/settings.json` (Fernet) |
| `LOG_LEVEL` | Уровень JSON-логирования |

Флаги режимов (`anonymize_enabled`, `anonymize_round_amounts`,
`reminders_enabled`, `hermes_write_enabled`, `ai_enabled`) задаются в UI и
хранятся в `/data/settings.json`.

> **Важно (безопасность):** без `SETTINGS_ENCRYPTION_KEY` секреты, введённые в
> UI (ключи ИИ, токены/webhook Mattermost), хранятся в `/data/settings.json` в
> **открытом виде** (в логах будет предупреждение `SETTINGS_ENCRYPTION_KEY не
> задан`). Перед сохранением токенов задайте в `.env` длинную случайную строку
> и перезапустите бэкенд:
> ```
> SETTINGS_ENCRYPTION_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
> ```
> Уже сохранённые значения перешифруются при следующем сохранении.

## Частые ошибки при первом деплое

- **502 Bad Gateway, в логах `CORS_ORIGINS must list explicit origins`.** При
  `APP_ENV=production` нельзя `CORS_ORIGINS=["*"]`. Укажите явный домен фронтенда,
  например `CORS_ORIGINS=["https://invest.example.com"]`, и `docker compose up -d backend`.
- **`table ... already exists` на старте при нескольких воркерах.** Разовая гонка
  воркеров при первом создании новой таблицы; приложение самовосстанавливается,
  а `init_db` устойчив к этому (пропускает «already exists»).

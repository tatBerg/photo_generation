# AI-фотобудка

Telegram-бот AI-фотобудка для генерации и редактирования пользовательских фотографий через OpenAI и fal.ai.

## Сейчас реализовано

- три сценария: «Жить богато», «Я со знаменитостью», «Добавить меня на фото»;
- асинхронная очередь задач через Redis;
- отдельный worker для AI-генераций;
- маршрутизация: fal.ai для identity/composite-сценариев, OpenAI Images для «Жить богато» и автоматический fallback;
- `MOCK_MODE=true` для запуска без API-ключей;
- PostgreSQL в Docker и SQLite по умолчанию;
- дневной бесплатный лимит;
- возврат бесплатной генерации или Stars-кредита, если AI-провайдер завершился ошибкой;
- Telegram Stars invoice-flow с защитой от повторного зачисления;
- конфигурируемые модели через `.env`;
- health-check `/health`.

Команда `/status` показывает, включён ли DEMO-режим. В `MOCK_MODE=true` бот не обращается к AI-провайдерам и возвращает тестовое изображение с отметкой `DEMO`; для настоящей генерации нужны ключи и `MOCK_MODE=false`. После результата доступны кнопки нового заказа и возврата в главное меню.

Для тестирования владелец может получить свой ID командой `/myid`, записать его в `ADMIN_TELEGRAM_ID`, перезапустить бота и сбрасывать бесплатный лимит командой `/reset_free`.

## Запуск локально

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
uvicorn photo_generation.api:app --reload
```

Для запуска настоящего бота заполни `TELEGRAM_BOT_TOKEN`, `FAL_KEY` и/или `OPENAI_API_KEY`, затем поставь `MOCK_MODE=false`. Redis должен быть доступен по `REDIS_URL`, а worker и polling-бот запускаются отдельно:

При наличии обоих ключей режим «Жить богато» обрабатывается через OpenAI Images: у текущего API `fal-ai/nano-banana-2` в схеме запроса нет поля `image_urls`, поэтому он не подходит для этой операции без отдельного адаптера. fal.ai используется для «Я со знаменитостью» и «Добавить меня на фото», а при недоступности fal.ai эти сценарии автоматически переключаются на OpenAI.

```bash
python -m photo_generation.worker
python -m photo_generation.bot
```

Через Docker:

```bash
cp .env.example .env
docker compose up --build
```

## Деплой на Ubuntu-сервер (Docker Compose)

Этот вариант использует Telegram polling: домен и входящий порт для самого бота не нужны. API доступно только локально на сервере (`127.0.0.1:8000`), а Redis и PostgreSQL не публикуются наружу.

1. Подключись к серверу по SSH и установи Docker Engine с Compose plugin по [официальной инструкции Docker](https://docs.docker.com/engine/install/ubuntu/).
2. Клонируй репозиторий и создай production-конфиг:

```bash
git clone <URL_РЕПОЗИТОРИЯ> photo-generation
cd photo-generation
cp .env.example .env
chmod 600 .env
```

3. Заполни `.env`: обязательно укажи `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY` и/или `FAL_KEY`, установи `MOCK_MODE=false` и замени `POSTGRES_PASSWORD` на длинный случайный пароль. Не меняй `DATABASE_URL`, `REDIS_URL` и `MEDIA_DIR`: Compose задаёт безопасные серверные значения сам.
4. Запусти сервисы и проверь состояние:

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f bot worker
curl http://127.0.0.1:8000/health
```

Ожидаемый ответ health-check: `{"status":"ok","mode":"live"}`. После первого запуска отправь боту `/status` в Telegram и сделай тестовую генерацию.

Для обновления на сервере:

```bash
git pull
docker compose up -d --build
docker image prune -f
```

Сервисы настроены с `restart: unless-stopped`, поэтому стартуют снова после перезагрузки сервера. Логи: `docker compose logs -f bot worker`. Остановить: `docker compose down`. Не используй `docker compose down -v`, если нужно сохранить БД и изображения.

## Нагрузка до 1 000 пользователей

Бот ограничивает одного пользователя одной активной генерацией, а Redis ограничивает общую очередь (`MAX_QUEUE_SIZE=500`). Поэтому резкий наплыв не исчерпает память, не создаст неограниченные расходы у AI-провайдеров и не заблокирует остальных пользователей: при заполненной очереди бот попросит повторить попытку позже.

Для production-сервера с 4 vCPU и 8+ ГБ RAM начни с восьми параллельных генераций: `WORKER_CONCURRENCY=2` в `.env` и четырёх worker-контейнеров. Polling-бот всегда должен оставаться в одном экземпляре.

```bash
docker compose up -d --build --scale worker=4
docker compose ps
docker compose logs -f worker
```

Значение `WORKER_CONCURRENCY × число worker-контейнеров` подбирай по лимитам OpenAI/fal.ai и фактическому времени генерации. Не повышай его, пока не проверишь provider rate limits и не сделаешь пробный запуск на 20–50 одновременных задачах. Очередь сохраняется в Redis с AOF, а неподтверждённые задачи возвращаются в обработку после перезапуска worker.

## Render + Cloudflare R2

Для Render локальная папка с изображениями не подходит: bot и worker работают в разных контейнерах. При заданных переменных `S3_*` бот сохраняет загруженные изображения в S3-совместимое хранилище, а worker скачивает их только на время генерации. Cloudflare R2 поддерживает этот S3 API.

1. В Cloudflare открой **R2 → Create bucket**, например `photo-generation-media`.
2. В **R2 → Manage API Tokens** создай токен **Object Read & Write** только для этого bucket. Сохрани endpoint, Access Key ID и Secret Access Key.
3. В Render выбери **New → Blueprint**, укажи репозиторий. Файл `render.yaml` создаст API, один polling-бот, четыре worker-экземпляра, Postgres и Key Value.
4. При первом создании Blueprint введи значения секретов: `TELEGRAM_BOT_TOKEN`, ключи AI-провайдеров и все `S3_*`. Значение `S3_REGION` оставь `auto` (это значение по умолчанию в приложении).

Не создавай больше одного экземпляра `photo-generation-bot`: Telegram polling должен выполняться одним процессом. `photo-generation-worker` в Blueprint запускается в 4 экземплярах с двумя задачами на экземпляр, то есть максимум восемь генераций одновременно.

`photo-generation-cleanup` запускается каждый час и удаляет в R2 исходные и готовые изображения вместе с завершёнными job старше `RESULT_TTL_HOURS` (по умолчанию 24 часа). Bucket не делай публичным.

## Где взять ключи

1. Telegram: открой в Telegram `@BotFather`, отправь `/newbot`, задай имя `AI-фотобудка` и username, который заканчивается на `bot`. Полученный токен запиши в `TELEGRAM_BOT_TOKEN`.
2. OpenAI: открой [API Keys](https://platform.openai.com/api-keys), создай секретный ключ и запиши его в `OPENAI_API_KEY`.
3. fal.ai: открой [fal.ai/dashboard/keys](https://fal.ai/dashboard/keys), создай ключ со scope `API` и запиши его в `FAL_KEY`.
4. После этого поменяй `MOCK_MODE=true` на `MOCK_MODE=false`.

Пример заполнения `.env`:

```dotenv
BOT_NAME=AI-фотобудка
TELEGRAM_BOT_TOKEN=токен_от_BotFather
OPENAI_API_KEY=ключ_OpenAI
FAL_KEY=ключ_fal_ai
MOCK_MODE=false
```

Не добавляй `.env` в GitHub и не отправляй ключи в чат. `.env` уже добавлен в `.gitignore`. OpenAI рекомендует хранить ключи в переменных окружения и не публиковать их в репозитории; fal.ai также рекомендует переменную `FAL_KEY` и scope `API` для вызова готовых моделей.

## Перед публичным запуском

1. Проверить invoice-flow Telegram Stars в боевом Telegram-аккаунте и выставить рабочую цену.
2. Добавить webhook-режим Telegram вместо polling при деплое.
3. Вынести `MEDIA_DIR` в приватное S3/R2-хранилище и включить TTL-удаление.
4. Добавить модерацию входных фотографий и запросов.
5. Проверить коммерческие условия каждой модели fal.ai.
6. Провести нагрузочный тест и настроить лимиты провайдеров.

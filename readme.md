# Tracer watch

Каждые 5 минут опрашивает API motoauction.online и шлёт в Telegram новые лоты Yamaha Tracer, которые подходят под критерии:

- модель: группы, где в названии есть `TRACER` (`MT-09 TRACER`, `MT-09 TRACER GT`, `TRACER 9 GT+` и `TRACER 9GT`);
- год 2018 и новее;
- оценка 4 и выше;
- стартовая цена не выше лимита: 700 000 ¥, а при оценке 6+ — 730 000 ¥;
- средняя цена не выше лимита × 1.4. Иначе лот почти наверняка уйдёт дороже.

В сообщении есть фото, год, оценка, пробег, дата торгов, старт и средняя цена, прогноз «под ключ» с сайта, комментарий аукциона и замечания инспектора по узлам, а также кнопка «Открыть лот». Когда торги по лоту закончатся, бот ответит на своё сообщение итогом: продан за столько-то или не продан. Если сайт не отвечает дольше 30 минут, бот пришлёт предупреждение, а когда сайт оживёт — сообщение об этом.

Без зависимостей, нужен только Python 3.9+.

## Как это крутится

```
cron-job.org, каждые 5 мин
   ↓  POST api.github.com/.../actions/workflows/watch.yml/dispatches
GitHub Actions: один проход tracer_watch.py (~15 с)
   ↓  новые подходящие лоты → Telegram
   ↓  что уже отправлено → ветка state (коммит только когда что-то поменялось)
```

Своего сервера нет, засыпать нечему. Роль пинговалки здесь играет запуск workflow. В workflow есть и своё расписание раз в 30 минут, но только как подстраховка: GitHub исполняет его с опозданиями.

Почему не Render, как cacher: бесплатные 750 часов в месяц — это на весь аккаунт, и разбуженный круглосуточно cacher съедает их почти целиком. Со вторым таким же сервисом квота кончилась бы к середине месяца, и Render усыпил бы обоих.

Репозиторий публичный, потому что Actions для публичных репозиториев бесплатны без лимита. Запуск раз в 5 минут — это ~8 600 запусков в месяц, а приватному репо дают 2 000 минут. Секретов в коде нет: токен бота и chat_id лежат в секретах репозитория.

## Настройка

### 1. Бот в Telegram

1. В Telegram открыть [@BotFather](https://t.me/BotFather), выполнить `/newbot` и получить токен.
2. Написать своему боту любое сообщение.
3. Локально:

   ```sh
   cp .env.example .env               # вписать TG_BOT_TOKEN
   python3 tracer_watch.py --whoami   # напечатает TG_CHAT_ID — вписать в .env
   python3 tracer_watch.py --test     # должно прийти тестовое сообщение
   ```

### 2. Секреты в GitHub

```sh
gh secret set -f .env -r ersul4ik/tracer-watch
```

Команда загрузит все строки из `.env` в секреты репозитория. Workflow читает оттуда только `TG_BOT_TOKEN` и `TG_CHAT_ID`, остальное ни на что не влияет. Проверка: Actions → **watch** → **Run workflow**. Через ~20 секунд должен появиться зелёный запуск.

### 3. Пинговалка на cron-job.org

1. GitHub → Settings → Developer settings → [Fine-grained tokens](https://github.com/settings/personal-access-tokens/new):
   - Repository access: **Only select repositories** → `tracer-watch`;
   - Permissions → Repository → **Actions: Read and write**;
   - Expiration — максимальный срок. Когда токен истечёт, пинговалка начнёт получать `401`, и его надо будет перевыпустить.
2. [cron-job.org](https://cron-job.org) → **Create cronjob**:
   - Title: `tracer-watch`;
   - URL: `https://api.github.com/repos/ersul4ik/tracer-watch/actions/workflows/watch.yml/dispatches`;
   - Schedule: **Every 5 minutes**;
   - вкладка **Advanced**:
     - Request method: `POST`;
     - Headers:
       - `Authorization: Bearer <токен из п.1>`
       - `Accept: application/vnd.github+json`
       - `Content-Type: application/json`
     - Request body: `{"ref":"main"}`
3. Save → **Test run**. Ответ должен быть `204`, а в Actions появится новый запуск.

## Полезное

```sh
python3 tracer_watch.py --dry-run         # что пришло бы сейчас (ничего не шлёт)
python3 tracer_watch.py --dry-run --all   # то же по всем лотам, включая проданные сегодня
gh workflow run watch -f dry_run=true     # то же самое, но на сервере; результат в логе запуска
gh run list -w watch -L 5                 # последние запуски
```

Критерии по умолчанию зашиты в код. Поменять их на сервере можно в Settings → Secrets and variables → Actions → **Variables**: `LIMIT_JPY`, `TOP_LIMIT_JPY`, `MIN_YEAR`, `MIN_RANK`, `TOP_RANK`, `MAX_AVG_RATIO`, `MODEL_PATTERN`. Например, `gh variable set LIMIT_JPY -b 750000`.

Что уже отправлено, хранится в `state.json` в ветке `state`. Если удалить оттуда лот, бот пришлёт его заново, если тот ещё в продаже.

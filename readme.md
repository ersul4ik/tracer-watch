# Tracer watch

Polls the motoauction.online API every 5 minutes and sends new Yamaha Tracer lots that match the criteria to Telegram:

- model: any model group with `TRACER` in its name (`MT-09 TRACER`, `MT-09 TRACER GT`, `TRACER 9 GT+`, which also covers `TRACER 9GT`);
- year 2018 or newer;
- auction grade 4 or higher;
- starting price within the limit: ¥700,000, or ¥730,000 for grade 6 and up;
- average price for similar lots no higher than 1.4 × the limit. Above that, the lot almost certainly sells for more.

Each alert carries a photo, year, grade, mileage, auction date, starting and average price, the site's landed-cost estimate, the auction comment, the inspector's notes per section, and an "open lot" button. Once the auction is over, the bot replies to its own alert with the outcome: sold and for how much, or not sold. If the site stays unreachable for more than 30 minutes, the bot sends a warning, and another message once it is back.

Once a day, at 10:00 Bishkek time, a digest arrives: how many Tracer lots are on sale, how many alerts went out, and which new lots were skipped and why. There is deliberately no "nothing found" message after every pass: at one pass per 5 minutes that would be 288 messages a day, and real finds would drown in them. The digest doubles as a heartbeat instead: if it does not arrive, something is broken.

The bot writes to Telegram in Russian. No dependencies, Python 3.9+ only.

## How it runs

```
cron-job.org, every 5 min
   ↓  POST api.github.com/.../actions/workflows/watch.yml/dispatches
GitHub Actions: a single pass of tracer_watch.py (~15 s)
   ↓  new matching lots → Telegram
   ↓  what has been sent → the state branch (committed only when something changed)
```

There is no server of its own, so nothing can fall asleep. The keep-alive ping is the workflow dispatch itself. The workflow also has a schedule of its own, every 30 minutes, but only as a fallback: GitHub runs scheduled workflows late and disables them after 60 days without commits.

Why not an always-on web service on Render's free tier: the 750 free hours a month are per account, and one service awake around the clock already takes 744 of them. A second one would run the quota out by mid-month, and Render would suspend both.

The repository is public because Actions minutes are unlimited for public repositories. One pass every 5 minutes is about 8,600 runs a month, while a private repository gets 2,000 minutes. There are no secrets in the code: the bot token and chat id live in the repository secrets.

## Setup

### 1. Telegram bot

1. Open [@BotFather](https://t.me/BotFather), run `/newbot` and take the token.
2. Send your bot any message.
3. Locally:

   ```sh
   cp .env.example .env               # fill in TG_BOT_TOKEN
   python3 tracer_watch.py --whoami   # prints TG_CHAT_ID; put it into .env
   python3 tracer_watch.py --test     # a test message should arrive
   ```

### 2. GitHub secrets

```sh
gh secret set -f .env -R ersul4ik/tracer-watch
```

This uploads every line of `.env` as a repository secret. The workflow reads only `TG_BOT_TOKEN` and `TG_CHAT_ID`; the rest has no effect. To check: Actions → **watch** → **Run workflow**, and a green run should show up within ~20 seconds.

### 3. Keep-alive ping on cron-job.org

1. GitHub → Settings → Developer settings → [Fine-grained tokens](https://github.com/settings/personal-access-tokens/new):
   - Repository access: **Only select repositories** → `tracer-watch`;
   - Permissions → Repositories → **Actions: Read and write**;
   - Expiration: the longest available. Once the token expires, the ping starts getting `401` and the token has to be reissued.
2. [cron-job.org](https://cron-job.org) → **Create cronjob**:
   - Title: `tracer-watch`;
   - URL: `https://api.github.com/repos/ersul4ik/tracer-watch/actions/workflows/watch.yml/dispatches`;
   - Schedule: **Every 5 minutes**;
   - **Advanced** tab:
     - Request method: `POST`;
     - Headers:
       - `Authorization: Bearer <token from step 1>`
       - `Accept: application/vnd.github+json`
       - `Content-Type: application/json`
     - Request body: `{"ref":"main"}`
3. Save → **Test run**. The response should be `204`, and a new run appears under Actions.

## Useful commands

```sh
python3 tracer_watch.py --dry-run          # what would be sent right now (sends nothing)
python3 tracer_watch.py --dry-run --all    # the same over every lot, including those sold today
gh workflow run watch.yml -f dry_run=true  # the same on the server; the output is in the run log
gh run list -w watch.yml -L 5              # latest runs
```

Run logs: [github.com/ersul4ik/tracer-watch/actions](https://github.com/ersul4ik/tracer-watch/actions).

The default criteria live in the code. On the server they can be overridden in Settings → Secrets and variables → Actions → **Variables**: `LIMIT_JPY`, `TOP_LIMIT_JPY`, `MIN_YEAR`, `MIN_RANK`, `TOP_RANK`, `MAX_AVG_RATIO`, `MODEL_PATTERN`, plus the digest hour `DIGEST_HOUR` (`-1` turns it off) and the time zone `TZ_OFFSET_HOURS`. For example, `gh variable set LIMIT_JPY -b 750000`.

What has already been sent is kept in `state.json` on the `state` branch. Deleting a lot from it makes the bot send that lot again if it is still on sale.

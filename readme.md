# Tracer watch

Checks Japanese motorcycle auction listings every 3 hours, or right away when asked in Telegram, and sends new Yamaha Tracer lots that match the criteria:

- model: any model group with `TRACER` in its name (`MT-09 TRACER`, `MT-09 TRACER GT`, `TRACER 9 GT+`, which also covers `TRACER 9GT`);
- year 2018 or newer;
- auction grade 4 or higher;
- the limit is the final hammer price: ¥700,000, or ¥730,000 for grade 6 and up;
- the starting price is only a floor for the final one, so a start over the limit rules the lot out. A start up to 10% over still gets through, flagged as a near miss: it cannot be had within the limit, but might be worth raising it for;
- the expected final price is no higher than 1.3 × the limit. The bot works it out itself from the same site's archive of past sales: the median of the same model within ±1 year and ±1 grade over the last year, widening the match when fewer than three sales qualify. The site's own "average price" runs high (about ¥1.07M for a 2019 GT against a median sale of ¥838k), so it is used only when the archive has nothing comparable.

A lot that has not been inspected yet shows grade 0. The bot waits for the grade, and sends the lot as is if the auction is a day away and there is still none. Once the grade of such a lot comes out, the bot replies to its alert with the inspection sheet and whether the lot still qualifies.

Lots that end unsold although the last bid was within the limit get their own alert, since a buyer at that price existed and only the seller said no. Such lots are often worth haggling over through the dealer for a day or two after the auction, and they tend to come back: 207900 went unsold at a ¥628k bid and sold for ¥590k a week later. So:

- a Tracer that meets the criteria and went unsold in the last two days with a bid within the limit is sent even if the price forecast had filtered it out before the auction, with a hint to negotiate. If the bot already alerted about it, the outcome reply says the same;
- for two months after that the bike is watched by frame number, the one thing that stays when it is relisted under a new lot number. When it is back on either site, the bot sends it as a reply to the earlier alert, with the previous bid, skipping the price forecast.

Unsold lots come from the motoauction archive only: projapan drops them from its listings.

Inspection notes in alerts come from both sources (projapan translates BDS sheets; for JBA it only has section grades). Serious notes — noises, leaks, failed seals, parts that need replacing — go first, marked with ❗, ahead of scratches and light rust.

Each alert carries a photo, year, grade, mileage, auction date, starting price, what similar lots usually sell for (median, number of sales and range), the site's landed-cost estimate, the auction comment, the inspector's notes per section, and an "open lot" button. Once the auction is over, the bot replies to its own alert with the outcome: sold and for how much, or not sold. If the site stays unreachable for more than 30 minutes, the bot sends a warning, and another message once it is back.

Once a day, at 10:00 Bishkek time, a digest arrives: how many Tracer lots are on sale, how many alerts went out, and which new lots were skipped and why. There is deliberately no "nothing found" message after every pass: at one pass per 5 minutes that would be 288 messages a day, and real finds would drown in them. The digest doubles as a heartbeat instead: if it does not arrive, something is broken.

The bot writes to Telegram in Russian. No dependencies, Python 3.9+ only.

## Sources

| Site | Auctions | How | Why |
|---|---|---|---|
| [motoauction.online](https://motoauction.online) | BDS, JBA, some AUCNET | JSON API behind a token from `/api/init` | main source: grades, inspector notes and the sales archive the price estimate is built from |
| [projapan.ru](https://projapan.ru) | BDS, JBA (ARAI and AUCNET too, but see below) | open JSON API, `/api/lot/get-list`, searched by frame prefix | catches BDS and JBA lots that never reach motoauction: on 27.10 there were five, among them a 2020 GT starting at ¥550k |

The same lot on both sites is matched by auction, date and lot number, and only alerted once. projapan is searched by frame prefix (`FRAMES`, default `RN51J,RN70J,RN99J,RNA1J`) because its model names are raw auction listings. If projapan is down, the pass carries on with motoauction alone.

Looked at and left out:
- **motovulkan.com** (BDS, JBA, AUCNET): works, but has no API — parsing its Next.js pages breaks with any redesign, and it found nothing projapan did not.
- **motorom.ru** (adds ARAI and upcoming AUCNET): its robots.txt disallows the search pages. ARAI is small and mostly scooters, and ARAI lots on projapan carry no frame number.
- **bike-place.ru**: BDS and JBA only, nothing new.

## Commands

Messages to the bot from the configured chat (anyone else is ignored):

- `/check`, or a plain-language request to go and look (in Russian) — check the sites now and reply with what is on sale and which already-sent lots are still ahead;
- `/status` — when the last check was and when the next one is due;
- anything else — a short help.

Replies come within about 5 minutes, which is how often the bot wakes up.

## How it runs

```
cron-job.org, every 5 min
   ↓  POST api.github.com/.../actions/workflows/watch.yml/dispatches
GitHub Actions: tracer_watch.py (a few seconds)
   ↓  any messages to the bot? (Telegram getUpdates)
   ↓  site visited only if asked, 3 hours have passed, or the morning digest is due
   ↓  new matching lots and replies → Telegram
   ↓  what has been sent → the state branch (committed only when something changed)
```

There is no server of its own, so nothing can fall asleep. The keep-alive ping is the workflow dispatch itself. Waking up every 5 minutes is only there so that commands get answered: most runs ask Telegram for new messages and stop, and the auction site sees one visit every 3 hours (`SCAN_EVERY_MIN`). Lots show up at least a day before the auction, so that is plenty. The workflow also has a schedule of its own, every 30 minutes, but only as a fallback: GitHub runs scheduled workflows late and disables them after 60 days without commits.

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
gh workflow run watch.yml -f scan=true     # a real check right now, without waiting for the 3 hours
gh run list -w watch.yml -L 5              # latest runs
```

Run logs: [github.com/ersul4ik/tracer-watch/actions](https://github.com/ersul4ik/tracer-watch/actions).

The default criteria live in the code. On the server they can be overridden in Settings → Secrets and variables → Actions → **Variables**: `LIMIT_JPY`, `TOP_LIMIT_JPY`, `MIN_YEAR`, `MIN_RANK`, `TOP_RANK`, `NEAR_RATIO`, `EXPECT_RATIO`, `MODEL_PATTERN`, how often to check the site `SCAN_EVERY_MIN`, plus the digest hour `DIGEST_HOUR` (`-1` turns it off) and the time zone `TZ_OFFSET_HOURS`. For example, `gh variable set LIMIT_JPY -b 750000`.

What has already been sent is kept in `state.json` on the `state` branch. Deleting a lot from it makes the bot send that lot again if it is still on sale.

# Tracer watch

Watches Japanese motorcycle auctions for Yamaha Tracer lots worth buying. When one shows up it sends a Telegram alert, and it keeps a web page with everything it sees: https://ersul4ik.github.io/tracer-watch/

- **Bot:** Python, standard library only. It runs on GitHub Actions every 5 minutes and checks the sites every `SCAN_EVERY_MIN` minutes (3 hours by default, 30 minutes on the server, since good lots can be listed the day before the auction), or right away when asked in Telegram.
- **Database:** SQLite on the `state` branch. It holds what was sent, every lot seen, and your notes.
- **Web page:** React + Tailwind + shadcn/ui on GitHub Pages, phone-first. It reads the data the bot exports after every pass.

## What gets sent

A lot qualifies when:

- **Model:** any model group with `TRACER` in its name (`MT-09 TRACER`, `MT-09 TRACER GT`, `TRACER 9 GT+`, which also covers `TRACER 9GT`).
- **Year:** 2018 or newer.
- **Grade:** auction grade 4 or higher.
- **Final price:** the limit is the final hammer price, ¥700,000 or ¥730,000 for grade 6 and up by default. On the server it is currently ¥750,000 and ¥775,000, set through repository variables.
- **Start price:** the starting price is only a floor for the final one, so a start over the limit rules the lot out. A start up to 10% over still gets through, flagged as a near miss.
- **Expected price:** no higher than 1.3 × the limit by default (`EXPECT_RATIO`; 1.6 on the server, so that well-kept bikes that might go cheap still come through). The bot works it out from the site's archive of past sales: the median of the same model within ±1 year and ±1 grade over the last year, widening the match when fewer than three sales qualify.
  - Each comparable price is first scaled to the mileage of the lot being judged. The rate comes from the archive itself: about 11% per 10,000 km for 2018+ bikes.
  - Without the scaling, a GT with 40,000 km was judged against low-mileage ones and dismissed as "usually goes for ¥1.2M". In a backtest the scaling brought the median error down from 6% to 5%.
  - The site's own "average price" runs high, so it is used only when the archive has nothing comparable.

**Lots without a grade.** A lot that has not been inspected yet shows grade 0. The bot waits for the grade, and sends the lot as is if the auction is a day away and there is still none. Once the grade comes out, the bot replies to its alert with the inspection sheet and whether the lot still qualifies.

**Unsold within the limit.** Lots that end unsold although the last bid was within the limit get their own alert: a buyer at that price existed, only the seller said no.
- Such lots are worth haggling over through the dealer for a day or two after the auction.
- They tend to come back: 207900 went unsold at a ¥628k bid and sold for ¥590k a week later.
- For two months the bike is watched by frame number, the one thing that stays when it is relisted under a new lot number. When it is back, the bot replies to the earlier alert with the previous bid.
- Unsold lots come from the motoauction archive only, since projapan drops them from its listings.

**What an alert contains:**
- a photo, year, grade, mileage, auction date and starting price;
- what similar lots usually sell for;
- the auction comment and the inspector's notes. Serious ones (noises, leaks, failed seals, parts that need replacing) go first, marked with ❗;
- your notes on the bike, if any;
- an "open lot" button.

After the auction the bot replies with the outcome. If a site stays unreachable for more than 30 minutes, it sends a warning.

**Daily digest.** Every day at 10:00 Bishkek time: how many Tracer lots are on sale, how many alerts went out, and which new lots were skipped and why. It doubles as a heartbeat: if it does not arrive, something is broken.

The bot writes to Telegram in Russian; the code is English.

## Notes

You can mark a bike, for example "seen", "too pricey", "needs repair", "mileage", "interesting", plus a comment. Marks attach to the frame number, so they survive a relist and a copy on the other site. They show on the web page, and in Telegram on the next alert about the same bike.

Two ways to leave one:

- **On the web page:** the note button on any lot. The page sends the note to the bot as a run of the `watch` workflow, so it needs a GitHub token with **Actions: Read and write** on this repository only (see the settings dialog on the page). The token stays in that browser. The note shows up within about a minute.
- **In Telegram:** reply with text to the bot's message about a lot.

## Web page

https://ersul4ik.github.io/tracer-watch/ has five tabs (labels are in Russian):

- **Matching:** matching lots on sale as cards: photo, prices, estimate, limit, flags, the inspection sheet and notes;
- **On sale:** every Tracer on sale with the reason it was skipped;
- **Unsold:** bikes left unsold within the limit, and whether they are back;
- **Sent:** everything the bot sent, with auction outcomes;
- **Archive:** past sales with filters and a price-vs-mileage chart.

The header shows when the bot last checked, and turns red when it is overdue. The page reads `board.json` from the `state` branch, so it is as fresh as the bot's last pass. It is public, like the repository, but hidden from search engines.

## Sources

| Site | Auctions | How | Why |
|---|---|---|---|
| [motoauction.online](https://motoauction.online) | BDS, JBA, some AUCNET | JSON API behind a token from `/api/init` | main source: grades, inspector notes and the sales archive |
| [projapan.ru](https://projapan.ru) | BDS, JBA | open JSON API, searched by frame prefix | catches BDS and JBA lots that never reach motoauction |

The same lot on both sites is matched by auction, date and lot number, and only alerted once. projapan is searched by frame prefix (`FRAMES`, default `RN51J,RN70J,RN99J,RNA1J`) because its model names are raw auction listings. If projapan is down, the pass carries on with motoauction alone.

Looked at and left out:
- **motovulkan.com:** no API, and it found nothing projapan did not.
- **motorom.ru:** its robots.txt disallows the search pages.
- **bike-place.ru:** BDS and JBA only, nothing new.
- **Yahoo Auctions Japan:** only a handful of Tracers a month, priced like the auctions, with no inspection sheet and the logistics on the buyer.

## Commands

Messages to the bot from the configured chat (anyone else is ignored):

- `/check`, or a plain-language request to go and look (in Russian): check the sites now;
- `/status`: when the last check was and when the next one is due;
- a text reply to a lot alert: store it as a note on that bike;
- anything else: a short help.

Replies come within about 5 minutes, which is how often the bot wakes up.

## How it runs

```
cron-job.org, every 5 min
   ↓  POST api.github.com/.../actions/workflows/watch.yml/dispatches
GitHub Actions: python -m bot (a few seconds)
   ↓  any messages to the bot? (Telegram getUpdates)
   ↓  sites visited only if asked, SCAN_EVERY_MIN has passed, or the morning digest is due
   ↓  new matching lots and replies → Telegram
   ↓  tracer.db + board.json → the state branch (one fresh commit, only when something changed)
GitHub Pages: the web page reads board.json from the state branch
```

There is no server of its own, so nothing can fall asleep.
- **Keep-alive:** the workflow dispatch itself is the ping. Most runs only ask Telegram for new messages.
- **Fallback:** the workflow also has a schedule of its own, every 30 minutes, because GitHub runs schedules late and disables them after 60 days without commits.
- **Why the repository is public:** Actions minutes are unlimited for public repositories. The bot token and chat id live in the repository secrets.

## Project layout

```
bot/
  main.py          command line (python -m bot)
  config.py        settings from the environment
  sources/         motoauction.py, projapan.py
  pricing.py       limits, the mileage-adjusted estimate, lot keys
  messages.py      Telegram texts
  telegram.py      sending, commands, notes as replies
  scan.py          one pass: send, follow up, outcomes, unsold, relists, digest
  db.py            SQLite: sent, lots, notes, kv
  export.py        board.json for the web page
tests/             unit tests with fake sites (python -m unittest)
web/               the web page (see web/README.md)
.github/workflows/ watch (the bot), test, pages
```

## Setup

### 1. Telegram bot

1. Open [@BotFather](https://t.me/BotFather), run `/newbot` and take the token.
2. Send your bot any message.
3. Locally:

   ```sh
   cp .env.example .env         # fill in TG_BOT_TOKEN
   python -m bot --whoami       # prints TG_CHAT_ID; put it into .env
   python -m bot --test         # a test message should arrive
   ```

### 2. GitHub secrets

```sh
gh secret set -f .env -R ersul4ik/tracer-watch
```

The workflow reads only `TG_BOT_TOKEN` and `TG_CHAT_ID`.

### 3. Keep-alive ping on cron-job.org

1. GitHub → Settings → Developer settings → [Fine-grained tokens](https://github.com/settings/personal-access-tokens/new): only the `tracer-watch` repository, **Actions: Read and write**, the longest expiration.
2. [cron-job.org](https://cron-job.org) → **Create cronjob**:
   - URL: `https://api.github.com/repos/ersul4ik/tracer-watch/actions/workflows/watch.yml/dispatches`;
   - schedule: every 5 minutes;
   - method `POST`;
   - headers `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`, `Content-Type: application/json`;
   - body `{"ref":"main"}`.
3. **Test run** should answer `204`.

### 4. Web page

GitHub Pages is set to deploy from GitHub Actions; the `pages` workflow publishes `web/` on every push that touches it. For notes from the page, create one more token like the one in step 3 (or reuse it) and paste it in the page's settings.

## Useful commands

```sh
python -m bot --dry-run                     # what would be sent right now (sends and stores nothing)
python -m bot --dry-run --all               # the same over every lot, including those sold today
python -m bot --dry-run --board board.json  # and write the web page data locally
python -m unittest discover -s tests -t .   # tests
gh workflow run watch.yml -f scan=true      # a real check on the server right now
gh workflow run watch.yml -f note_key=RN51J003241 -f note_tag=price   # a note from the command line
gh run list -w watch.yml -L 5               # latest runs
```

The criteria defaults live in `bot/config.py`. On the server they can be overridden in Settings → Secrets and variables → Actions → **Variables**:
- price: `LIMIT_JPY`, `TOP_LIMIT_JPY`, `TOP_RANK`, `NEAR_RATIO`, `EXPECT_RATIO`;
- lots: `MIN_YEAR`, `MIN_RANK`, `MODEL_PATTERN`, `FRAMES`;
- schedule: `SCAN_EVERY_MIN`, plus `DIGEST_HOUR` (`-1` turns it off) and `TZ_OFFSET_HOURS`.

For example, `gh variable set LIMIT_JPY -b 750000`.

The database is `tracer.db` on the `state` branch. To inspect it, fetch that branch and open the file with `sqlite3`. Deleting a row from `sent` makes the bot send that lot again if it is still on sale.

Every save keeps the previous version of the `state` branch on `state-prev`. To roll back a bad run: `git push -f origin origin/state-prev:state`.

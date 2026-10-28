"""Settings from the environment (.env locally, secrets and vars in GitHub Actions) and small shared helpers."""
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # repository root
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0 Safari/537.36")

# availability: 0 for sale, 1 sold, 2 not sold (see /status-config.js on motoauction)
FOR_SALE, SOLD, NOT_SOLD = 0, 1, 2


def load_env(path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env(HERE / ".env")


# An empty variable means "use the default": GitHub Actions passes "" for unset vars.*
def env_str(name, default=""):
    return os.environ.get(name) or default


def env_int(name, default):
    return int(env_str(name, default))


def env_float(name, default):
    return float(env_str(name, default))


CFG = {
    "token": env_str("TG_BOT_TOKEN"),
    "chat_id": env_str("TG_CHAT_ID"),
    "brand": env_str("BRAND", "Yamaha"),
    "model_re": re.compile(env_str("MODEL_PATTERN", r"TRACER"), re.I),
    "min_year": env_int("MIN_YEAR", 2018),
    # Tracer frame prefixes to search projapan by: RN51J is 2018-20 (Tracer 900/GT), RN70J 2021-23,
    # RN99J and RNA1J 2025+. RN36J (2015-17) is left out: the year filter would drop it anyway
    "frames": [f.strip() for f in env_str("FRAMES", "RN51J,RN70J,RN99J,RNA1J").split(",") if f.strip()],
    "min_rank": env_float("MIN_RANK", 4),
    "limit": env_int("LIMIT_JPY", 700_000),
    "top_rank": env_float("TOP_RANK", 6),
    "top_limit": env_int("TOP_LIMIT_JPY", 730_000),
    # The limit is the final hammer price. Skip a lot when similar ones usually sell for more than
    # limit times this (0 turns it off). Generous on purpose: 2019 GTs went for anything from 682k to 950k.
    "expect_ratio": env_float("EXPECT_RATIO", 1.3),
    # A start up to limit times this still gets sent, flagged as a near miss: it cannot be had
    # within the limit, but might be worth raising the limit for
    "near_ratio": env_float("NEAR_RATIO", 1.1),
    "db": Path(env_str("DB_FILE", HERE / "tracer.db")),
    # The old JSON state: when there is no database yet, the bot imports it
    "state": Path(env_str("STATE_FILE", HERE / "state.json")),
    # How many minutes a site may stay down before the bot says so in Telegram
    "alert_after_min": env_int("ALERT_AFTER_MIN", 30),
    # How often to visit the sites. Runs in between (the ping every 5 minutes) only check
    # whether the user asked the bot to look right now
    "scan_every_min": env_int("SCAN_EVERY_MIN", 180),
    # What a bike costs landed, for the dollar line in alerts: the hammer price in dollars plus the
    # agent's percentage, plus fixed costs (customs 1800 + shipping 1200 + service 500)
    "jpy_per_usd": env_float("JPY_PER_USD", 155),
    "fee_ratio": env_float("FEE_RATIO", 0.10),
    "fixed_usd": env_int("FIXED_USD", 3500),
    # Daily digest: the local hour to send it at (-1 turns it off) and the UTC offset
    "digest_hour": env_int("DIGEST_HOUR", 10),
    "tz": timezone(timedelta(hours=env_float("TZ_OFFSET_HOURS", 6))),
}


def log(*args):
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), *args, flush=True)


def fmt_jpy(v):
    return f"{v:,}".replace(",", " ") + " ¥" if v else "—"


def fmt_num(v):
    return f"{v:,}".replace(",", " ")

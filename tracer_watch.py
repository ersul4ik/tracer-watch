#!/usr/bin/env python3
"""Следит за motoauction.online и шлёт в Telegram подходящие лоты Yamaha Tracer.

Запуск:
    python3 tracer_watch.py              # один проход (так его запускает GitHub Actions)
    python3 tracer_watch.py --loop 300   # крутиться самому, проход раз в 5 минут
    python3 tracer_watch.py --dry-run    # ничего не слать, показать что было бы
    python3 tracer_watch.py --dry-run --all  # то же, но и по уже проданным лотам (бэктест)
    python3 tracer_watch.py --whoami     # показать chat_id тех, кто написал боту
    python3 tracer_watch.py --test       # отправить тестовое сообщение
"""
import argparse
import html
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE = "https://motoauction.online"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0 Safari/537.36")

# availability: 0 — в продаже, 1 — продан, 2 — не продан (см. /status-config.js на сайте)
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


# Пустая переменная значит «по умолчанию»: GitHub Actions подставляет "" вместо незаданных vars.*
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
    "min_rank": env_float("MIN_RANK", 4),
    "limit": env_int("LIMIT_JPY", 700_000),
    "top_rank": env_float("TOP_RANK", 6),
    "top_limit": env_int("TOP_LIMIT_JPY", 730_000),
    # Пропускать лот, если средняя цена по похожим уже выше лимита в столько раз.
    # 0 — не фильтровать по средней. Средняя на сайте завышена: у GT 2019 она ~1.07 млн
    # при медиане продаж 838к, поэтому порог щедрый.
    "max_avg_ratio": env_float("MAX_AVG_RATIO", 1.6),
    # Старт выше лимита не больше чем во столько раз — лот всё равно присылается как «почти подходит»
    "near_ratio": env_float("NEAR_RATIO", 1.1),
    "state": Path(env_str("STATE_FILE", HERE / "state.json")),
    # Сколько минут сайт может не отвечать, прежде чем бот скажет об этом в Telegram
    "alert_after_min": env_int("ALERT_AFTER_MIN", 30),
    # Ежедневная сводка: в какой час по местному времени (-1 — не слать) и пояс относительно UTC
    "digest_hour": env_int("DIGEST_HOUR", 10),
    "tz": timezone(timedelta(hours=env_float("TZ_OFFSET_HOURS", 6))),
}


def log(*args):
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), *args, flush=True)


def fmt_jpy(v):
    return f"{v:,}".replace(",", " ") + " ¥" if v else "—"


def fmt_num(v):
    return f"{v:,}".replace(",", " ")


class Site:
    def __init__(self):
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.token = None
        self.token_until = 0

    def _get(self, path, params=None, auth=True):
        url = SITE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"User-Agent": UA, "Accept": "application/json", "Referer": SITE + "/"}
        if auth:
            headers["X-Request-Token"] = self._ensure_token()
        for attempt in range(3):
            try:
                with self.opener.open(urllib.request.Request(url, headers=headers), timeout=30) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                # nginx на сайте режет частые запросы 429 — подождать и повторить
                if e.code == 429 and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise

    def _ensure_token(self):
        if not self.token or time.time() > self.token_until:
            d = self._get("/api/init", auth=False)
            self.token = d["t"]
            self.token_until = time.time() + d.get("ttl", 300) - 30
        return self.token

    def model_groups(self, brand):
        d = self._get("/api/models", {"brand": brand})
        return [m["name"] for m in d.get("models", []) if m.get("name")]

    def lots(self, brand, model):
        out, offset = [], 0
        while True:
            d = self._get("/api/lots", {"limit": 100, "offset": offset, "brand": brand,
                                        "model": model, "skip_count": 1})
            page = list((d.get("lots") or {}).values())
            out.extend(page)
            if len(page) < 100:
                return out
            offset += 100

    def lot(self, lot_id):
        return self._get(f"/api/lot/{lot_id}")


class Telegram:
    def __init__(self, token, chat_id, dry_run=False):
        self.token, self.chat_id, self.dry_run = token, chat_id, dry_run

    def call(self, method, **params):
        data = urllib.parse.urlencode(
            {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in params.items()}
        ).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{self.token}/{method}", data=data)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)["result"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Telegram {method}: {e.code} {e.read().decode(errors='replace')}")

    def send(self, text, photo=None, button_url=None, reply_to=None):
        if self.dry_run:
            print("\n----- [dry-run] сообщение -----")
            print(re.sub(r"<[^>]+>", "", text))
            if button_url:
                print(f"[кнопка] {button_url}")
            print("-------------------------------")
            return None
        common = {"chat_id": self.chat_id, "parse_mode": "HTML"}
        if button_url:
            common["reply_markup"] = {"inline_keyboard": [[{"text": "Открыть лот", "url": button_url}]]}
        if reply_to:
            common["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        if photo and len(text) <= 1024:
            try:
                return self.call("sendPhoto", photo=photo, caption=text, **common)["message_id"]
            except RuntimeError as e:
                log("фото не ушло, шлю текстом:", e)
        return self.call("sendMessage", text=text, link_preview_options={"is_disabled": True},
                         **common)["message_id"]


def limit_for(rank):
    if rank is not None and rank >= CFG["top_rank"]:
        return CFG["top_limit"]
    return CFG["limit"]


def check(lot):
    """Возвращает None, если лот подходит, иначе причину отказа."""
    model = lot.get("model") or ""
    year = lot.get("year") or 0
    rank = lot.get("rank")
    if not CFG["model_re"].search(model):
        return f"модель {model}"
    if year < CFG["min_year"]:
        return f"год {year}"
    # Оценка 0 — лот ещё не осмотрен, обычно оценка появляется за пару дней до торгов.
    # Ждём её, но если торги уже завтра, а оценки всё нет, пусть человек глянет сам.
    if not rank:
        if days_to_auction(lot) > 1:
            return "оценки пока нет"
    elif rank < CFG["min_rank"]:
        return f"оценка {rank}"
    limit = limit_for(rank)
    start = lot.get("price") or 0
    if lot.get("availability") == FOR_SALE and start > limit * CFG["near_ratio"]:
        return f"старт {fmt_jpy(start)} выше лимита"
    avg = lot.get("AveragePrice") or 0
    if CFG["max_avg_ratio"] and avg > limit * CFG["max_avg_ratio"]:
        return f"средняя {fmt_jpy(avg)} сильно выше лимита"
    return None


def days_to_auction(lot):
    try:
        day = datetime.strptime(lot.get("auction_date") or "", "%d.%m.%Y").date()
    except ValueError:
        return 0  # дата непонятна — считаем, что торги скоро, и не ждём
    return (day - datetime.now(CFG["tz"]).date()).days


def report_lines(detail):
    """Короткая выжимка листа осмотра: оценка по узлам и замечания."""
    lines = []
    for part in detail.get("inspector_report") or []:
        comments = "; ".join(c for c in part.get("comments") or [] if c)
        if not comments:
            continue
        lines.append(f"• {part.get('title_ru') or part.get('name')} ({part.get('rank') or '?'}): {comments}")
    return lines


def lot_message(lot, detail, max_len):
    rank = lot.get("rank")
    limit = limit_for(rank)
    start = detail.get("price_start_jpy") or lot.get("price") or 0
    avg = detail.get("average_price_jpy") or lot.get("AveragePrice") or 0
    rub = (detail.get("display_price") or {}).get("display")
    rub_label = (detail.get("display_price") or {}).get("label") or "Под ключ"
    flags = []
    if start > limit:
        flags.append(f"🟡 почти подходит: старт выше лимита на {fmt_jpy(start - limit)}")
    if rank and rank >= CFG["top_rank"]:
        flags.append("🔥 топ-оценка")
    if not rank:
        flags.append("⏳ оценки пока нет, торги вот-вот")
    if avg and avg > limit:
        flags.append("⚠️ средняя выше лимита")

    e = html.escape
    head = [
        f"🏍 <b>{e(lot.get('brand') or '')} {e(lot.get('model') or '')}</b> · {lot.get('year')}",
        f"Оценка <b>{rank or '?'}</b> · {fmt_num(lot.get('mileage') or 0)} км"
        f" · {lot.get('volume') or '?'} cc · {e(detail.get('color') or '')}",
        f"Торги <b>{e(lot.get('auction_date') or '?')}</b> · {e(detail.get('auction_line') or lot.get('auction') or '')}"
        f" · лот {e(str(detail.get('lot_number') or lot.get('bid') or ''))}",
        f"Старт: {fmt_jpy(start) if start else 'пока неизвестен'} · средняя: {fmt_jpy(avg)}",
        f"Наш лимит: <b>{fmt_jpy(limit)}</b>" + (f" · {e(rub_label)}: {e(rub)}" if rub else ""),
    ]
    head += flags

    tail = []
    if detail.get("comment_auction_ru"):
        tail.append(f"💬 {e(detail['comment_auction_ru'])}")
    tail += [e(x) for x in report_lines(detail)]

    text = "\n".join(head)
    for line in tail:
        if len(text) + len(line) + 1 > max_len - 4:
            text += "\n…"
            break
        text += "\n" + line
    return text


def result_message(detail):
    av = detail.get("availability")
    final = detail.get("price_finish_jpy") or detail.get("price_jpy") or 0
    rub = (detail.get("display_price") or {}).get("display")
    if av == SOLD:
        s = f"✅ Продан за <b>{fmt_jpy(final)}</b>"
    else:
        s = f"❌ Не продан, последняя ставка {fmt_jpy(final)}"
    if rub and av == SOLD:
        s += f" (под ключ {html.escape(rub)})"
    return s


def load_state():
    try:
        return with_defaults(json.loads(CFG["state"].read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        return with_defaults({})


def with_defaults(state):
    state.setdefault("lots", {})
    # Неподходящие лоты в продаже: когда впервые увидены и почему отсеяны — для сводки
    state.setdefault("skipped", {})
    state.setdefault("fail_since", None)
    state.setdefault("alerted", False)
    return state


def save_state(state):
    # Лоты, впервые увиденные больше 60 дней назад, уже не нужны
    cutoff = time.time() - 60 * 86400
    for name in ("lots", "skipped"):
        state[name] = {k: v for k, v in state[name].items() if v.get("at", 0) > cutoff}
    text = json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    # Файл переписывается, только если что-то поменялось: в Actions каждое изменение — это коммит
    if CFG["state"].exists() and CFG["state"].read_text() == text:
        return
    CFG["state"].parent.mkdir(parents=True, exist_ok=True)
    tmp = CFG["state"].with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(CFG["state"])


def run_once(site, tg, state, include_finished=False, verbose=False):
    lots_state, skipped = state["lots"], state["skipped"]
    first_run = "digest_at" not in state
    groups = [g for g in site.model_groups(CFG["brand"]) if CFG["model_re"].search(g)]
    lots = {}
    for g in groups:
        for lot in site.lots(CFG["brand"], g):
            lots[lot["id"]] = lot
    log(f"группы: {groups}; лотов: {len(lots)}")

    now = time.time()
    for lot_id, lot in sorted(lots.items()):
        key = str(lot_id)
        if key in lots_state:
            continue
        if lot.get("availability") != FOR_SALE and not include_finished:
            continue
        reason = check(lot)
        if verbose:
            log(f"  {lot_id} {lot.get('model')} {lot.get('year')} r{lot.get('rank')} "
                f"av{lot.get('availability')} {lot.get('auction_date')}: {reason or 'ПОДХОДИТ'}")
        if reason:
            # отказ по старту/средней не окончательный — цена может появиться позже,
            # поэтому в lots такие лоты не попадают и проверяются на каждом проходе
            if lot.get("availability") == FOR_SALE:
                line = (f"{lot.get('model')} {lot.get('year')} · оценка {lot.get('rank') or '?'}"
                        f" · торги {(lot.get('auction_date') or '?')[:5]} — {reason}")
                # причина меняется (появилась оценка или старт), а время первого появления — нет
                skipped.setdefault(key, {"at": int(now)})["line"] = line
            continue
        detail = site.lot(lot_id)
        photo = lot.get("pathImg") or next(iter(detail.get("photos") or []), None)
        text = lot_message(lot, detail, 1024 if photo else 4096)
        msg_id = tg.send(text, photo=photo, button_url=f"{SITE}/{lot_id}")
        lots_state[key] = {"at": int(now), "msg": msg_id, "date_ts": detail.get("auction_date_ts") or 0,
                           "done": lot.get("availability") != FOR_SALE}
        log(f"отправлен лот {lot_id}")

    # итоги торгов по лотам, о которых уже писали
    for key, entry in lots_state.items():
        if entry.get("done") or not entry.get("date_ts") or entry["date_ts"] > now:
            continue
        lot = lots.get(int(key))
        if lot is not None and lot.get("availability") == FOR_SALE:
            continue
        try:
            detail = site.lot(key)
        except urllib.error.HTTPError as e:
            log(f"лот {key}: {e.code}")
            continue
        if detail.get("availability") in (SOLD, NOT_SOLD):
            tg.send(result_message(detail), reply_to=entry.get("msg"))
            entry["done"] = True
        elif now - entry["date_ts"] > 3 * 86400:
            entry["done"] = True  # итог так и не появился — перестаём спрашивать

    if first_run:
        # Всё, что лежит на сайте к первому запуску, — не «новое за сутки»
        state["digest_at"] = int(now)
    if not tg.dry_run:
        maybe_send_digest(state, tg, sum(1 for l in lots.values() if l.get("availability") == FOR_SALE))


def maybe_send_digest(state, tg, for_sale):
    """Раз в сутки: что бот видел. Заодно знак, что он жив — нет сводки, значит что-то сломалось."""
    if CFG["digest_hour"] < 0:
        return
    local = datetime.now(CFG["tz"])
    today = local.strftime("%Y-%m-%d")
    if local.hour < CFG["digest_hour"] or state.get("digest_day") == today:
        return
    since = state.get("digest_at", 0)
    sent = sum(1 for v in state["lots"].values() if v["at"] > since)
    new = [v["line"] for v in sorted(state["skipped"].values(), key=lambda v: v["at"]) if v["at"] > since]

    lines = ["📋 <b>Сводка за сутки</b>",
             f"Лотов Tracer в продаже: {for_sale}."
             + (f" Прислал подходящих: <b>{sent}</b>." if sent else " Подходящих не нашлось.")]
    if new:
        lines.append(f"\nНовые за сутки, не подошли ({len(new)}):")
        lines += [f"• {html.escape(x)}" for x in new[:30]]
        if len(new) > 30:
            lines.append(f"… и ещё {len(new) - 30}")
    else:
        lines.append("Других новых лотов не было." if sent else "Новых лотов за сутки не появилось.")
    tg.send("\n".join(lines))
    state["digest_day"], state["digest_at"] = today, int(time.time())


def note_site_ok(state, tg):
    if state["alerted"]:
        tg.send("✅ Сайт снова отвечает, слежу дальше.")
    state["fail_since"], state["alerted"] = None, False


def note_site_down(state, tg, err):
    """Один сбой — не повод будить человека; молчание дольше ALERT_AFTER_MIN — повод."""
    log("сайт не ответил:", repr(err))
    now = int(time.time())
    if not state["fail_since"]:
        state["fail_since"] = now
    down_min = (now - state["fail_since"]) // 60
    if not state["alerted"] and down_min >= CFG["alert_after_min"]:
        tg.send(f"⚠️ motoauction.online не отвечает уже {down_min} мин — лоты сейчас не вижу.\n"
                f"<code>{html.escape(repr(err))[:300]}</code>")
        state["alerted"] = True


def whoami(tg):
    updates = tg.call("getUpdates")
    chats = {}
    for u in updates:
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat")
        if chat:
            chats[chat["id"]] = chat.get("username") or chat.get("title") or chat.get("first_name")
    if not chats:
        print("Пусто. Напиши боту любое сообщение в Telegram и запусти ещё раз.")
    for cid, name in chats.items():
        print(f"TG_CHAT_ID={cid}    # {name}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--loop", type=int, metavar="SEC", help="крутиться и делать проход раз в SEC секунд")
    p.add_argument("--dry-run", action="store_true", help="не слать в Telegram и не трогать state.json")
    p.add_argument("--all", action="store_true", help="с --dry-run: проверить и уже проданные лоты")
    p.add_argument("--whoami", action="store_true", help="показать chat_id из последних сообщений боту")
    p.add_argument("--test", action="store_true", help="отправить тестовое сообщение")
    args = p.parse_args()

    if not args.dry_run and not CFG["token"]:
        sys.exit("Нет TG_BOT_TOKEN — положи его в .env (см. .env.example)")
    tg = Telegram(CFG["token"], CFG["chat_id"], dry_run=args.dry_run)
    if args.whoami:
        return whoami(tg)
    if not args.dry_run and not CFG["chat_id"]:
        sys.exit("Нет TG_CHAT_ID — запусти с --whoami, чтобы узнать его")
    if args.test:
        tg.send("👋 Бот на связи. Буду присылать подходящие Tracer'ы.")
        return

    site = Site()
    # В dry-run состояние не читается и не пишется: каждый прогон видит всё как в первый раз
    state = load_state() if not args.dry_run else with_defaults({})
    while True:
        try:
            run_once(site, tg, state, include_finished=args.dry_run and args.all, verbose=args.dry_run)
        except (OSError, ValueError) as e:  # сеть, HTTP-ошибки сайта, битый JSON
            note_site_down(state, tg, e)
        else:
            note_site_ok(state, tg)
        finally:
            # и после падения посреди прохода: уже отправленные лоты не должны прийти второй раз
            if not args.dry_run:
                save_state(state)
        if not args.loop:
            break
        time.sleep(args.loop)


if __name__ == "__main__":
    main()

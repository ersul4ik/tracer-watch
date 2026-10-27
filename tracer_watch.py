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
import math
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
    # Префиксы рам Tracer для поиска на projapan: RN51J — 2018–20 (Tracer 900/GT), RN70J — 2021–23,
    # RN99J и RNA1J — 2025+. RN36J (2015–17) не ищем: всё равно отсечётся по году
    "frames": [f.strip() for f in env_str("FRAMES", "RN51J,RN70J,RN99J,RNA1J").split(",") if f.strip()],
    "min_rank": env_float("MIN_RANK", 4),
    "limit": env_int("LIMIT_JPY", 700_000),
    "top_rank": env_float("TOP_RANK", 6),
    "top_limit": env_int("TOP_LIMIT_JPY", 730_000),
    # Лимит — финальная цена. Пропускать лот, если похожие обычно уходят дороже лимита
    # в столько раз (0 — не фильтровать). С запасом: разброс цен большой, GT 2019 уходили за 682–950к.
    "expect_ratio": env_float("EXPECT_RATIO", 1.3),
    # Старт выше лимита не больше чем во столько раз — лот всё равно присылается как «почти подходит»:
    # в лимит его уже не взять, но может стоить поднять лимит
    "near_ratio": env_float("NEAR_RATIO", 1.1),
    "state": Path(env_str("STATE_FILE", HERE / "state.json")),
    # Сколько минут сайт может не отвечать, прежде чем бот скажет об этом в Telegram
    "alert_after_min": env_int("ALERT_AFTER_MIN", 30),
    # Как часто ходить на сайт. Запуски чаще (пинговалка раз в 5 минут) только проверяют,
    # не написал ли человек боту «сходи посмотри»
    "scan_every_min": env_int("SCAN_EVERY_MIN", 180),
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

    def lots(self, brand, model, statistics=False):
        """statistics=True — архив прошедших торгов (страница «Статистика» на сайте)."""
        out, offset = [], 0
        while True:
            params = {"limit": 100, "offset": offset, "brand": brand, "model": model, "skip_count": 1}
            if statistics:
                params["statistics"] = 1
            d = self._get("/api/lots", params)
            page = list((d.get("lots") or {}).values())
            out.extend(page)
            if len(page) < 100:
                return out
            offset += 100

    def lot(self, lot_id):
        return self._get(f"/api/lot/{lot_id}")


class ProJapan:
    """Второй источник: projapan.ru — тоже витрина японских мотоаукционов, с открытым JSON API.

    Нужен ради лотов BDS и JBA, которые до motoauction не доходят (на 27.10 таких было пять,
    среди них GT 2020 со стартом 550к). Ищем по префиксу рамы: названия моделей там
    сырые, из аукциона («MT-09 TRE ｰｻｰGT»), а рама надёжна.
    """
    BASE = "https://projapan.ru"
    AUCTIONS = {1: "BDS", 2: "JBA", 3: "ARAI", 4: "AUCNET"}
    STATUS = {(0, 0): FOR_SALE, (1, 1): SOLD, (1, 0): NOT_SOLD}
    NO_PRICE = (0, 99990000)  # «старт не объявлен»

    def _get(self, params, method="get-list"):
        url = f"{self.BASE}/api/lot/{method}?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        for attempt in range(2):  # projapan иногда задумывается на полминуты — один повтор
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    d = json.load(r)
                break
            except OSError:
                if attempt:
                    raise
                time.sleep(5)
        time.sleep(1)  # сайт чужой, не торопимся
        if d.get("status") != "OK":
            raise ValueError(f"projapan: {str(d)[:200]}")
        return d["response"]

    def lots(self):
        out = {}
        for prefix in CFG["frames"]:
            page = 1
            while True:
                r = self._get({"lang": "ru", "limit": 100, "page": page, "type": "no_sold",
                               "filters[frame_number]": prefix})
                for x in r["list"]:
                    lot = self._lot(x)
                    out[lot["id"]] = lot
                if page * r["limit"] >= r["total_count"]:
                    break
                page += 1
        return out

    def _lot(self, x):
        day = (x.get("auction_date") or "")[:10]
        try:
            day = datetime.strptime(day, "%Y-%m-%d")
        except ValueError:
            day = None
        price = x.get("price_start") or 0
        place = (x.get("place") or "").split("\n")[0]
        auction = self.AUCTIONS.get(x.get("parser_type"), str(x.get("parser_type")))
        lot = {"id": f"pj:{x['id']}", "url": f"{self.BASE}/lot/{x['id']}", "site": "projapan",
               "brand": CFG["brand"], "model": (x.get("model") or {}).get("title") or x.get("parser_model") or "",
               "year": x.get("year") or None, "rank": x.get("rank") or None,
               "price": 0 if price in self.NO_PRICE else price, "AveragePrice": 0,
               "availability": self.STATUS.get((x.get("auction_status"), x.get("sold_status")), NOT_SOLD),
               "auction": auction, "auction_date": day.strftime("%d.%m.%Y") if day else None,
               "bid": x.get("lot_number"), "mileage": x.get("mileage"), "volume": x.get("cubature"),
               "pathImg": x.get("preview"), "final": x.get("price_end") or 0}
        lot["detail"] = {
            "price_start_jpy": lot["price"], "average_price_jpy": 0, "color": x.get("color"),
            "auction_line": f"{auction} {place}".strip(), "lot_number": x.get("lot_number"),
            "frame_number": x.get("frame_number"),
            "auction_date_ts": int(day.replace(tzinfo=CFG["tz"]).timestamp()) if day else 0,
            "ratings_line": self._ratings_line(x),
            "availability": lot["availability"], "price_finish_jpy": lot["final"]}
        return lot

    @staticmethod
    def _ratings_line(x):
        ratings = [f"{r['title'].lower()} {r['value']}" for r in x.get("ratings") or []
                   if r.get("parser_title") != "global" and r.get("value") not in (None, "", "0")]
        return ("Оценки по узлам: " + ", ".join(ratings)) if ratings else None

    # Служебные поля листа осмотра — не замечания
    NOT_NOTES = {"bid", "key", "horn", "lane", "year", "color", "meter", "frame_no", "displacement",
                 "engine_model", "registration", "starting_bid", "ranking_status", "genuine_parts",
                 "sales_data", "meter_pvi", "bds_comment"}

    # Поля, чей текст без названия узла непонятен («Правая-under сильно» — это течь масла)
    NOTE_LABELS = {"oil_leak": "Течь масла", "tube_outer": "Вилка", "tube_inner": "Вилка",
                   "front_brake": "Передний тормоз", "rear_brake": "Задний тормоз",
                   "front_break": "Передний тормоз", "rear_break": "Задний тормоз",  # так в их данных
                   "front_tire": "Передняя покрышка", "rear_tire": "Задняя покрышка",
                   "front_wheel": "Переднее колесо", "rear_wheel": "Заднее колесо",
                   "rear_shock": "Задний амортизатор", "clutch": "Сцепление"}

    def enrich(self, lot):
        """Дописывает в detail лота лист осмотра: в списке его нет, только на странице лота.

        У BDS замечания переведены на русский, у JBA — сырые японские поля, их пропускаем
        (берём только то, где есть кириллица); оценки по узлам есть у обоих.
        """
        x = self._get({"id": lot["id"][3:], "lang": "ru"}, method="get-by-id")
        meta = x.get("metadata_ru") or {}
        detail = lot["detail"]
        notes = []
        for k, v in meta.items():
            if (isinstance(v, str) and k not in self.NOT_NOTES and not k.startswith(("rank_", "detail_title"))
                    and re.search(r"[А-Яа-яЁё]", v)):
                label = self.NOTE_LABELS.get(k)
                v = v.strip()
                notes.append(f"{label}: {v}" if label and not v.lower().startswith(label.lower()) else v)
        detail["notes"] = notes
        prev = re.sub(r"\D", "", str(meta.get("meter_pvi") or ""))
        if prev:
            detail["prev_meter"] = f"{fmt_num(int(prev))} км"
        detail["ratings_line"] = self._ratings_line(x) or detail.get("ratings_line")
        lot["rank"] = x.get("rank") or lot["rank"]
        return detail

    def result(self, key, frame):
        """Итог торгов лота: проданные лежат в архиве (type=sold), ищем по раме."""
        if not frame:
            return {}
        r = self._get({"lang": "ru", "limit": 100, "page": 1, "type": "sold", "filters[frame_number]": frame})
        for x in r["list"]:
            if f"pj:{x['id']}" == key:
                return self._lot(x)["detail"]
        return {}


def same_lot_key(lot):
    """Один и тот же лот на разных сайтах: аукцион + дата торгов + номер лота."""
    digits = re.sub(r"\D", "", str(lot.get("bid") or ""))
    auction = {"IAUC": "AUCNET"}.get(lot.get("auction"), lot.get("auction"))  # motoauction зовёт AUCNET по его площадке
    return f"{auction}|{lot.get('auction_date')}|{int(digits)}" if digits else None


def stats_model(name):
    """Названия модели на сайтах разные («Tracer 900 GT» на projapan = «MT-09 TRACER GT»)."""
    compact = re.sub(r"\s+|ABS", "", (name or "").upper()).replace("YAMAHA", "")
    if "900GT" in compact or compact == "MT-09TRACERGT":
        return "MT-09TRACERGT"
    if compact in ("MT-09TRACER", "TRACER900"):
        return "MT-09TRACER"
    return compact


class Stats:
    """За сколько похожие лоты реально уходили — по архиву продаж того же сайта за год.

    Средняя цена с сайта для этого не годится: у GT 2019 она ~1.07 млн при медиане
    продаж 838к. Архив грузится лениво, только когда есть кого оценивать.
    """

    def __init__(self, site, groups):
        self.site, self.groups, self.sold, self.unsold = site, groups, None, None

    def _load(self):
        cutoff = datetime.now(CFG["tz"]).date() - timedelta(days=365)
        rows = {}
        for g in self.groups:
            for lot in self.site.lots(CFG["brand"], g, statistics=True):
                lot["url"] = f"{SITE}/{lot['id']}"
                rows[lot["id"]] = lot
        self.sold, self.unsold = [], []
        for lot in rows.values():
            day = auction_day(lot)
            if not day or day < cutoff or not lot.get("price"):
                continue
            if lot.get("availability") == SOLD:
                self.sold.append(lot)
            elif lot.get("availability") == NOT_SOLD:
                self.unsold.append(lot)  # price у них — последняя ставка
        self.per_km = self._fit_mileage()
        log(f"архив продаж: {len(self.sold)} лотов за год, не продано {len(self.unsold)}; "
            f"10 тыс. км пробега — минус {(1 - math.exp(-self.per_km * 10)) * 100:.0f}% цены")

    def _fit_mileage(self):
        """Насколько дешевеет лот с каждой тысячей км: наклон логарифма цены по пробегу внутри групп
        «модель + год + оценка». По архиву 2018+ выходит ~11% на 10 тыс. км: GT 2021 с оценкой 5
        ушли за 1.285 млн при 5 тыс. км, 910к при 30 тыс. и 600к при 70 тыс.
        """
        groups = {}
        for s in self.sold:
            if s.get("mileage") and s.get("rank") and (s.get("year") or 0) >= CFG["min_year"]:
                key = (stats_model(s.get("model")), s["year"], s["rank"])
                groups.setdefault(key, []).append((s["mileage"] / 1000, math.log(s["price"])))
        sxy = sxx = 0
        for pts in groups.values():
            mx, my = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
            sxy += sum((x - mx) * (y - my) for x, y in pts)
            sxx += sum((x - mx) ** 2 for x, _ in pts)
        # мало данных или странный наклон — берём разумные рамки, а не что вышло
        return min(max(-sxy / sxx, 0.003), 0.02) if sxx else 0.008

    def not_sold(self):
        if self.unsold is None:
            self._load()
        return self.unsold

    def _at_mileage(self, sale, km):
        """Цена проданного лота, пересчитанная на пробег оцениваемого: без этого мотоцикл
        с 40 тыс. км мерился бы по малопробежным и отсеивался как «уходят за 1.2 млн»."""
        if not km or not sale.get("mileage"):
            return sale["price"]
        factor = math.exp(self.per_km * (sale["mileage"] - km) / 1000)
        return int(round(sale["price"] * min(max(factor, 0.45), 1.6), -3))

    def estimate(self, lot):
        """Медиана финальных цен похожих лотов или None, если похожих меньше трёх.

        Сначала та же модель ±1 год и оценка ±1, потом без оценки, потом ±2 года.
        Цены похожих пересчитаны на пробег этого лота.
        """
        if self.sold is None:
            self._load()
        model, year, rank = stats_model(lot.get("model")), lot.get("year") or 0, lot.get("rank")
        km = lot.get("mileage")
        for years, by_rank in ((1, True), (1, False), (2, False)):
            if by_rank and not rank:
                continue
            prices = sorted(
                self._at_mileage(s, km) for s in self.sold
                if stats_model(s.get("model")) == model and abs((s.get("year") or 0) - year) <= years
                and (not by_rank or (s.get("rank") and abs(s["rank"] - rank) <= 1))
                and s.get("id") != lot.get("id"))
            if len(prices) >= 3:
                scope = f"{year - years}–{year + years}" + (f", оценка {rank - 1:g}–{rank + 1:g}" if by_rank else "")
                if km:
                    scope += f", в пересчёте на {fmt_num(km)} км"
                return {"median": prices[len(prices) // 2], "n": len(prices),
                        "lo": prices[0], "hi": prices[-1], "scope": scope}
        return None


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


def expected_price(lot, stats):
    """Ожидаемая финальная цена: по архиву продаж, а без него — средняя с сайта."""
    est = stats.estimate(lot) if stats else None
    return est["median"] if est else (lot.get("AveragePrice") or 0), est


def basic_reason(lot):
    """Модель, год и оценка — то, что не зависит от цены."""
    model = lot.get("model") or ""
    year = lot.get("year") or 0
    rank = lot.get("rank")
    if not CFG["model_re"].search(model):
        return f"модель {model}"
    # Год неизвестен бывает у лотов projapan — их ищем по раме, а рама сама говорит о годах
    if year and year < CFG["min_year"]:
        return f"год {year}"
    # Оценка 0 — лот ещё не осмотрен, обычно оценка появляется за пару дней до торгов.
    # Ждём её, но если торги уже завтра, а оценки всё нет, пусть человек глянет сам.
    if not rank:
        if days_to_auction(lot) > 1:
            return "оценки пока нет"
    elif rank < CFG["min_rank"]:
        return f"оценка {rank}"
    return None


def check(lot, stats=None):
    """Возвращает None, если лот подходит, иначе причину отказа.

    Лимит — это финальная цена. Старт — только нижняя граница финала, а угадывает финал
    медиана продаж похожих лотов.
    """
    reason = basic_reason(lot)
    if reason:
        return reason
    rank = lot.get("rank")
    limit = limit_for(rank)
    start = lot.get("price") or 0
    if lot.get("availability") == FOR_SALE and start > limit * CFG["near_ratio"]:
        return f"старт {fmt_jpy(start)} выше лимита"
    if CFG["expect_ratio"]:
        expected, est = expected_price(lot, stats)
        if expected > limit * CFG["expect_ratio"]:
            source = f"медиана {est['n']} продаж" if est else "средняя с сайта"
            return f"обычно уходят за ~{fmt_jpy(expected)} ({source})"
    return None


def unsold_bid(lot):
    """Последняя ставка непроданного лота, если она уложилась в лимит, иначе 0.

    Такой лот — шанс: покупатель за наши деньги нашёлся, не согласился продавец.
    С ним можно поторговаться после торгов, а перевыставляют его часто дешевле
    (207900 не отдали за 628к — через неделю ушёл за 590к).
    """
    bid = lot.get("price") or 0
    if lot.get("availability") == NOT_SOLD and 0 < bid <= limit_for(lot.get("rank")) and not basic_reason(lot):
        return bid
    return 0


def frame_key(lot):
    """Рама — единственное, что у мотоцикла не меняется при перевыставлении: номер лота новый."""
    frame = lot.get("frame") or (lot.get("detail") or {}).get("frame_number") or ""
    return re.sub(r"[^A-Z0-9]", "", frame.upper()) or None


def auction_day(lot):
    try:
        return datetime.strptime(lot.get("auction_date") or "", "%d.%m.%Y").date()
    except ValueError:
        return None


def days_to_auction(lot):
    day = auction_day(lot)
    if not day:
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


# Замечания, из-за которых лот стоит смотреть внимательно: шумы, течи, «требует замены».
# «Сильно» серьёзно, только если это не царапины
SERIOUS_RE = re.compile(r"требует замен|failure|неисправ|не работ|шум|течь|утечк|трещин"
                        r"|^(?!.*царапин).*сильно", re.I)


def inspection_lines(detail):
    """Лист осмотра для сообщения, серьёзные замечания — первыми и с ❗."""
    lines = []
    if detail.get("comment_auction_ru"):
        lines.append(f"💬 {detail['comment_auction_ru']}")
    if detail.get("ratings_line"):
        lines.append(detail["ratings_line"])
    if detail.get("prev_meter"):
        lines.append(f"Пробег на прошлой проверке: {detail['prev_meter']}")
    notes = report_lines(detail) + [f"• {n}" for n in detail.get("notes") or []]
    lines += ["❗" + n[1:] for n in notes if SERIOUS_RE.search(n)]
    lines += [n for n in notes if not SERIOUS_RE.search(n)]
    return [html.escape(x) for x in lines]


def fit(head, tail, max_len):
    text = "\n".join(head)
    for line in tail:
        if len(text) + len(line) + 1 > max_len - 4:
            return text + "\n…"
        text += "\n" + line
    return text


def lot_message(lot, detail, max_len, stats=None, intro=()):
    rank = lot.get("rank")
    limit = limit_for(rank)
    start = detail.get("price_start_jpy") or lot.get("price") or 0
    avg = detail.get("average_price_jpy") or lot.get("AveragePrice") or 0
    expected, est = expected_price(lot, stats)
    rub = (detail.get("display_price") or {}).get("display")
    rub_label = (detail.get("display_price") or {}).get("label") or "Под ключ"
    flags = []
    if start > limit:
        flags.append(f"🟡 почти: старт уже выше лимита на {fmt_jpy(start - limit)}"
                     " — в лимит не взять, только если его поднять")
    if rank and rank >= CFG["top_rank"]:
        flags.append("🔥 топ-оценка")
    if not rank:
        flags.append("⏳ оценки пока нет, торги вот-вот")
    if expected > limit:
        flags.append("⚠️ обычно уходят дороже лимита")
    if est:
        expect_line = (f"Обычно уходят за: <b>~{fmt_jpy(est['median'])}</b> "
                       f"(медиана {est['n']} продаж, {est['scope']}; от {fmt_jpy(est['lo'])} до {fmt_jpy(est['hi'])})")
    else:
        expect_line = f"Средняя с сайта: {fmt_jpy(avg)} (своих продаж для сравнения мало)"

    e = html.escape
    head = [*intro,
        f"🏍 <b>{e(lot.get('brand') or '')} {e(lot.get('model') or '')}</b> · {lot.get('year') or 'год ?'}",
        f"Оценка <b>{rank or '?'}</b> · {fmt_num(lot.get('mileage') or 0)} км"
        f" · {lot.get('volume') or '?'} cc · {e(detail.get('color') or '')}",
        f"Торги <b>{e(lot.get('auction_date') or '?')}</b> · {e(detail.get('auction_line') or lot.get('auction') or '')}"
        f" · лот {e(str(detail.get('lot_number') or lot.get('bid') or ''))}",
        f"Старт: {fmt_jpy(start) if start else 'пока неизвестен'}",
        expect_line,
        f"Наш лимит (финал): <b>{fmt_jpy(limit)}</b>" + (f" · {e(rub_label)}: {e(rub)}" if rub else ""),
    ]
    head += flags
    if lot.get("site") == "projapan":
        head.append(f"🔎 нашёл на projapan.ru, на motoauction этого лота нет · рама {e(detail.get('frame_number') or '?')}")

    return fit(head, inspection_lines(detail), max_len)


def grade_message(lot, detail, stats):
    """Дополнение к лоту, ушедшему без оценки: что оказалось в листе осмотра и подходит ли он теперь."""
    reason = check(lot, stats)
    head = [f"📋 Появилась оценка: <b>{lot['rank']:g}</b>"]
    _, est = expected_price(lot, stats)
    if est:
        head.append(f"Обычно уходят за: ~{fmt_jpy(est['median'])} (медиана {est['n']} продаж, {est['scope']})")
    tail = inspection_lines(detail)
    if reason:
        head.append(f"❌ Теперь не подходит: {html.escape(reason)}")
    elif any(x.startswith("❗") for x in tail):
        head.append("🟡 По критериям подходит, но в листе осмотра есть серьёзные замечания ❗")
    else:
        head.append("✅ По-прежнему подходит")
    return fit(head, tail, 4096)


NEGOTIATE = ("Можно попросить дилера поторговаться: после торгов продавцы иногда отдают чуть дороже ставки, "
             "но обычно только день-два. Если мотоцикл выставят снова, напишу.")


def result_message(detail):
    av = detail.get("availability")
    final = detail.get("price_finish_jpy") or detail.get("price_jpy") or 0
    rub = (detail.get("display_price") or {}).get("display")
    if av == SOLD:
        s = f"✅ Продан за <b>{fmt_jpy(final)}</b>"
    else:
        s = f"❌ Не продан, последняя ставка {fmt_jpy(final)}"
        if 0 < final <= limit_for(detail.get("rank")):
            s += "\n🤝 Покупатель в наш лимит нашёлся, не согласился продавец. " + NEGOTIATE
    if rub and av == SOLD:
        s += f" (под ключ {html.escape(rub)})"
    return s


def serious_warning(detail):
    if any(x.startswith("❗") for x in inspection_lines(detail)):
        return ["❗ В листе осмотра серьёзные замечания — возможно, ставки низкие из-за них, а не по везению."]
    return []


def unsold_intro(prev, detail):
    return [f"🤝 <b>Не продан: ставка дошла до {fmt_jpy(prev['price'])}, продавец не отдал</b>", NEGOTIATE,
            *serious_warning(detail), ""]


def relist_intro(prev, detail):
    return [f"🔁 <b>Снова на торгах.</b> {html.escape(prev.get('auction_date') or '?')} на "
            f"{html.escape(prev.get('auction') or '?')} его не продали: ставка дошла до "
            f"<b>{fmt_jpy(prev['price'])}</b>, продавец хотел больше",
            "Присылаю, даже если похожие обычно уходят дороже: свою цену продавец уже не получил и может уступить.",
            *serious_warning(detail), ""]


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
            lot["url"] = f"{SITE}/{lot['id']}"
            lots[str(lot["id"])] = lot
    log(f"группы: {groups}; лотов: {len(lots)}")
    stats = Stats(site, groups)

    # projapan добавляет только то, чего на motoauction нет. Его сбой не повод молчать
    # о лотах с motoauction — просто проход без второго источника
    projapan = ProJapan()
    known = {same_lot_key(l) for l in lots.values()}
    everywhere = dict(lots)  # и копии с обоих сайтов — чтобы найти лот, о котором уже писали
    extra = None
    try:
        pj = projapan.lots()
        everywhere.update(pj)
        extra = {k: l for k, l in pj.items() if same_lot_key(l) not in known}
        log(f"projapan: нет на motoauction — {len(extra)}")
        lots.update(extra)
    except (OSError, ValueError) as e:
        log("projapan не ответил:", repr(e))

    def same_of(key):
        entry, lot = lots_state.get(key) or {}, everywhere.get(key)
        return entry.get("same") or (same_lot_key(lot) if lot else None)

    # Лот мог уйти с одного сайта, а потом появиться на другом: projapan показал его
    # раньше, motoauction добавил позже. Второй раз о нём писать не надо
    sent_same = {same_of(k) for k in lots_state} - {None}

    def settle_copies(key, field):
        """Дополнение или итог отправлены по одной копии лота — остальным уже не нужно."""
        same = same_of(key)
        for k, e in lots_state.items():
            if same and same_of(k) == same:
                e[field] = True

    def copies_of(lot):
        """Ключи записей state, отправленных об этом лоте — с любого из сайтов."""
        key, same = str(lot["id"]), same_lot_key(lot)
        return [k for k in lots_state if k == key or (same and same_of(k) == same)]

    # Не проданные за два месяца, хотя ставка уложилась в лимит: рама → последний такой лот.
    # projapan непроданных не показывает — они просто пропадают из выдачи, так что только motoauction
    watched = {}
    for lot in sorted(stats.not_sold(), key=auction_day):
        if unsold_bid(lot) and frame_key(lot) and days_to_auction(lot) >= -60:
            watched[frame_key(lot)] = lot

    now = time.time()
    for key, lot in sorted(lots.items()):
        if key in lots_state or same_lot_key(lot) in sent_same:
            continue
        if lot.get("availability") != FOR_SALE and not include_finished:
            continue
        # Тот же мотоцикл, что недавно не продали в наш лимит, снова выставлен
        prev = watched.get(frame_key(lot))
        relist = bool(prev and lot.get("availability") == FOR_SALE
                      and (auction_day(lot) or auction_day(prev)) > auction_day(prev))
        reason = basic_reason(lot) if relist else check(lot, stats)
        if verbose:
            log(f"  {key} {lot.get('model')} {lot.get('year')} r{lot.get('rank')} "
                f"av{lot.get('availability')} {lot.get('auction_date')}: {reason or 'ПОДХОДИТ'}"
                + (f" (перевыставлен, был {prev['id']})" if relist else ""))
        if reason:
            # отказ по старту/оценке не окончательный — они могут появиться позже,
            # поэтому в lots такие лоты не попадают и проверяются на каждом проходе
            if lot.get("availability") == FOR_SALE:
                line = (f"{lot.get('model')} {lot.get('year') or '?'} · оценка {lot.get('rank') or '?'}"
                        f" · торги {(lot.get('auction_date') or '?')[:5]} — {reason}")
                # причина меняется (появилась оценка или старт), а время первого появления — нет
                skipped.setdefault(key, {"at": int(now)})["line"] = line
            continue
        detail = projapan.enrich(lot) if lot.get("site") == "projapan" else site.lot(lot["id"])
        photo = lot.get("pathImg") or next(iter(detail.get("photos") or []), None)
        text = lot_message(lot, detail, 1024 if photo else 4096, stats, intro=relist_intro(prev, detail) if relist else ())
        # перевыставленный — ответом на прошлое сообщение о нём, если оно было
        reply_to = next((lots_state[k].get("msg") for k in copies_of(prev)), None) if relist else None
        msg_id = tg.send(text, photo=photo, button_url=lot["url"], reply_to=reply_to)
        lots_state[key] = {"at": int(now), "msg": msg_id, "date_ts": detail.get("auction_date_ts") or 0,
                           "done": lot.get("availability") != FOR_SALE, "graded": bool(lot.get("rank")),
                           "same": same_lot_key(lot)}
        if lot.get("site") == "projapan":
            lots_state[key]["frame"] = detail.get("frame_number")  # по раме потом найдём итог
        if relist:
            lots_state[key]["relist_of"] = str(prev["id"])
        log(f"отправлен лот {key}" + (f", перевыставленный {prev['id']}" if relist else ""))

    # Лоты, ушедшие без оценки: когда она появилась — дописать ответом, что в листе осмотра.
    # У старых записей поля graded нет — они уходили уже с оценкой
    for key, entry in lots_state.items():
        lot = everywhere.get(key)
        if entry.get("done") or entry.get("graded", True) or not lot or not lot.get("rank"):
            continue
        try:
            detail = projapan.enrich(lot) if lot.get("site") == "projapan" else site.lot(lot["id"])
        except (OSError, ValueError) as e:
            log(f"лот {key}: {e!r}")
            continue
        tg.send(grade_message(lot, detail, stats), reply_to=entry.get("msg"))
        settle_copies(key, "graded")
        entry["graded"] = True
        log(f"дописана оценка лота {key}")

    # итоги торгов по лотам, о которых уже писали
    for key, entry in lots_state.items():
        if entry.get("done") or not entry.get("date_ts") or entry["date_ts"] > now:
            continue
        lot = everywhere.get(key)
        if lot is not None and lot.get("availability") == FOR_SALE:
            continue
        try:
            detail = projapan.result(key, entry.get("frame")) if key.startswith("pj:") else site.lot(key)
        except (OSError, ValueError) as e:
            log(f"лот {key}: {e!r}")
            continue
        if detail.get("availability") in (SOLD, NOT_SOLD):
            tg.send(result_message(detail), reply_to=entry.get("msg"))
            settle_copies(key, "done")
            entry["done"] = True
        elif now - entry["date_ts"] > 3 * 86400:
            entry["done"] = True  # итог так и не появился — перестаём спрашивать

    # Только что не проданные, хотя ставка уложилась в лимит: пока продавец не остыл, можно торговаться.
    # Прогноз цены такие лоты до торгов отсеивал, так что обычно о них ещё не писали
    for lot in watched.values():
        key, same, sent = str(lot["id"]), same_lot_key(lot), copies_of(lot)
        if days_to_auction(lot) < -2 or any(lots_state[k].get("done") for k in sent):
            continue
        try:
            detail = site.lot(lot["id"])
        except (OSError, ValueError) as e:
            log(f"лот {key}: {e!r}")
            continue
        if sent:
            # писали о его копии с projapan — а там итога непроданного не узнать
            tg.send(result_message(detail), reply_to=lots_state[sent[0]].get("msg"))
            settle_copies(sent[0], "done")
            continue
        photo = lot.get("pathImg") or next(iter(detail.get("photos") or []), None)
        text = lot_message(lot, detail, 1024 if photo else 4096, stats, intro=unsold_intro(lot, detail))
        lots_state[key] = {"at": int(now), "msg": tg.send(text, photo=photo, button_url=lot["url"]),
                           "date_ts": detail.get("auction_date_ts") or 0, "done": True, "graded": True,
                           "same": same, "unsold": lot["price"]}
        log(f"отправлен непроданный лот {key}")

    if first_run:
        # Всё, что лежит на сайте к первому запуску, — не «новое за сутки»
        state["digest_at"] = int(now)
    for_sale = [l for l in lots.values() if l.get("availability") == FOR_SALE]
    if not tg.dry_run:
        maybe_send_digest(state, tg, len(for_sale))
    # для ответа на «сходи посмотри»: что сейчас в продаже из уже присланного — со ссылками на все копии
    def urls(lot):
        same = same_lot_key(lot)
        return [l["url"] for l in everywhere.values() if l is lot or (same and same_lot_key(l) == same)]

    return {"for_sale": len(for_sale),
            "projapan_only": None if extra is None else sum(1 for l in extra.values()
                                                            if l.get("availability") == FOR_SALE),
            "sent_now": [k for k, v in lots_state.items() if v["at"] == int(now)],
            "open": [(l, urls(l)) for k, l in lots.items() if l.get("availability") == FOR_SALE and k in lots_state]}


def digest_due(state):
    if CFG["digest_hour"] < 0:
        return False
    local = datetime.now(CFG["tz"])
    return local.hour >= CFG["digest_hour"] and state.get("digest_day") != local.strftime("%Y-%m-%d")


def maybe_send_digest(state, tg, for_sale):
    """Раз в сутки: что бот видел. Заодно знак, что он жив — нет сводки, значит что-то сломалось."""
    if not digest_due(state):
        return
    today = datetime.now(CFG["tz"]).strftime("%Y-%m-%d")
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


CHECK_RE = re.compile(r"/check|/scan|сходи|посмотр|провер|глян", re.I)
STATUS_RE = re.compile(r"/status|статус|жив", re.I)
HELP = ("Я слежу за лотами Tracer и пишу, когда появляется подходящий.\n"
        "• «сходи посмотри» или /check — проверить сайт прямо сейчас\n"
        "• /status — когда проверял последний раз\n"
        "Отвечаю в течение ~5 минут: чаще меня не будят.")


def poll_commands(tg, state):
    """Что человек написал боту с прошлого запуска. Только из своего чата — чужим бот не отвечает."""
    try:
        updates = tg.call("getUpdates", offset=state.get("tg_offset", 0), timeout=0,
                          allowed_updates=["message"])
    except (RuntimeError, OSError) as e:
        log("не смог прочитать сообщения:", e)
        return []
    commands = []
    for u in updates:
        state["tg_offset"] = u["update_id"] + 1
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != str(CFG["chat_id"]):
            continue
        text = msg.get("text") or ""
        commands.append("check" if CHECK_RE.search(text) else "status" if STATUS_RE.search(text) else "help")
    return commands


def scan_due(state):
    return time.time() - state.get("last_scan", 0) >= CFG["scan_every_min"] * 60 or digest_due(state)


def fmt_when(ts):
    return datetime.fromtimestamp(ts, CFG["tz"]).strftime("%d.%m %H:%M") if ts else "ещё ни разу"


def scan_reply(summary):
    if summary is None:
        return "⚠️ Сходил, но сайт не ответил. Попробую ещё раз через 5 минут."
    pj = summary["projapan_only"]
    lines = [f"🔎 Сходил на motoauction и projapan: лотов Tracer в продаже — {summary['for_sale']}"
             + (" (projapan не ответил, только motoauction)." if pj is None else
                f", из них только на projapan — {pj}." if pj else ", все есть на motoauction.")]
    lines.append(f"Новых подходящих: <b>{len(summary['sent_now'])}</b> — прислал выше."
                 if summary["sent_now"] else "Новых подходящих нет.")
    if summary["open"]:
        lines.append("\nУже присылал, торги ещё впереди:")
        lines += [f"• {html.escape(l.get('model') or '')} {l.get('year')} · оценка {l.get('rank') or '?'}"
                  f" · торги {(l.get('auction_date') or '?')[:5]} — {' · '.join(urls)}" for l, urls in summary["open"]]
    return "\n".join(lines)


def status_reply(state):
    next_ts = state.get("last_scan", 0) + CFG["scan_every_min"] * 60
    return (f"Последняя проверка: {fmt_when(state.get('last_scan'))}. "
            f"Следующая: ~{fmt_when(max(next_ts, time.time()))}.\n"
            f"Присылал лотов за всё время: {len(state['lots'])}.")


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
    p.add_argument("--scan", action="store_true", help="сходить на сайт сейчас, не дожидаясь SCAN_EVERY_MIN")
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
        commands = [] if args.dry_run else poll_commands(tg, state)
        summary = None
        try:
            if args.dry_run or args.scan or "check" in commands or scan_due(state):
                summary = run_once(site, tg, state, include_finished=args.dry_run and args.all,
                                   verbose=args.dry_run)
                state["last_scan"] = int(time.time())
                note_site_ok(state, tg)
        except (OSError, ValueError) as e:  # сеть, HTTP-ошибки сайта, битый JSON
            # last_scan не сдвигается — следующий запуск через 5 минут попробует снова
            note_site_down(state, tg, e)
        finally:
            for cmd in dict.fromkeys(commands):  # «сходи» три раза подряд — один ответ
                tg.send(scan_reply(summary) if cmd == "check" else
                        status_reply(state) if cmd == "status" else HELP)
            # и после падения посреди прохода: уже отправленные лоты не должны прийти второй раз
            if not args.dry_run:
                save_state(state)
        if not args.loop:
            break
        time.sleep(args.loop)


if __name__ == "__main__":
    main()

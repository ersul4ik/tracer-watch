"""Fake sites and Telegram: whole passes without the network."""
from datetime import datetime, timedelta

from bot import scan
from bot.config import CFG, FOR_SALE, SOLD
from bot.telegram import Telegram

# The daily digest depends on the clock; tests that need it turn it back on
CFG["digest_hour"] = -1


def day(offset):
    return (datetime.now(CFG["tz"]) + timedelta(days=offset)).strftime("%d.%m.%Y")


def ts(offset):
    d = (datetime.now(CFG["tz"]) + timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(d.timestamp())


def lot(id, model="MT-09 TRACER GT", year=2019, rank=5.0, mileage=10000, price=600000,
        availability=FOR_SALE, date=3, frame=None, bid=None, auction="BDS"):
    return {"id": id, "brand": "Yamaha", "model": model, "year": year, "rank": rank, "mileage": mileage,
            "price": price, "availability": availability, "auction_date": day(date), "auction": auction,
            "bid": bid if bid is not None else id % 10000, "frame": frame or f"RN51J-{id:06d}",
            "pathImg": f"https://example.test/{id}.jpg", "AveragePrice": 0}


def archive(n=6, model="MT-09 TRACER GT", year=2019, rank=5.0, price=800000):
    """Similar sold lots, so that there is an estimate and it lands near price."""
    return [lot(900000 + i, model=model, year=year, rank=rank, mileage=10000, price=price,
                availability=SOLD, date=-10 - i) for i in range(n)]


class FakeSite:
    def __init__(self, current=(), sold=(), groups=("MT-09 TRACER GT",)):
        self.current = {l["id"]: l for l in current}
        self.sold = list(sold)
        self.groups = list(groups)

    def model_groups(self, brand):
        return self.groups

    def lots(self, brand, model, statistics=False):
        rows = self.sold if statistics else self.current.values()
        return [dict(l) for l in rows if l["model"] == model]

    def lot(self, lot_id):
        l = self.current.get(int(lot_id)) or next((x for x in self.sold if x["id"] == int(lot_id)), {})
        return {"price_start_jpy": l.get("price"), "price_finish_jpy": l.get("price"),
                "availability": l.get("availability"), "rank": l.get("rank"), "model_name": l.get("model"),
                "auction_line": f"{l.get('auction')} Kanto", "lot_number": str(l.get("bid")),
                "auction_date_ts": ts(3), "frame_number": l.get("frame"),
                "inspector_report": [{"title_ru": "Двигатель", "rank": 5, "comments": ["Окисление"]}]}


class FakeProJapan:
    """projapan with given lots (in the shape ProJapan._lot returns)."""
    lots_by_key = {}

    def lots(self):
        return {k: dict(v) for k, v in self.lots_by_key.items()}

    def enrich(self, lot):
        return lot["detail"]

    def result(self, key, frame):
        return {}


def pj_lot(id, same_as, **kw):
    """A projapan copy of same_as: the same auction, date and number."""
    base = lot(id, **kw)
    base.update(id=f"pj:{id}", site="projapan", url=f"https://projapan.ru/lot/{id}",
                auction=same_as["auction"], auction_date=same_as["auction_date"], bid=same_as["bid"])
    base["detail"] = {"price_start_jpy": base["price"], "frame_number": base["frame"],
                      "auction_line": base["auction"], "auction_date_ts": ts(3), "availability": base["availability"]}
    return base


class FakeTelegram(Telegram):
    def __init__(self):
        super().__init__("token", CFG["chat_id"] or "1")
        self.sent, self.updates = [], []

    def send(self, text, photo=None, button_url=None, reply_to=None):
        self.sent.append({"text": text, "reply_to": reply_to, "url": button_url})
        return 1000 + len(self.sent)

    def call(self, method, **params):
        assert method == "getUpdates"
        return self.updates


def use_projapan(lots_by_key=None):
    FakeProJapan.lots_by_key = lots_by_key or {}
    scan.ProJapan = FakeProJapan

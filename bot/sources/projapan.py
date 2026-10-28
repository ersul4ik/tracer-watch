"""projapan.ru, the second source: BDS and JBA lots that never reach motoauction."""
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime

from ..config import CFG, FOR_SALE, NOT_SOLD, SOLD, UA, fmt_num


class ProJapan:
    """projapan.ru: another storefront for Japanese bike auctions, with an open JSON API.

    It is here for BDS and JBA lots that never reach motoauction (five on 27.10, a 2020 GT
    starting at 550k among them). Searched by frame prefix: model names there are raw
    auction listings ("MT-09 TRE ｰｻｰGT"), while the frame is reliable.
    """
    BASE = "https://projapan.ru"
    AUCTIONS = {1: "BDS", 2: "JBA", 3: "ARAI", 4: "AUCNET"}
    STATUS = {(0, 0): FOR_SALE, (1, 1): SOLD, (1, 0): NOT_SOLD}
    NO_PRICE = (0, 99990000)  # "no start price yet"

    def _get(self, params, method="get-list"):
        url = f"{self.BASE}/api/lot/{method}?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        for attempt in range(2):  # projapan sometimes stalls for half a minute: one retry
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    d = json.load(r)
                break
            except OSError:
                if attempt:
                    raise
                time.sleep(5)
        time.sleep(1)  # someone else's site, go easy on it
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

    # Service fields of the inspection sheet, not notes
    NOT_NOTES = {"bid", "key", "horn", "lane", "year", "color", "meter", "frame_no", "displacement",
                 "engine_model", "registration", "starting_bid", "ranking_status", "genuine_parts",
                 "sales_data", "meter_pvi", "bds_comment"}

    # Fields whose text means nothing without the part's name ("Правая-under сильно" is an oil leak)
    NOTE_LABELS = {"oil_leak": "Течь масла", "tube_outer": "Вилка", "tube_inner": "Вилка",
                   "front_brake": "Передний тормоз", "rear_brake": "Задний тормоз",
                   "front_break": "Передний тормоз", "rear_break": "Задний тормоз",  # sic, that is how their data spells it
                   "front_tire": "Передняя покрышка", "rear_tire": "Задняя покрышка",
                   "front_wheel": "Переднее колесо", "rear_wheel": "Заднее колесо",
                   "rear_shock": "Задний амортизатор", "clutch": "Сцепление"}

    def enrich(self, lot):
        """Adds the inspection sheet to the lot's detail: the list lacks it, only the lot page has it.

        BDS notes come translated into Russian, JBA ones as raw Japanese fields, which are skipped
        (only text with Cyrillic is kept); section grades exist for both.
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
        """The lot's auction outcome: sold lots are in the archive (type=sold), searched by frame."""
        if not frame:
            return {}
        r = self._get({"lang": "ru", "limit": 100, "page": 1, "type": "sold", "filters[frame_number]": frame})
        for x in r["list"]:
            if f"pj:{x['id']}" == key:
                return self._lot(x)["detail"]
        return {}

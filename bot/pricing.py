"""Which lots qualify: limits, a mileage-adjusted price estimate from the sales archive, lot keys."""
import math
import re
from datetime import datetime, timedelta

from .config import CFG, FOR_SALE, NOT_SOLD, SOLD, fmt_jpy, fmt_num, log
from .sources.motoauction import SITE


def same_lot_key(lot):
    """The same lot on different sites: auction + auction date + lot number."""
    digits = re.sub(r"\D", "", str(lot.get("bid") or ""))
    auction = {"IAUC": "AUCNET"}.get(lot.get("auction"), lot.get("auction"))  # motoauction names AUCNET after its venue
    return f"{auction}|{lot.get('auction_date')}|{int(digits)}" if digits else None


def stats_model(name):
    """Model names differ between sites ("Tracer 900 GT" on projapan is "MT-09 TRACER GT")."""
    compact = re.sub(r"\s+|ABS", "", (name or "").upper()).replace("YAMAHA", "")
    if "900GT" in compact or compact == "MT-09TRACERGT":
        return "MT-09TRACERGT"
    if compact in ("MT-09TRACER", "TRACER900", "TRACKER900"):
        return "MT-09TRACER"
    return compact


class Stats:
    """What similar lots actually sold for, from the same site's sales archive for the past year.

    The site's own average is no good for this: ~1.07M for a 2019 GT against a median sale
    of 838k. The archive loads lazily, only once there is something to estimate.
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
                self.unsold.append(lot)  # for these, price is the last bid
        self.per_km = self._fit_mileage()
        log(f"sales archive: {len(self.sold)} sold in a year, {len(self.unsold)} unsold; "
            f"10,000 km takes {(1 - math.exp(-self.per_km * 10)) * 100:.0f}% off the price")

    def _fit_mileage(self):
        """How much cheaper a lot gets per 1,000 km: the slope of log price over mileage within
        model + year + grade groups. For 2018+ bikes it comes out at ~11% per 10,000 km: grade 5
        2021 GTs sold for 1.285M at 5,000 km, 910k at 30,000 and 600k at 70,000.
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
        # too little data or an odd slope: clamp to sane bounds rather than trust it
        return min(max(-sxy / sxx, 0.003), 0.02) if sxx else 0.008

    def not_sold(self):
        if self.unsold is None:
            self._load()
        return self.unsold

    def _at_mileage(self, sale, km):
        """A sold lot's price scaled to the mileage of the lot being judged. Without it a bike with
        40,000 km was measured against low-mileage ones and dismissed as "usually goes for 1.2M"."""
        if not km or not sale.get("mileage"):
            return sale["price"]
        factor = math.exp(self.per_km * (sale["mileage"] - km) / 1000)
        return int(round(sale["price"] * min(max(factor, 0.45), 1.6), -3))

    def estimate(self, lot):
        """Median final price of similar lots, or None with fewer than three of them.

        First the same model ±1 year and ±1 grade, then any grade, then ±2 years.
        Comparable prices are scaled to this lot's mileage.
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


def limit_for(rank):
    if rank is not None and rank >= CFG["top_rank"]:
        return CFG["top_limit"]
    return CFG["limit"]


def expected_price(lot, stats):
    """Expected final price: from the sales archive, or the site's average without one."""
    est = stats.estimate(lot) if stats else None
    return est["median"] if est else (lot.get("AveragePrice") or 0), est


def basic_reason(lot):
    """Model, year and grade: the checks that do not depend on price."""
    model = lot.get("model") or ""
    year = lot.get("year") or 0
    rank = lot.get("rank")
    if not CFG["model_re"].search(model):
        return f"модель {model}"
    # projapan lots may lack a year; they are found by frame, and the frame implies the years
    if year and year < CFG["min_year"]:
        return f"год {year}"
    # Grade 0 means not inspected yet; the grade usually shows up a couple of days before the auction.
    # Wait for it, but if the auction is tomorrow and there is still none, let the user look.
    if not rank:
        if days_to_auction(lot) > 1:
            return "оценки пока нет"
    elif rank < CFG["min_rank"]:
        return f"оценка {rank}"
    return None


def check(lot, stats=None):
    """None when the lot qualifies, otherwise the reason it does not (shown to the user).

    The limit is the final price. The start is only a floor for it; the median sale price of
    similar lots is what predicts it.
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
    """The last bid of an unsold lot if it was within the limit, otherwise 0.

    Such a lot is a chance: a buyer at our price existed and the seller said no. It can be
    haggled over after the auction, and relists often go cheaper (207900 went unsold at a
    628k bid and sold for 590k a week later).
    """
    bid = lot.get("price") or 0
    if lot.get("availability") == NOT_SOLD and 0 < bid <= limit_for(lot.get("rank")) and not basic_reason(lot):
        return bid
    return 0


def frame_key(lot):
    """The frame is the one thing that stays when a bike is relisted under a new lot number."""
    frame = lot.get("frame") or (lot.get("detail") or {}).get("frame_number") or ""
    if "*" in frame:  # masked by the site (RNA1J-000***): would lump different bikes together
        return None
    return re.sub(r"[^A-Z0-9]", "", frame.upper()) or None


def auction_day(lot):
    try:
        return datetime.strptime(lot.get("auction_date") or "", "%d.%m.%Y").date()
    except ValueError:
        return None


def days_to_auction(lot):
    day = auction_day(lot)
    if not day:
        return 0  # unknown date: assume the auction is close and do not wait
    return (day - datetime.now(CFG["tz"]).date()).days


def bike_id(lot):
    """What notes attach to: the bike, not the lot. The frame survives a relist and a copy on the other site."""
    return frame_key(lot) or same_lot_key(lot) or str(lot.get("id"))


def landed_usd(price):
    """Hammer price in yen to the full cost in dollars: the bike, the agent's fee and fixed costs."""
    return round(price / CFG["jpy_per_usd"] * (1 + CFG["fee_ratio"]) + CFG["fixed_usd"])


def suggested_bid(limit, est):
    """No point bidding far above what similar lots go for: 5% over the median, rounded up to 10k,
    but never over the limit."""
    if not est:
        return limit
    return min(limit, -(-int(est["median"] * 1.05) // 10_000) * 10_000)

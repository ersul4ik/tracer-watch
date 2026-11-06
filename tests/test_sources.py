import unittest
import unittest.mock
from datetime import timedelta, timezone

from bot.config import CFG, FOR_SALE, SOLD
from bot.export import lot_row
from bot.messages import auction_time
from bot.sources.motoauction import Site
from bot.sources.projapan import ProJapan


class Paging(unittest.TestCase):
    def fake(self, total, cap, has_more=True):
        site = Site()
        calls = []

        def get(path, params=None, auth=True):
            calls.append(params["offset"])
            ids = range(params["offset"], min(params["offset"] + min(params["limit"], cap), total))
            d = {"lots": {str(i): {"id": i} for i in ids}}
            if has_more:
                d["has_more"] = params["offset"] + len(ids) < total
            return d

        site._get = get
        return site, calls

    def test_follows_a_capped_page_size(self):
        site, calls = self.fake(total=96, cap=50)
        self.assertEqual(len(site.lots("Suzuki", "X")), 96)
        self.assertEqual(calls, [0, 50])

    def test_without_has_more_reads_until_an_empty_page(self):
        site, calls = self.fake(total=120, cap=50, has_more=False)
        self.assertEqual(len(site.lots("Suzuki", "X")), 120)
        self.assertEqual(calls, [0, 50, 100, 120])


class ProJapanStart(unittest.TestCase):
    def test_placeholder_start_means_unknown(self):
        pj = ProJapan()
        raw = {"id": 1, "auction_date": "2026-11-06 00:00:00", "parser_type": 2, "auction_status": 0, "sold_status": 0}
        for placeholder in (88_888_000, 99_990_000, 9_999_000):
            self.assertEqual(pj._lot({**raw, "price_start": placeholder})["price"], 0)
        self.assertEqual(pj._lot({**raw, "price_start": 600_000})["price"], 600_000)

    def test_jba_sheet_brings_reserve_start_and_time(self):
        pj = ProJapan()
        raw = {"id": 1, "auction_date": "2026-11-06 00:00:00", "parser_type": 2, "auction_status": 0,
               "sold_status": 0, "price_start": 99_990_000}
        meta = {"売切価格": "700", "スタート価格": "600", "セリ予定時刻": "2026-11-06 11:50:34"}
        pj._get = lambda params, method: {"metadata_ru": meta, "rank": 4}
        lot = pj._lot(raw)
        detail = pj.enrich(lot)
        self.assertEqual((detail["reserve_jpy"], detail["price_start_jpy"], lot["price"]), (700_000, 600_000, 600_000))
        self.assertEqual(detail["auction_time_jst"], "11:50")
        with unittest.mock.patch.dict(CFG, {"tz": timezone(timedelta(hours=6))}):
            self.assertEqual(auction_time(detail), " в 11:50 по Японии (08:50 у нас)")
        # not set yet: JBA shows 99990 (thousands) in both
        meta.update({"売切価格": "99990", "スタート価格": "99990"})
        detail = pj.enrich(pj._lot(raw))
        self.assertEqual((detail["reserve_jpy"], detail["price_start_jpy"]), (0, 0))

    def test_sold_lot_is_stored_with_the_hammer_price_not_the_start(self):
        # JBA lot 7149 on 06.11.2026: start 730k, sold for 812k
        raw = {"id": 2290763, "auction_date": "2026-11-06 00:00:00", "parser_type": 2, "auction_status": 1,
               "sold_status": 1, "price_start": 730_000, "price_end": 812_000}
        row = lot_row(ProJapan()._lot(raw))
        self.assertEqual((row["availability"], row["start"], row["final"]), (SOLD, 730_000, 812_000))
        # motoauction's archive rows carry the sale price in price alone
        self.assertEqual(lot_row({"id": 1, "price": 812_000, "availability": SOLD})["final"], 812_000)
        self.assertIsNone(lot_row({"id": 2, "price": 730_000, "availability": FOR_SALE})["final"])


if __name__ == "__main__":
    unittest.main()

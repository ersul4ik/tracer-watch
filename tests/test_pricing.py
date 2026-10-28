import unittest

from bot.config import CFG, NOT_SOLD, SOLD
from bot.pricing import (Stats, bike_id, check, frame_key, limit_for, same_lot_key, stats_model,
                         unsold_bid)
from tests.fakes import FakeSite, archive, lot


class Keys(unittest.TestCase):
    def test_same_lot_key_matches_aucnet_names(self):
        a = {"auction": "IAUC", "auction_date": "01.11.2026", "bid": "0402"}
        b = {"auction": "AUCNET", "auction_date": "01.11.2026", "bid": 402}
        self.assertEqual(same_lot_key(a), same_lot_key(b))

    def test_frame_key_ignores_punctuation(self):
        self.assertEqual(frame_key({"frame": "rn51j-003241"}), "RN51J003241")
        self.assertEqual(frame_key({"detail": {"frame_number": "RN51J 003241"}}), "RN51J003241")
        self.assertIsNone(frame_key({}))
        self.assertIsNone(frame_key({"frame": "RNA1J-000***"}))  # masked: not an identity

    def test_bike_id_prefers_frame(self):
        self.assertEqual(bike_id(lot(5, frame="RN51J-000005")), "RN51J000005")
        self.assertEqual(bike_id({"id": 7, "auction": "BDS", "auction_date": "01.11.2026", "bid": 3}), "BDS|01.11.2026|3")

    def test_stats_model_joins_site_names(self):
        self.assertEqual(stats_model("Tracer 900 GT"), stats_model("MT-09 TRACER GT"))
        self.assertEqual(stats_model("TRACER 900"), stats_model("MT-09 TRACER"))


class Limits(unittest.TestCase):
    def test_top_rank_raises_limit(self):
        self.assertEqual(limit_for(4), CFG["limit"])
        self.assertEqual(limit_for(CFG["top_rank"]), CFG["top_limit"])
        self.assertEqual(limit_for(None), CFG["limit"])


class Estimate(unittest.TestCase):
    def setUp(self):
        sold = [lot(800 + i, mileage=km, price=p, availability=SOLD, date=-5 - i)
                for i, (km, p) in enumerate([(5000, 1_000_000), (5000, 980_000), (30000, 760_000),
                                             (30000, 740_000), (60000, 540_000), (60000, 520_000)])]
        self.stats = Stats(FakeSite(sold=sold), ["MT-09 TRACER GT"])

    def test_price_falls_with_mileage(self):
        low = self.stats.estimate(lot(1, mileage=5000))["median"]
        high = self.stats.estimate(lot(2, mileage=60000))["median"]
        self.assertGreater(low, 900_000)
        self.assertLess(high, 600_000)
        self.assertIn("в пересчёте", self.stats.estimate(lot(3, mileage=30000))["scope"])

    def test_leaves_the_lot_itself_out(self):
        est = self.stats.estimate(lot(800, mileage=5000))
        self.assertEqual(est["n"], 5)


class Check(unittest.TestCase):
    def setUp(self):
        self.stats = Stats(FakeSite(sold=archive(price=CFG["limit"])), ["MT-09 TRACER GT"])

    def test_fits(self):
        self.assertIsNone(check(lot(1, price=CFG["limit"] - 100_000), self.stats))

    def test_reasons(self):
        self.assertIn("год", check(lot(1, year=CFG["min_year"] - 1), self.stats))
        self.assertIn("оценка", check(lot(1, rank=CFG["min_rank"] - 0.5), self.stats))
        self.assertEqual(check(lot(1, rank=0, date=5), self.stats), "оценки пока нет")
        self.assertIsNone(check(lot(1, rank=0, date=1), self.stats))  # auction tomorrow: send without a grade
        self.assertIn("модель", check(lot(1, model="MT-09"), self.stats))

    def test_start_near_limit_still_fits(self):
        near = int(CFG["limit"] * (CFG["near_ratio"] - 0.02))
        self.assertIsNone(check(lot(1, price=near), self.stats))
        far = int(CFG["limit"] * (CFG["near_ratio"] + 0.05))
        self.assertIn("выше лимита", check(lot(1, price=far), self.stats))

    def test_usually_pricier(self):
        stats = Stats(FakeSite(sold=archive(price=int(CFG["limit"] * CFG["expect_ratio"] * 1.2))), ["MT-09 TRACER GT"])
        self.assertIn("обычно уходят", check(lot(1, price=500_000), stats))


class Unsold(unittest.TestCase):
    def test_bid_within_limit(self):
        self.assertEqual(unsold_bid(lot(1, availability=NOT_SOLD, price=600_000, date=-1)), 600_000)
        self.assertEqual(unsold_bid(lot(1, availability=NOT_SOLD, price=CFG["top_limit"] + 1, date=-1)), 0)
        self.assertEqual(unsold_bid(lot(1, availability=SOLD, price=600_000, date=-1)), 0)
        self.assertEqual(unsold_bid(lot(1, availability=NOT_SOLD, price=600_000, year=2015, date=-1)), 0)


if __name__ == "__main__":
    unittest.main()

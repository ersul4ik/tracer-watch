"""Bid advice, finer serious-note detection, relists of any unsold bike, auction reminders, crash alerts."""
import time
import unittest.mock
import unittest

from bot.config import CFG, NOT_SOLD
from bot.db import Store
from bot.messages import is_serious
from bot.pricing import landed_usd, suggested_bid
from bot.scan import auctions_soon, note_site_down, run_once
from tests.fakes import FakeSite, FakeTelegram, archive, lot, ts, use_projapan


class Budget(unittest.TestCase):
    def test_landed_cost_matches_the_budget_maths(self):
        # 775k: 5000 $ + 10% + 3500 fixed = 9000 $
        with unittest.mock.patch.dict(CFG, {"jpy_per_usd": 155, "fee_ratio": 0.10, "fixed_usd": 3500}):
            self.assertEqual(landed_usd(775_000), 9000)

    def test_suggested_bid_stays_near_the_median_and_under_the_limit(self):
        self.assertEqual(suggested_bid(750_000, {"median": 640_000}), 680_000)
        self.assertEqual(suggested_bid(750_000, {"median": 900_000}), 750_000)
        self.assertEqual(suggested_bid(750_000, None), 750_000)


class Serious(unittest.TestCase):
    def test_slight_issues_are_not_repairs(self):
        self.assertFalse(is_serious("• Передняя часть (5): Внешняя окисление, Незначительно, Утечка масла, Незначительно"))
        self.assertTrue(is_serious("• Двигатель (3): Окисление двигателя; Шум сцепления Уровень 3"))
        self.assertTrue(is_serious("• Сальник вилки треснувший"))
        self.assertTrue(is_serious("• Задняя часть: Утечка масла, Незначительно; Требуется замена тормозного диска."))


class RelistOfAnyUnsold(unittest.TestCase):
    def test_bike_unsold_above_the_limit_comes_back_cheaper(self):
        use_projapan()
        store, tg = Store(), FakeTelegram()
        unsold = lot(600, price=CFG["limit"] + 50_000, availability=NOT_SOLD, date=-7)  # seller refused more than our limit
        sold = archive(price=int(CFG["limit"] * CFG["expect_ratio"] * 1.3))  # forecast alone would filter it
        again = lot(601, price=CFG["limit"] - 100_000, frame=unsold["frame"], date=3)
        run_once(FakeSite(current=[again], sold=sold + [unsold]), tg, store)
        self.assertEqual(len(tg.sent), 1)
        self.assertIn("Снова на торгах", tg.sent[0]["text"])

    def test_relist_with_a_high_start_is_skipped(self):
        use_projapan()
        store, tg = Store(), FakeTelegram()
        unsold = lot(600, price=CFG["limit"] + 50_000, availability=NOT_SOLD, date=-7)
        again = lot(601, price=int(CFG["limit"] * CFG["near_ratio"]) + 10_000, frame=unsold["frame"], date=3)
        run_once(FakeSite(current=[again], sold=archive() + [unsold]), tg, store)
        self.assertEqual(tg.sent, [])


class Reminders(unittest.TestCase):
    def test_lists_sent_lots_with_auctions_today_and_tomorrow(self):
        state = {"lots": {
            "1": {"date_ts": ts(0), "title": "A", "url": "u1", "same": "s1"},
            "pj:1": {"date_ts": ts(0), "title": "A copy", "url": "u2", "same": "s1"},  # same lot, other site
            "2": {"date_ts": ts(1), "title": "B", "url": "u3"},
            "3": {"date_ts": ts(3), "title": "C", "url": "u4"},
            "4": {"date_ts": ts(0), "title": "D", "url": "u5", "done": True},
        }}
        lines = auctions_soon(state)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("• сегодня: A"))
        self.assertTrue(lines[1].startswith("• завтра: B"))


class CrashAlert(unittest.TestCase):
    def test_bug_is_reported_once_after_the_grace_period(self):
        tg, state = FakeTelegram(), {"fail_since": int(time.time()) - 31 * 60, "alerted": False}
        note_site_down(state, tg, KeyError("x"))
        note_site_down(state, tg, KeyError("x"))
        self.assertEqual(len(tg.sent), 1)
        self.assertIn("падает с ошибкой", tg.sent[0]["text"])


if __name__ == "__main__":
    unittest.main()

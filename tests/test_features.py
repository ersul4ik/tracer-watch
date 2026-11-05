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

    def test_finding_shares_a_line_with_a_slight_one(self):
        # projapan's comma-separated lines from BDS lot 2637 (06.11.2026)
        self.assertTrue(is_serious("• Задний тормоз: Break незначительная ржавчина, Тормозной диск износ требует замены"))
        self.assertTrue(is_serious("• Задний амортизатор: Амортизатор незначительная ржавчина Подтек масла слабо"))
        self.assertTrue(is_serious("• Вилка: Сальник повреждено"))
        self.assertTrue(is_serious("• Fog-lamp необходима замена"))
        self.assertFalse(is_serious("• Подножка мотоцикла незначительная ржавчина Treatment слабо"))
        self.assertFalse(is_serious("• Глушитель царапины слабо неоригинальная деталь, Крышка царапины"))


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


class SellerReserve(unittest.TestCase):
    def test_reserve_is_reported_once_it_shows_up_and_on_every_change(self):
        from tests.fakes import pj_lot
        store, tg = Store(), FakeTelegram()
        site = FakeSite(current=[], sold=archive(price=CFG["limit"]))
        pj = pj_lot(5, lot(1, auction="JBA"), price=CFG["limit"] - 100_000)
        use_projapan({"pj:5": pj})
        run_once(site, tg, store)
        self.assertEqual(len(tg.sent), 1)
        self.assertNotIn("Резерв", tg.sent[0]["text"])
        run_once(site, tg, store)
        self.assertEqual(len(tg.sent), 1)  # still no reserve: nothing to say

        pj["detail"]["reserve_jpy"] = 700_000
        run_once(site, tg, store)
        run_once(site, tg, store)
        self.assertEqual(len(tg.sent), 2)
        self.assertIn("Продавец показал резерв", tg.sent[1]["text"])
        self.assertIn("700 000", tg.sent[1]["text"])
        self.assertEqual(tg.sent[1]["reply_to"], 1001)

        pj["detail"]["reserve_jpy"] = CFG["limit"] + 10_000
        run_once(site, tg, store)
        self.assertEqual(len(tg.sent), 3)
        self.assertIn("изменил резерв: было 700 000", tg.sent[2]["text"])
        self.assertIn("выше нашего лимита", tg.sent[2]["text"])

    def test_reserve_known_when_sent_is_not_repeated(self):
        from tests.fakes import pj_lot
        store, tg = Store(), FakeTelegram()
        site = FakeSite(current=[], sold=archive(price=CFG["limit"]))
        pj = pj_lot(5, lot(1, auction="JBA"), price=CFG["limit"] - 100_000)
        pj["detail"]["reserve_jpy"] = 700_000
        use_projapan({"pj:5": pj})
        run_once(site, tg, store)
        run_once(site, tg, store)
        self.assertEqual(len(tg.sent), 1)
        self.assertIn("Резерв продавца: <b>700 000", tg.sent[0]["text"])


class MotoauctionDown(unittest.TestCase):
    class DownSite:
        def model_groups(self, brand):
            raise OSError("Temporary failure in name resolution")

        def lots(self, *a, **k):
            raise OSError("down")

        def lot(self, *a):
            raise OSError("down")

    def test_pass_goes_on_with_projapan_and_the_stored_archive(self):
        from tests.fakes import pj_lot
        store, tg = Store(), FakeTelegram()
        # an earlier pass stored the archive
        use_projapan()
        run_once(FakeSite(current=[], sold=archive(price=CFG["limit"])), tg, store)
        self.assertEqual(len(store.archive_rows()), 6)
        ma = lot(1, price=CFG["limit"] - 100_000)
        use_projapan({"pj:5": pj_lot(5, ma, price=CFG["limit"] - 100_000)})
        summary = run_once(self.DownSite(), tg, store)
        self.assertEqual(len(tg.sent), 1)
        self.assertIn("projapan", tg.sent[0]["text"])
        self.assertIn("Обычно уходят", tg.sent[0]["text"])  # estimate from the stored archive
        self.assertEqual(summary["for_sale"], 1)
        self.assertTrue(store.state["ma_down_since"])

    def test_both_down_fails_the_pass(self):
        class DownProJapan:
            def lots(self):
                raise OSError("down too")
        from bot import scan
        scan.ProJapan = DownProJapan
        with self.assertRaises(OSError):
            run_once(self.DownSite(), FakeTelegram(), Store())


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

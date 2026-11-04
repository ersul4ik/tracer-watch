import unittest

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


if __name__ == "__main__":
    unittest.main()

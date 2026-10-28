import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from bot.db import Store

OLD_STATE = {
    "lots": {
        "237878": {"at": 1793088403, "msg": 12, "date_ts": 1793134800, "done": False, "graded": True,
                   "same": "BDS|28.10.2026|589"},
        "pj:2284586": {"at": 1793000000, "msg": 9, "date_ts": 1793134800, "done": False, "graded": True,
                       "same": "BDS|28.10.2026|589", "frame": "RN51J-003241"},
        "225792": {"at": 1792000000, "msg": 5, "date_ts": 1792702800, "done": True, "graded": True,
                   "unsold": 590000, "result": {"sold": False, "price": 590000}},
    },
    "skipped": {"236282": {"at": 1793010921, "line": "MT-09 TRACER GT 2020 · оценка 5.0 · торги 30.10 — старт выше"}},
    "tg_offset": 555, "last_scan": 1793100000, "digest_day": "2026-10-27", "digest_at": 1793000000,
    "fail_since": None, "alerted": False,
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Import(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        legacy = self.dir / "state.json"
        legacy.write_text(json.dumps(OLD_STATE))
        self.db = self.dir / "tracer.db"
        Store.open(self.db, legacy=legacy).close()

    def test_keeps_every_sent_lot_and_field(self):
        state = Store.open(self.db).state
        self.assertEqual(set(state["lots"]), set(OLD_STATE["lots"]))
        for key, old in OLD_STATE["lots"].items():
            for field, value in old.items():
                self.assertEqual(state["lots"][key][field], value, (key, field))
        self.assertEqual(state["tg_offset"], 555)
        self.assertEqual(state["digest_at"], 1793000000)

    def test_skipped_lines_reach_the_digest(self):
        store = Store.open(self.db)
        self.assertEqual(store.new_skipped_since(0), [OLD_STATE["skipped"]["236282"]["line"]])
        self.assertEqual(store.new_skipped_since(1793010921), [])

    def test_untouched_state_does_not_rewrite_the_file(self):
        before = digest(self.db)
        store = Store.open(self.db)
        store.save()
        store.close()
        self.assertEqual(digest(self.db), before)

    def test_changed_state_is_saved(self):
        store = Store.open(self.db)
        store.state["lots"]["237878"]["done"] = True
        store.state["lots"]["1"] = {"at": 1, "msg": 2, "done": False, "graded": False, "relist_of": "225792"}
        store.save()
        store.close()
        state = Store.open(self.db).state
        self.assertTrue(state["lots"]["237878"]["done"])
        self.assertFalse(state["lots"]["1"]["graded"])
        kinds = dict(Store.open(self.db).conn.execute("SELECT key, kind FROM sent").fetchall())
        self.assertEqual((kinds["1"], kinds["225792"], kinds["237878"]), ("relist", "unsold", "alert"))


class Lots(unittest.TestCase):
    def test_first_seen_stays(self):
        store = Store()
        row = {"key": "1", "model": "MT-09 TRACER", "year": 2018, "rank": 4, "availability": 0,
               "auction_date": "30.10.2026"}
        store.record_lot(row, 100, reason="старт выше лимита", with_reason=True)
        store.record_lot(dict(row, rank=5), 200, reason="старт выше лимита", with_reason=True)
        r = store.conn.execute("SELECT first_seen, last_seen, rank FROM lots").fetchone()
        self.assertEqual(tuple(r), (100, 200, 5))
        self.assertEqual(store.new_skipped_since(50), ["MT-09 TRACER 2018 · оценка 5.0 · торги 30.10 — старт выше лимита"])

    def test_sent_lot_is_not_skipped(self):
        store = Store()
        store.record_lot({"key": "1", "availability": 0}, 100, reason="x", with_reason=True)
        store.state["lots"]["1"] = {"at": 100, "msg": 1}
        store.save()
        self.assertEqual(store.new_skipped_since(0), [])

    def test_archive_row_keeps_reason(self):
        store = Store()
        store.record_lot({"key": "1", "availability": 0}, 100, reason="x", with_reason=True)
        store.record_lot({"key": "1", "availability": 1, "final": 700000}, 200)
        r = store.conn.execute("SELECT last_reason, final FROM lots").fetchone()
        self.assertEqual(tuple(r), ("x", 700000))


class Notes(unittest.TestCase):
    def test_add_list_delete(self):
        store = Store()
        a = store.add_note("RN51J003241", "price", "дорого для 42 тыс. км", now=1)
        store.add_note("RN51J003241", "", "посмотреть фото вилки", source="telegram", now=2)
        store.add_note("OTHER", "like", now=3)
        self.assertEqual([n["text"] for n in store.notes_for("RN51J003241")],
                         ["дорого для 42 тыс. км", "посмотреть фото вилки"])
        self.assertEqual(set(store.all_notes()), {"RN51J003241", "OTHER"})
        store.delete_note(a)
        self.assertEqual(len(store.notes_for("RN51J003241")), 1)
        self.assertEqual(store.notes_for(None), [])


if __name__ == "__main__":
    unittest.main()

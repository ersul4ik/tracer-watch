"""Whole passes against fake sites: what gets sent, what does not get sent twice."""
import unittest

from bot import main as cli
from bot.config import CFG, NOT_SOLD, SOLD
from bot.db import Store
from bot.export import build_board
from bot.scan import run_once
from bot.telegram import poll_commands
from tests.fakes import FakeSite, FakeTelegram, archive, lot, pj_lot, use_projapan

CHEAP = CFG["limit"] - 100_000


class Sending(unittest.TestCase):
    def setUp(self):
        use_projapan()
        self.store, self.tg = Store(), FakeTelegram()

    def run_pass(self, site):
        return run_once(site, self.tg, self.store)

    def test_matching_lot_is_sent_once(self):
        site = FakeSite(current=[lot(1, price=CHEAP)], sold=archive(price=CFG["limit"]))
        self.run_pass(site)
        self.assertEqual(len(self.tg.sent), 1)
        self.assertIn("MT-09 TRACER GT", self.tg.sent[0]["text"])
        self.run_pass(site)
        self.assertEqual(len(self.tg.sent), 1)
        entry = self.store.state["lots"]["1"]
        self.assertEqual(entry["bike"], "RN51J000001")
        self.assertEqual(entry["msg"], 1001)

    def test_copy_on_projapan_is_not_sent_again(self):
        ma = lot(1, price=CHEAP)
        use_projapan({"pj:77": pj_lot(77, ma, price=CHEAP)})
        # projapan listed it first
        self.run_pass(FakeSite(current=[], sold=archive(price=CFG["limit"])))
        self.assertEqual(len(self.tg.sent), 1)
        self.assertIn("projapan", self.tg.sent[0]["text"])
        # then motoauction added the same lot
        self.run_pass(FakeSite(current=[ma], sold=archive(price=CFG["limit"])))
        self.assertEqual(len(self.tg.sent), 1)

    def test_skipped_lot_goes_to_the_digest_store(self):
        site = FakeSite(current=[lot(1, price=CHEAP, year=CFG["min_year"] - 1)], sold=archive())
        self.store.state["lots_seeded"] = True  # not the first pass with the db
        self.run_pass(site)
        self.assertEqual(self.tg.sent, [])
        lines = self.store.new_skipped_since(0)
        self.assertEqual(len(lines), 1)
        self.assertIn("год", lines[0])

    def test_first_pass_with_db_does_not_flood_the_digest(self):
        site = FakeSite(current=[lot(1, price=CHEAP, year=CFG["min_year"] - 1)], sold=archive())
        self.run_pass(site)
        self.assertEqual(self.store.new_skipped_since(0), [])

    def test_note_shows_in_the_alert(self):
        self.store.add_note("RN51J000001", "price", "дорого")
        self.run_pass(FakeSite(current=[lot(1, price=CHEAP)], sold=archive(price=CFG["limit"])))
        self.assertIn("Твои метки", self.tg.sent[0]["text"])
        self.assertIn("дорого", self.tg.sent[0]["text"])


class UnsoldAndRelist(unittest.TestCase):
    def setUp(self):
        use_projapan()
        self.store, self.tg = Store(), FakeTelegram()
        self.unsold = lot(500, price=CFG["limit"] - 50_000, availability=NOT_SOLD, date=-1)
        self.sold = archive(price=int(CFG["limit"] * CFG["expect_ratio"] * 1.2))  # usually far pricier

    def test_unsold_within_limit_is_sent_then_relist_replies_to_it(self):
        run_once(FakeSite(current=[], sold=self.sold + [self.unsold]), self.tg, self.store)
        self.assertEqual(len(self.tg.sent), 1)
        self.assertIn("Не продан", self.tg.sent[0]["text"])
        first_msg = self.store.state["lots"]["500"]["msg"]

        again = lot(501, price=CHEAP, frame=self.unsold["frame"], date=4)
        run_once(FakeSite(current=[again], sold=self.sold + [self.unsold]), self.tg, self.store)
        self.assertEqual(len(self.tg.sent), 2)
        self.assertIn("Снова на торгах", self.tg.sent[1]["text"])
        self.assertEqual(self.tg.sent[1]["reply_to"], first_msg)
        self.assertEqual(self.store.state["lots"]["501"]["relist_of"], "500")

    def test_old_unsold_is_not_sent(self):
        old = dict(self.unsold, auction_date=lot(1, date=-5)["auction_date"])
        run_once(FakeSite(current=[], sold=self.sold + [old]), self.tg, self.store)
        self.assertEqual(self.tg.sent, [])


class Results(unittest.TestCase):
    def test_result_reply_after_the_auction(self):
        use_projapan()
        store, tg = Store(), FakeTelegram()
        l1 = lot(1, price=CHEAP)
        site = FakeSite(current=[l1], sold=archive(price=CFG["limit"]))
        run_once(site, tg, store)
        store.state["lots"]["1"]["date_ts"] = 1  # the auction day has passed
        site.current = {}
        site.sold.append(dict(l1, availability=SOLD, price=CHEAP + 10_000))
        run_once(site, tg, store)
        self.assertIn("Продан за", tg.sent[-1]["text"])
        self.assertEqual(store.state["lots"]["1"]["result"], {"sold": True, "price": CHEAP + 10_000})
        self.assertTrue(store.state["lots"]["1"]["done"])


class Crashes(unittest.TestCase):
    def test_failed_reply_does_not_lose_the_pass(self):
        """Telegram refusing a command reply must not undo the record of lots already sent."""
        import tempfile
        from pathlib import Path
        from unittest import mock
        d = Path(tempfile.mkdtemp())
        use_projapan()
        tg = FakeTelegram()
        chat = {"id": int(tg.chat_id)}
        tg.updates = [{"update_id": 1, "message": {"chat": chat, "text": "/status"}}]
        real_send = tg.send

        def send(text, photo=None, button_url=None, reply_to=None):
            if text.startswith("Последняя проверка"):
                raise RuntimeError("Telegram sendMessage: 429")
            return real_send(text, photo, button_url, reply_to)

        tg.send = send
        site = FakeSite(current=[lot(1, price=CHEAP)], sold=archive(price=CFG["limit"]))
        with mock.patch.dict(CFG, {"db": d / "tracer.db", "state": d / "none.json", "token": "x", "chat_id": tg.chat_id}), \
                mock.patch.object(cli, "Telegram", lambda *a, **k: tg), \
                mock.patch.object(cli, "Site", lambda: site), \
                mock.patch("sys.argv", ["bot", "--scan"]):
            cli.main()
        state = Store.open(d / "tracer.db").state
        self.assertIn("1", state["lots"])
        self.assertEqual(state["tg_offset"], 2)

    def test_dry_run_note_is_refused(self):
        from unittest import mock
        with mock.patch("sys.argv", ["bot", "--dry-run", "--note", "X", "--tag", "seen"]):
            with self.assertRaises(SystemExit):
                cli.main()


class DigestCopies(unittest.TestCase):
    def test_copy_of_a_sent_lot_is_not_listed_as_skipped(self):
        ma = lot(1, price=int(CFG["limit"] * 2))  # motoauction copy would be skipped on price
        use_projapan({"pj:77": pj_lot(77, ma, price=CHEAP)})
        store, tg = Store(), FakeTelegram()
        store.state["lots_seeded"] = True
        run_once(FakeSite(current=[], sold=archive(price=CFG["limit"])), tg, store)
        self.assertEqual(len(tg.sent), 1)
        run_once(FakeSite(current=[ma], sold=archive(price=CFG["limit"])), tg, store)
        self.assertEqual(store.new_skipped_since(0), [])


class Board(unittest.TestCase):
    def test_board_has_everything_the_page_reads(self):
        use_projapan()
        store, tg = Store(), FakeTelegram()
        site = FakeSite(current=[lot(1, price=CHEAP), lot(2, year=2015)], sold=archive(price=CFG["limit"]))
        store.add_note("RN51J000002", "seen", "старый")
        board = build_board(run_once(site, tg, store)["board"], store)
        self.assertEqual(board["counts"]["for_sale"], 2)
        self.assertEqual(board["counts"]["matching"], 1)
        fits = next(l for l in board["lots"] if l["key"] == "1")
        self.assertTrue(fits["sent"])
        self.assertIsNotNone(fits["estimate"])
        self.assertEqual(fits["links"][0]["site"], "motoauction")
        self.assertIn("RN51J000002", board["notes"])
        self.assertTrue(board["archive"])
        self.assertEqual(board["history"][0]["key"], "1")


class TelegramNotes(unittest.TestCase):
    def test_reply_to_an_alert_becomes_a_note(self):
        use_projapan()
        store, tg = Store(), FakeTelegram()
        run_once(FakeSite(current=[lot(1, price=CHEAP)], sold=archive(price=CFG["limit"])), tg, store)
        msg = store.state["lots"]["1"]["msg"]
        chat = {"id": int(tg.chat_id)}
        tg.updates = [
            {"update_id": 10, "message": {"chat": chat, "text": "дорого, пропускаем", "reply_to_message": {"message_id": msg}}},
            {"update_id": 11, "message": {"chat": chat, "text": "сходи посмотри"}},
            {"update_id": 12, "message": {"chat": {"id": 999}, "text": "чужой"}},
        ]
        commands = poll_commands(tg, store.state)
        self.assertEqual([c["cmd"] for c in commands], ["note", "check"])
        self.assertEqual(store.state["tg_offset"], 13)
        self.assertIn("Записал метку", cli.note_from_reply(store, commands[0]))
        self.assertEqual(store.notes_for("RN51J000001")[0]["text"], "дорого, пропускаем")

    def test_command_sent_as_a_reply_is_still_a_command(self):
        tg = FakeTelegram()
        chat = {"id": int(tg.chat_id)}
        texts = ["сходи посмотри", "Посмотри!", "/status", "статус", "посмотрел, дорого"]
        tg.updates = [{"update_id": i, "message": {"chat": chat, "text": t, "reply_to_message": {"message_id": 5}}}
                      for i, t in enumerate(texts)]
        self.assertEqual([c["cmd"] for c in poll_commands(tg, {})], ["check", "check", "status", "status", "note"])

    def test_resent_note_is_stored_once(self):
        store = Store()
        cli.add_note(store, "RN51J000001", "price", "дорого", source="web")
        cli.add_note(store, "RN51J000001", "price", "дорого", source="web")
        self.assertEqual(len(store.notes_for("RN51J000001")), 1)

    def test_cli_note_validation(self):
        store = Store()
        cli.add_note(store, "RN51J000001", "price", "")
        with self.assertRaises(ValueError):
            cli.add_note(store, "RN51J000001", "nonsense", "")
        with self.assertRaises(ValueError):
            cli.add_note(store, "bad id with spaces", "price", "")
        note_id = store.notes_for("RN51J000001")[0]["id"]
        cli.add_note(store, "RN51J000001", "delete", str(note_id))
        self.assertEqual(store.notes_for("RN51J000001"), [])


if __name__ == "__main__":
    unittest.main()

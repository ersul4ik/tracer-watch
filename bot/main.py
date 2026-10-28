"""Watches Japanese motorcycle auctions and sends matching Yamaha Tracer lots to Telegram.

Usage:
    python -m bot              # one pass (how GitHub Actions runs it)
    python -m bot --loop 300   # keep running, one pass every 5 minutes
    python -m bot --dry-run    # send and store nothing, print what would be sent
    python -m bot --dry-run --all  # the same, including lots already sold (backtest)
    python -m bot --dry-run --board board.json  # and write the web page data to a file
    python -m bot --note RN51J003241 --tag price --text "too pricey"  # a note on a bike
    python -m bot --whoami     # print the chat_id of whoever messaged the bot
    python -m bot --test       # send a test message
"""
import argparse
import html
import re
import sys
import time

from .config import CFG, log
from .db import Store
from .export import build_board, refresh_notes, write_board
from .messages import TAGS, scan_reply, status_reply
from .scan import note_site_down, note_site_ok, run_once, scan_due
from .sources.motoauction import Site
from .telegram import HELP, Telegram, poll_commands, whoami


def board_path():
    return CFG["db"].parent / "board.json"


def add_note(store, bike, tag, text, lot_key=None, source="cli"):
    """A note from the web page or the command line. Tag "delete" removes the note whose id is in text."""
    bike = (bike or "").strip()
    if not re.fullmatch(r"[\w|.:-]{1,64}", bike):
        raise ValueError(f"bad bike id: {bike!r}")
    if tag == "delete":
        removed = store.delete_note(int(text))
        log(f"note {text} on {bike}: removed {removed}")
        return
    if tag and tag not in TAGS:
        raise ValueError(f"unknown tag: {tag!r}")
    if not tag and not (text or "").strip():
        raise ValueError("empty note")
    note_id = store.add_note(bike, tag, (text or "")[:500], lot_key=lot_key, source=source)
    log(f"note {note_id} on {bike}: {tag} {text}")


def note_from_reply(store, tg, cmd):
    """A reply to a lot alert becomes a note on that bike."""
    found = next(((k, e) for k, e in store.state["lots"].items() if e.get("msg") == cmd["reply_to"]), None)
    if not found:
        tg.send("Не понял, к какому лоту это. Ответь на моё сообщение с лотом — запишу как метку.",
                reply_to=cmd["reply_to"])
        return False
    key, entry = found
    store.add_note(entry.get("bike") or key, "", cmd["text"][:500], lot_key=key, source="telegram")
    tg.send(f"📝 Записал метку к {html.escape(entry.get('title') or key)}: {html.escape(cmd['text'][:500])}",
            reply_to=cmd["reply_to"])
    return True


def main():
    p = argparse.ArgumentParser(prog="python -m bot", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--loop", type=int, metavar="SEC", help="keep running, one pass every SEC seconds")
    p.add_argument("--dry-run", action="store_true", help="send nothing to Telegram and leave the database alone")
    p.add_argument("--all", action="store_true", help="with --dry-run: check lots already sold too")
    p.add_argument("--board", metavar="PATH", help="where to write the web page data (default: next to the database)")
    p.add_argument("--note", metavar="BIKE", help="store a note on a bike (frame or lot key) and exit")
    p.add_argument("--tag", default="", help=f"with --note: {', '.join(TAGS)}, or delete (text is the note id)")
    p.add_argument("--text", default="", help="with --note: the note text")
    p.add_argument("--lot", default=None, help="with --note: key of the lot the note was left on")
    p.add_argument("--whoami", action="store_true", help="print chat ids from recent messages to the bot")
    p.add_argument("--test", action="store_true", help="send a test message")
    p.add_argument("--scan", action="store_true", help="check the sites now instead of waiting for SCAN_EVERY_MIN")
    args = p.parse_args()

    if args.note is not None:
        store = Store.open(CFG["db"], legacy=CFG["state"])
        try:
            add_note(store, args.note, args.tag, args.text, lot_key=args.lot)
            refresh_notes(args.board or board_path(), store)
        finally:
            store.save()
            store.close()
        return

    if not args.dry_run and not CFG["token"]:
        sys.exit("No TG_BOT_TOKEN: put it in .env (see .env.example)")
    tg = Telegram(CFG["token"], CFG["chat_id"], dry_run=args.dry_run)
    if args.whoami:
        return whoami(tg)
    if not args.dry_run and not CFG["chat_id"]:
        sys.exit("No TG_CHAT_ID: run with --whoami to find it")
    if args.test:
        tg.send("👋 Бот на связи. Буду присылать подходящие Tracer'ы.")
        return

    site = Site()
    # A dry run uses an in-memory db: every run sees everything as new and saves nothing
    store = Store() if args.dry_run else Store.open(CFG["db"], legacy=CFG["state"])
    state = store.state
    while True:
        commands = [] if args.dry_run else poll_commands(tg, state)
        kinds = {c["cmd"] for c in commands}
        summary = None
        try:
            if args.dry_run or args.scan or "check" in kinds or scan_due(state):
                summary = run_once(site, tg, store, include_finished=args.dry_run and args.all,
                                   verbose=args.dry_run)
                state["last_scan"] = int(time.time())
                note_site_ok(state, tg)
                if not args.dry_run or args.board:
                    write_board(args.board or board_path(), build_board(summary["board"], store))
        except (OSError, ValueError) as e:  # network, HTTP errors, broken JSON
            # last_scan stays put, so the next run in 5 minutes tries again
            note_site_down(state, tg, e)
        finally:
            noted = [note_from_reply(store, tg, c) for c in commands if c["cmd"] == "note"]
            if any(noted) and summary is None:
                refresh_notes(board_path(), store)
            for cmd in dict.fromkeys(c["cmd"] for c in commands if c["cmd"] != "note"):  # three check requests, one reply
                tg.send(scan_reply(summary) if cmd == "check" else
                        status_reply(state) if cmd == "status" else HELP)
            # even after a crash mid-pass: lots already sent must not go out a second time
            if not args.dry_run:
                store.save()
        if not args.loop:
            break
        time.sleep(args.loop)
    store.close()


if __name__ == "__main__":
    main()

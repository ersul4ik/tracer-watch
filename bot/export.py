"""board.json: everything the web page shows. Lots on sale with a verdict, unsold lots, outcomes,
the sales archive and notes.

The bot writes it next to the database after every pass; the page reads it from the state branch.
"""
import html
import json
import time
from datetime import datetime
from pathlib import Path

from .config import CFG, FOR_SALE, NOT_SOLD, SOLD
from .messages import inspection_lines
from .pricing import (auction_day, bike_id, days_to_auction, expected_price, frame_key, limit_for,
                      same_lot_key, stats_model)

VERSION = 1


def site_of(url):
    return "projapan" if "projapan" in (url or "") else "motoauction"


def iso_day(lot):
    day = auction_day(lot)
    return day.isoformat() if day else None


def lot_row(lot, detail=None, estimate=None):
    """A row for the lots table."""
    detail = detail or lot.get("detail") or {}
    return {"key": str(lot["id"]), "site": lot.get("site") or "motoauction", "bike": bike_id(lot),
            "frame": lot.get("frame") or detail.get("frame_number"), "same_key": same_lot_key(lot),
            "model": lot.get("model"), "year": lot.get("year"), "rank": lot.get("rank"),
            "mileage": lot.get("mileage"), "start": detail.get("price_start_jpy") or lot.get("price") or None,
            "final": (lot.get("price") if lot.get("availability") in (SOLD, NOT_SOLD) else lot.get("final")) or None,
            "availability": lot.get("availability"), "auction": detail.get("auction_line") or lot.get("auction"),
            "auction_date": lot.get("auction_date"), "lot_no": str(lot.get("bid") or "") or None,
            "url": lot.get("url"), "photo": lot.get("pathImg"), "estimate": estimate}


def board_lot(lot, detail, reason, prev, stats, urls, sent):
    """A lot on sale: everything its card on the page needs."""
    rank = lot.get("rank")
    limit = limit_for(rank)
    start = detail.get("price_start_jpy") or lot.get("price") or 0
    expected, est = expected_price(lot, stats)
    lines = [html.unescape(x) for x in inspection_lines(detail)]
    return {
        "key": str(lot["id"]), "bike": bike_id(lot), "site": lot.get("site") or "motoauction",
        "model": lot.get("model"), "group": stats_model(lot.get("model")), "year": lot.get("year"),
        "rank": rank, "mileage": lot.get("mileage"), "start": start or None,
        "date": lot.get("auction_date"), "date_iso": iso_day(lot), "days": days_to_auction(lot),
        "auction": detail.get("auction_line") or lot.get("auction"),
        "lot_no": str(detail.get("lot_number") or lot.get("bid") or "") or None,
        "frame": lot.get("frame") or detail.get("frame_number"), "color": detail.get("color"),
        "photo": lot.get("pathImg") or next(iter(detail.get("photos") or []), None),
        "links": [{"site": site_of(u), "url": u} for u in urls],
        "reason": reason, "sent": sent, "limit": limit,
        "estimate": est, "site_avg": detail.get("average_price_jpy") or lot.get("AveragePrice") or None,
        "relist_of": None if prev is None else {"key": str(prev["id"]), "date": prev.get("auction_date"),
                                                 "auction": prev.get("auction"), "bid": prev.get("price")},
        "flags": {"near": bool(start and start > limit), "top": bool(rank and rank >= CFG["top_rank"]),
                  "pricey": bool(expected and expected > limit), "no_rank": not rank},
        # the inspection sheet as plain text; lines marked serious are the ❗ ones
        "inspection": [{"text": x.lstrip("❗•💬 ").strip(), "serious": x.startswith("❗"),
                        "kind": "comment" if x.startswith("💬") else "note" if x.startswith(("❗", "•")) else "info"}
                       for x in lines],
        "serious": any(x.startswith("❗") for x in lines),
    }


def board_unsold(lot, everywhere):
    """Went unsold with a bid within the limit; relisted is the same bike back on sale."""
    again = next((l for l in everywhere.values()
                  if l.get("availability") == FOR_SALE and frame_key(l) and frame_key(l) == frame_key(lot)), None)
    return {"key": str(lot["id"]), "bike": bike_id(lot), "model": lot.get("model"), "year": lot.get("year"),
            "rank": lot.get("rank"), "mileage": lot.get("mileage"), "bid": lot.get("price"),
            "date": lot.get("auction_date"), "date_iso": iso_day(lot), "auction": lot.get("auction"),
            "url": lot.get("url"), "photo": lot.get("pathImg"),
            "relisted": None if again is None else {"key": str(again["id"]), "url": again.get("url"),
                                                     "date": again.get("auction_date"), "start": again.get("price")}}


def board_history(lots_state):
    """What the bot has sent, with auction outcomes, newest first."""
    rows = []
    for key, e in lots_state.items():
        rows.append({"key": key, "bike": e.get("bike"), "title": e.get("title") or key, "url": e.get("url"),
                     "sent_at": e.get("at"), "date_ts": e.get("date_ts") or None, "done": bool(e.get("done")),
                     "kind": "unsold" if e.get("unsold") else "relist" if e.get("relist_of") else "alert",
                     "result": e.get("result")})
    return sorted(rows, key=lambda r: r["sent_at"] or 0, reverse=True)


def board_archive(stats):
    """motoauction's past year of auctions: price, the site's average, and our estimate without the lot itself."""
    rows = []
    for lot in stats.sold + stats.unsold:
        sold = lot.get("availability") == SOLD
        est = stats.estimate(lot) if sold else None
        rows.append({"key": str(lot["id"]), "bike": bike_id(lot), "model": lot.get("model"),
                     "group": stats_model(lot.get("model")), "year": lot.get("year"), "rank": lot.get("rank"),
                     "mileage": lot.get("mileage"), "price": lot.get("price"), "sold": sold,
                     "site_avg": lot.get("AveragePrice") or None, "estimate": est["median"] if est else None,
                     "date": lot.get("auction_date"), "date_iso": iso_day(lot), "auction": lot.get("auction"),
                     "url": lot.get("url"), "photo": lot.get("pathImg")})
    return sorted(rows, key=lambda r: r["date_iso"] or "", reverse=True)


def notes_payload(store):
    return {bike: [{"id": n["id"], "tag": n["tag"], "text": n["text"], "source": n["source"],
                    "created_at": n["created_at"], "lot_key": n["lot_key"]} for n in notes]
            for bike, notes in store.all_notes().items()}


def build_board(payload, store, now=None):
    now = int(now or time.time())
    lots = payload["lots"]
    return {
        "version": VERSION,
        "updated_at": now,
        "updated_iso": datetime.fromtimestamp(now, CFG["tz"]).isoformat(timespec="minutes"),
        "scan_every_min": CFG["scan_every_min"],
        "limits": {"limit": CFG["limit"], "top_limit": CFG["top_limit"], "top_rank": CFG["top_rank"],
                   "min_year": CFG["min_year"], "min_rank": CFG["min_rank"],
                   "expect_ratio": CFG["expect_ratio"], "near_ratio": CFG["near_ratio"]},
        "per_km": payload.get("per_km"),
        "projapan_ok": payload.get("projapan_ok"),
        "counts": {"for_sale": len(lots), "matching": sum(1 for l in lots if not l["reason"]),
                   "sent": len(payload["history"]), "archive": len(payload["archive"]),
                   "seen_total": store.count_lots()},
        "lots": lots,
        "watched": payload["watched"],
        "history": payload["history"],
        "archive": payload["archive"],
        "notes": notes_payload(store),
        "notes_at": now,
    }


def write_board(path, board):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(board, ensure_ascii=False, separators=(",", ":")))
    tmp.replace(path)


def refresh_notes(path, store):
    """After a note without a pass: only the notes in the existing board.json change."""
    path = Path(path)
    if not path.exists():
        return False
    board = json.loads(path.read_text())
    board["notes"], board["notes_at"] = notes_payload(store), int(time.time())
    write_board(path, board)
    return True

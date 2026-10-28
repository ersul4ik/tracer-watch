"""One pass: collect lots from both sites, send the matching ones, follow up on grades and outcomes,
catch unsold and relisted bikes, send the daily digest."""
import html
import time
from datetime import datetime

from .config import CFG, FOR_SALE, NOT_SOLD, SOLD, log
from .export import board_archive, board_history, board_lot, board_unsold, lot_row
from .messages import (grade_message, lot_message, lot_title, relist_intro, result_message,
                       unsold_intro)
from .pricing import (Stats, auction_day, basic_reason, bike_id, check, days_to_auction, frame_key,
                      same_lot_key, unsold_bid)
from .sources.motoauction import SITE
from .sources.projapan import ProJapan


def lot_result(detail):
    """The auction outcome to keep in state: sold or not, and the price (the last bid if unsold)."""
    return {"sold": detail.get("availability") == SOLD,
            "price": detail.get("price_finish_jpy") or detail.get("price_jpy") or 0}


def run_once(site, tg, store, include_finished=False, verbose=False):
    state = store.state
    lots_state = state["lots"]
    first_run = "digest_at" not in state
    groups = [g for g in site.model_groups(CFG["brand"]) if CFG["model_re"].search(g)]
    lots = {}
    for g in groups:
        for lot in site.lots(CFG["brand"], g):
            lot["url"] = f"{SITE}/{lot['id']}"
            lots[str(lot["id"])] = lot
    log(f"groups: {groups}; lots: {len(lots)}")
    stats = Stats(site, groups)

    # projapan adds only what motoauction lacks. If it fails, motoauction lots still go out:
    # the pass just runs without the second source
    projapan = ProJapan()
    known = {same_lot_key(l) for l in lots.values()}
    everywhere = dict(lots)  # copies from both sites, to find a lot already written about
    extra = None
    try:
        pj = projapan.lots()
        everywhere.update(pj)
        extra = {k: l for k, l in pj.items() if same_lot_key(l) not in known}
        log(f"projapan: not on motoauction: {len(extra)}")
        lots.update(extra)
    except (OSError, ValueError) as e:
        log("projapan did not answer:", repr(e))

    def same_of(key):
        entry, lot = lots_state.get(key) or {}, everywhere.get(key)
        return entry.get("same") or (same_lot_key(lot) if lot else None)

    # A lot may go out from one site and show up on the other later: projapan listed it first,
    # motoauction added it afterwards. It must not be sent twice
    sent_same = {same_of(k) for k in lots_state} - {None}

    def settle_copies(key, field):
        """A follow-up or outcome went out for one copy of a lot; the other copies no longer need it."""
        same = same_of(key)
        for k, e in lots_state.items():
            if same and same_of(k) == same:
                e[field] = True

    def copies_of(lot):
        """Keys of state entries sent about this lot, from either site."""
        key, same = str(lot["id"]), same_lot_key(lot)
        return [k for k in lots_state if k == key or (same and same_of(k) == same)]

    # Bikes left unsold in the past two months with a bid within the limit: frame -> latest such lot.
    # projapan does not show unsold lots (they just drop out of its listings), so motoauction only
    watched = {}
    for lot in sorted(stats.not_sold(), key=auction_day):
        if unsold_bid(lot) and frame_key(lot) and days_to_auction(lot) >= -60:
            watched[frame_key(lot)] = lot

    def verdict(lot):
        """The reason to skip (None if it qualifies) and the earlier unsold lot if this is a relist."""
        prev = watched.get(frame_key(lot))
        if prev and lot.get("availability") == FOR_SALE and (auction_day(lot) or auction_day(prev)) > auction_day(prev):
            return basic_reason(lot), prev
        return check(lot, stats), None

    def get_detail(lot):
        return projapan.enrich(lot) if lot.get("site") == "projapan" else site.lot(lot["id"])

    now = time.time()
    details = {}  # lot pages already fetched in this pass, reused for the web page
    for key, lot in sorted(lots.items()):
        if key in lots_state or same_lot_key(lot) in sent_same:
            continue
        if lot.get("availability") != FOR_SALE and not include_finished:
            continue
        # The same bike that recently went unsold within our limit, listed again
        reason, prev = verdict(lot)
        relist = prev is not None
        if verbose:
            log(f"  {key} {lot.get('model')} {lot.get('year')} r{lot.get('rank')} "
                f"av{lot.get('availability')} {lot.get('auction_date')}: {reason or 'MATCH'}"
                + (f" (relist of {prev['id']})" if relist else ""))
        if reason:
            # a skip over start price or grade is not final, both can show up later, so such lots
            # stay out of state and get rechecked every pass; the reason is stored in the db below
            continue
        detail = details[key] = get_detail(lot)
        photo = lot.get("pathImg") or next(iter(detail.get("photos") or []), None)
        text = lot_message(lot, detail, 1024 if photo else 4096, stats, intro=relist_intro(prev, detail) if relist else (),
                           notes=store.notes_for(bike_id(lot)))
        # a relist goes as a reply to the earlier message about the bike, if there was one
        reply_to = next((lots_state[k].get("msg") for k in copies_of(prev)), None) if relist else None
        msg_id = tg.send(text, photo=photo, button_url=lot["url"], reply_to=reply_to)
        lots_state[key] = {"at": int(now), "msg": msg_id, "date_ts": detail.get("auction_date_ts") or 0,
                           "done": lot.get("availability") != FOR_SALE, "graded": bool(lot.get("rank")),
                           "same": same_lot_key(lot), "bike": bike_id(lot), "title": lot_title(lot), "url": lot["url"]}
        if lot.get("site") == "projapan":
            lots_state[key]["frame"] = detail.get("frame_number")  # the outcome is looked up by frame later
        if relist:
            lots_state[key]["relist_of"] = str(prev["id"])
        log(f"sent lot {key}" + (f", relist of {prev['id']}" if relist else ""))

    # Lots sent without a grade: once it is out, reply with what the inspection sheet says.
    # Older entries lack the graded field; they were sent with a grade already
    for key, entry in lots_state.items():
        lot = everywhere.get(key)
        if entry.get("done") or entry.get("graded", True) or not lot or not lot.get("rank"):
            continue
        try:
            detail = details[key] = get_detail(lot)
        except (OSError, ValueError) as e:
            log(f"lot {key}: {e!r}")
            continue
        tg.send(grade_message(lot, detail, stats), reply_to=entry.get("msg"))
        settle_copies(key, "graded")
        entry["graded"] = True
        log(f"grade follow-up sent for lot {key}")

    # auction outcomes for lots already sent
    for key, entry in lots_state.items():
        if entry.get("done") or not entry.get("date_ts") or entry["date_ts"] > now:
            continue
        lot = everywhere.get(key)
        if lot is not None and lot.get("availability") == FOR_SALE:
            continue
        try:
            detail = projapan.result(key, entry.get("frame")) if key.startswith("pj:") else site.lot(key)
        except (OSError, ValueError) as e:
            log(f"lot {key}: {e!r}")
            continue
        if detail.get("availability") in (SOLD, NOT_SOLD):
            tg.send(result_message(detail), reply_to=entry.get("msg"))
            settle_copies(key, "done")
            entry["done"], entry["result"] = True, lot_result(detail)
        elif now - entry["date_ts"] > 3 * 86400:
            entry["done"] = True  # no outcome ever showed up: stop asking

    # Just went unsold with a bid within the limit: while the seller is still warm, there is room to haggle.
    # The price forecast usually filtered these out before the auction, so they are usually new to the user
    for lot in watched.values():
        key, same, sent = str(lot["id"]), same_lot_key(lot), copies_of(lot)
        if days_to_auction(lot) < -2 or any(lots_state[k].get("done") for k in sent):
            continue
        try:
            detail = site.lot(lot["id"])
        except (OSError, ValueError) as e:
            log(f"lot {key}: {e!r}")
            continue
        if sent:
            # its projapan copy was sent, and projapan cannot tell an unsold outcome
            tg.send(result_message(detail), reply_to=lots_state[sent[0]].get("msg"))
            settle_copies(sent[0], "done")
            lots_state[sent[0]]["result"] = lot_result(detail)
            continue
        photo = lot.get("pathImg") or next(iter(detail.get("photos") or []), None)
        text = lot_message(lot, detail, 1024 if photo else 4096, stats, intro=unsold_intro(lot, detail),
                           notes=store.notes_for(bike_id(lot)))
        lots_state[key] = {"at": int(now), "msg": tg.send(text, photo=photo, button_url=lot["url"]),
                           "date_ts": detail.get("auction_date_ts") or 0, "done": True, "graded": True,
                           "same": same, "unsold": lot["price"], "bike": bike_id(lot), "title": lot_title(lot), "url": lot["url"],
                           "result": lot_result(detail)}
        log(f"sent unsold lot {key}")

    if first_run:
        # Whatever is listed at the first run is not "new today"
        state["digest_at"] = int(now)
    for_sale = [l for l in lots.values() if l.get("availability") == FOR_SALE]
    # for the reply to a check request: already-sent lots still on sale, with links to every copy
    def urls(lot):
        same = same_lot_key(lot)
        return [l["url"] for l in everywhere.values() if l is lot or (same and same_lot_key(l) == same)]

    # The web page: what matches, what is on sale, what went unsold, outcomes and the archive
    sent_same = {same_of(k) for k in lots_state} - {None}
    board_lots = []
    # First pass with the db: everything on the sites now appeared earlier, otherwise the digest
    # would call every lot new at once
    first_seen = None if state.get("lots_seeded") else 0
    for key, lot in sorted(lots.items(), key=lambda kv: (auction_day(kv[1]) or datetime.max.date(), kv[0])):
        if lot.get("availability") != FOR_SALE:
            continue
        reason, prev = verdict(lot)
        detail = details.get(key)
        if detail is None and not reason:
            try:
                detail = details[key] = get_detail(lot)
                reason, prev = verdict(lot)  # a projapan lot page can bring the grade
            except (OSError, ValueError) as e:
                log(f"lot {key}: {e!r}")
        sent = key in lots_state or same_lot_key(lot) in sent_same
        item = board_lot(lot, detail or lot.get("detail") or {}, reason, prev, stats, urls(lot), sent)
        board_lots.append(item)
        # a lot already sent (or its copy on the other site) is not "skipped" in the digest
        store.record_lot(lot_row(lot, detail, (item["estimate"] or {}).get("median")), int(now),
                         reason=None if sent else reason, with_reason=True, first_seen=first_seen)
    # copies from the other site and the sales archive go to the db too: our own archive
    for key, lot in everywhere.items():
        if key not in lots:
            store.record_lot(lot_row(lot), int(now), first_seen=first_seen)
    for lot in stats.sold + stats.unsold:
        store.record_lot(lot_row(lot), int(now), first_seen=first_seen)
    store.forget_unlisted(int(now))
    state["lots_seeded"] = True
    for key, entry in lots_state.items():  # entries from before this version lack a title and a bike
        if key in everywhere:
            entry.setdefault("title", lot_title(everywhere[key]))
            entry.setdefault("url", everywhere[key]["url"])
            entry.setdefault("bike", bike_id(everywhere[key]))
            # entries sent before cross-site matching existed lack it; fill it in while the lot is listed
            if not entry.get("same"):
                entry["same"] = same_lot_key(everywhere[key])

    # the digest comes after lots are stored, so it includes the ones first seen in this pass
    if not tg.dry_run:
        maybe_send_digest(store, tg, len(for_sale))

    return {"for_sale": len(for_sale),
            "projapan_only": None if extra is None else sum(1 for l in extra.values()
                                                            if l.get("availability") == FOR_SALE),
            "sent_now": [k for k, v in lots_state.items() if v["at"] == int(now)],
            "open": [(l, urls(l)) for k, l in lots.items() if l.get("availability") == FOR_SALE and k in lots_state],
            "board": {"lots": board_lots, "projapan_ok": extra is not None, "per_km": stats.per_km,
                      "watched": [board_unsold(l, everywhere) for l in watched.values()],
                      "history": board_history(lots_state), "archive": board_archive(stats)}}


def digest_due(state):
    if CFG["digest_hour"] < 0:
        return False
    local = datetime.now(CFG["tz"])
    return local.hour >= CFG["digest_hour"] and state.get("digest_day") != local.strftime("%Y-%m-%d")


def maybe_send_digest(store, tg, for_sale):
    """Once a day: what the bot saw. It doubles as a heartbeat: no digest means something broke."""
    state = store.state
    if not digest_due(state):
        return
    today = datetime.now(CFG["tz"]).strftime("%Y-%m-%d")
    since = state.get("digest_at", 0)
    sent = sum(1 for v in state["lots"].values() if v["at"] > since)
    new = store.new_skipped_since(since)

    lines = ["📋 <b>Сводка за сутки</b>",
             f"Лотов Tracer в продаже: {for_sale}."
             + (f" Прислал подходящих: <b>{sent}</b>." if sent else " Подходящих не нашлось.")]
    if new:
        lines.append(f"\nНовые за сутки, не подошли ({len(new)}):")
        lines += [f"• {html.escape(x)}" for x in new[:30]]
        if len(new) > 30:
            lines.append(f"… и ещё {len(new) - 30}")
    else:
        lines.append("Других новых лотов не было." if sent else "Новых лотов за сутки не появилось.")
    tg.send("\n".join(lines))
    state["digest_day"], state["digest_at"] = today, int(time.time())


def note_site_ok(state, tg):
    if state["alerted"]:
        tg.send("✅ Сайт снова отвечает, слежу дальше.")
    state["fail_since"], state["alerted"] = None, False


def note_site_down(state, tg, err):
    """One failure is no reason to bother the user; silence longer than ALERT_AFTER_MIN is."""
    log("site did not answer:", repr(err))
    now = int(time.time())
    if not state["fail_since"]:
        state["fail_since"] = now
    down_min = (now - state["fail_since"]) // 60
    if not state["alerted"] and down_min >= CFG["alert_after_min"]:
        tg.send(f"⚠️ motoauction.online не отвечает уже {down_min} мин — лоты сейчас не вижу.\n"
                f"<code>{html.escape(repr(err))[:300]}</code>")
        state["alerted"] = True


def scan_due(state):
    return time.time() - state.get("last_scan", 0) >= CFG["scan_every_min"] * 60 or digest_due(state)

"""Telegram message texts (the texts themselves are Russian: they are for the user)."""
import html
import re
import time
from datetime import datetime

from .config import CFG, SOLD, fmt_jpy, fmt_num
from .pricing import check, expected_price, limit_for


def report_lines(detail):
    """A short digest of the inspection sheet: section grades and notes."""
    lines = []
    for part in detail.get("inspector_report") or []:
        comments = "; ".join(c for c in part.get("comments") or [] if c)
        if not comments:
            continue
        lines.append(f"• {part.get('title_ru') or part.get('name')} ({part.get('rank') or '?'}): {comments}")
    return lines


# Notes that make a lot worth a careful look: noises, leaks, "needs replacing".
# "Сильно" (heavy) is serious only when it is not about scratches
SERIOUS_RE = re.compile(r"требует замен|failure|неисправ|не работ|шум|течь|утечк|трещин"
                        r"|^(?!.*царапин).*сильно", re.I)


def inspection_lines(detail):
    """The inspection sheet for a message, serious notes first and marked with ❗."""
    lines = []
    if detail.get("comment_auction_ru"):
        lines.append(f"💬 {detail['comment_auction_ru']}")
    if detail.get("ratings_line"):
        lines.append(detail["ratings_line"])
    if detail.get("prev_meter"):
        lines.append(f"Пробег на прошлой проверке: {detail['prev_meter']}")
    notes = report_lines(detail) + [f"• {n}" for n in detail.get("notes") or []]
    lines += ["❗" + n[1:] for n in notes if SERIOUS_RE.search(n)]
    lines += [n for n in notes if not SERIOUS_RE.search(n)]
    return [html.escape(x) for x in lines]


def fit(head, tail, max_len):
    text = "\n".join(head)
    for line in tail:
        if len(text) + len(line) + 1 > max_len - 4:
            return text + "\n…"
        text += "\n" + line
    return text


def lot_message(lot, detail, max_len, stats=None, intro=(), notes=()):
    rank = lot.get("rank")
    limit = limit_for(rank)
    start = detail.get("price_start_jpy") or lot.get("price") or 0
    avg = detail.get("average_price_jpy") or lot.get("AveragePrice") or 0
    expected, est = expected_price(lot, stats)
    rub = (detail.get("display_price") or {}).get("display")
    rub_label = (detail.get("display_price") or {}).get("label") or "Под ключ"
    flags = []
    if start > limit:
        flags.append(f"🟡 почти: старт уже выше лимита на {fmt_jpy(start - limit)}"
                     " — в лимит не взять, только если его поднять")
    if rank and rank >= CFG["top_rank"]:
        flags.append("🔥 топ-оценка")
    if not rank:
        flags.append("⏳ оценки пока нет, торги вот-вот")
    if expected > limit:
        flags.append("⚠️ обычно уходят дороже лимита")
    if est:
        expect_line = (f"Обычно уходят за: <b>~{fmt_jpy(est['median'])}</b> "
                       f"(медиана {est['n']} продаж, {est['scope']}; от {fmt_jpy(est['lo'])} до {fmt_jpy(est['hi'])})")
    else:
        expect_line = f"Средняя с сайта: {fmt_jpy(avg)} (своих продаж для сравнения мало)"

    e = html.escape
    head = [*intro,
        f"🏍 <b>{e(lot.get('brand') or '')} {e(lot.get('model') or '')}</b> · {lot.get('year') or 'год ?'}",
        f"Оценка <b>{rank or '?'}</b> · {fmt_num(lot.get('mileage') or 0)} км"
        f" · {lot.get('volume') or '?'} cc · {e(detail.get('color') or '')}",
        f"Торги <b>{e(lot.get('auction_date') or '?')}</b> · {e(detail.get('auction_line') or lot.get('auction') or '')}"
        f" · лот {e(str(detail.get('lot_number') or lot.get('bid') or ''))}",
        f"Старт: {fmt_jpy(start) if start else 'пока неизвестен'}",
        expect_line,
        f"Наш лимит (финал): <b>{fmt_jpy(limit)}</b>" + (f" · {e(rub_label)}: {e(rub)}" if rub else ""),
    ]
    head += flags
    if lot.get("site") == "projapan":
        head.append(f"🔎 нашёл на projapan.ru, на motoauction этого лота нет · рама {e(detail.get('frame_number') or '?')}")
    if notes:
        head.append("📝 Твои метки: " + e("; ".join(note_text(n) for n in notes)))

    return fit(head, inspection_lines(detail), max_len)


def grade_message(lot, detail, stats):
    """Follow-up to a lot sent without a grade: what the inspection sheet says and whether it still qualifies."""
    reason = check(lot, stats)
    head = [f"📋 Появилась оценка: <b>{lot['rank']:g}</b>"]
    _, est = expected_price(lot, stats)
    if est:
        head.append(f"Обычно уходят за: ~{fmt_jpy(est['median'])} (медиана {est['n']} продаж, {est['scope']})")
    tail = inspection_lines(detail)
    if reason:
        head.append(f"❌ Теперь не подходит: {html.escape(reason)}")
    elif any(x.startswith("❗") for x in tail):
        head.append("🟡 По критериям подходит, но в листе осмотра есть серьёзные замечания ❗")
    else:
        head.append("✅ По-прежнему подходит")
    return fit(head, tail, 4096)


NEGOTIATE = ("Можно попросить дилера поторговаться: после торгов продавцы иногда отдают чуть дороже ставки, "
             "но обычно только день-два. Если мотоцикл выставят снова, напишу.")


def result_message(detail):
    av = detail.get("availability")
    final = detail.get("price_finish_jpy") or detail.get("price_jpy") or 0
    rub = (detail.get("display_price") or {}).get("display")
    if av == SOLD:
        s = f"✅ Продан за <b>{fmt_jpy(final)}</b>"
    else:
        s = f"❌ Не продан, последняя ставка {fmt_jpy(final)}"
        if 0 < final <= limit_for(detail.get("rank")):
            s += "\n🤝 Покупатель в наш лимит нашёлся, не согласился продавец. " + NEGOTIATE
    if rub and av == SOLD:
        s += f" (под ключ {html.escape(rub)})"
    return s


def serious_warning(detail):
    if any(x.startswith("❗") for x in inspection_lines(detail)):
        return ["❗ В листе осмотра серьёзные замечания — возможно, ставки низкие из-за них, а не по везению."]
    return []


def unsold_intro(prev, detail):
    return [f"🤝 <b>Не продан: ставка дошла до {fmt_jpy(prev['price'])}, продавец не отдал</b>", NEGOTIATE,
            *serious_warning(detail), ""]


def relist_intro(prev, detail):
    return [f"🔁 <b>Снова на торгах.</b> {html.escape(prev.get('auction_date') or '?')} на "
            f"{html.escape(prev.get('auction') or '?')} его не продали: ставка дошла до "
            f"<b>{fmt_jpy(prev['price'])}</b>, продавец хотел больше",
            "Присылаю, даже если похожие обычно уходят дороже: свою цену продавец уже не получил и может уступить.",
            *serious_warning(detail), ""]


def fmt_when(ts):
    return datetime.fromtimestamp(ts, CFG["tz"]).strftime("%d.%m %H:%M") if ts else "ещё ни разу"


def scan_reply(summary):
    if summary is None:
        return "⚠️ Сходил, но сайт не ответил. Попробую ещё раз через 5 минут."
    pj = summary["projapan_only"]
    lines = [f"🔎 Сходил на motoauction и projapan: лотов Tracer в продаже — {summary['for_sale']}"
             + (" (projapan не ответил, только motoauction)." if pj is None else
                f", из них только на projapan — {pj}." if pj else ", все есть на motoauction.")]
    lines.append(f"Новых подходящих: <b>{len(summary['sent_now'])}</b> — прислал выше."
                 if summary["sent_now"] else "Новых подходящих нет.")
    if summary["open"]:
        lines.append("\nУже присылал, торги ещё впереди:")
        lines += [f"• {html.escape(l.get('model') or '')} {l.get('year')} · оценка {l.get('rank') or '?'}"
                  f" · торги {(l.get('auction_date') or '?')[:5]} — {' · '.join(urls)}" for l, urls in summary["open"]]
    return "\n".join(lines)


def status_reply(state):
    next_ts = state.get("last_scan", 0) + CFG["scan_every_min"] * 60
    return (f"Последняя проверка: {fmt_when(state.get('last_scan'))}. "
            f"Следующая: ~{fmt_when(max(next_ts, time.time()))}.\n"
            f"Присылал лотов за всё время: {len(state['lots'])}.")


TAGS = {"seen": "👀 посмотрел", "price": "💴 дорого", "repair": "🔧 ремонт", "mileage": "📏 пробег",
        "like": "⭐ интересно"}


def note_text(note):
    tag = TAGS.get(note.get("tag") or "", note.get("tag") or "")
    return " — ".join(x for x in (tag, note.get("text") or "") if x)


def lot_title(lot):
    return f"{lot.get('model') or '?'} {lot.get('year') or '?'} · оценка {lot.get('rank') or '?'}"

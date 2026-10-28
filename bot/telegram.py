"""Telegram: sending messages, and commands from the user's chat (check now, /status, notes as replies)."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from .config import CFG, log


class Telegram:
    def __init__(self, token, chat_id, dry_run=False):
        self.token, self.chat_id, self.dry_run = token, chat_id, dry_run

    def call(self, method, **params):
        data = urllib.parse.urlencode(
            {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in params.items()}
        ).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{self.token}/{method}", data=data)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)["result"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Telegram {method}: {e.code} {e.read().decode(errors='replace')}")

    def send(self, text, photo=None, button_url=None, reply_to=None):
        if self.dry_run:
            print("\n----- [dry-run] message -----")
            print(re.sub(r"<[^>]+>", "", text))
            if button_url:
                print(f"[button] {button_url}")
            print("-------------------------------")
            return None
        common = {"chat_id": self.chat_id, "parse_mode": "HTML"}
        if button_url:
            common["reply_markup"] = {"inline_keyboard": [[{"text": "Открыть лот", "url": button_url}]]}
        if reply_to:
            common["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        if photo and len(text) <= 1024:
            try:
                return self.call("sendPhoto", photo=photo, caption=text, **common)["message_id"]
            except RuntimeError as e:
                log("photo failed, sending as text:", e)
        return self.call("sendMessage", text=text, link_preview_options={"is_disabled": True},
                         **common)["message_id"]


CHECK_RE = re.compile(r"/check|/scan|сходи|посмотр|провер|глян", re.I)
STATUS_RE = re.compile(r"/status|статус|жив", re.I)
HELP = ("Я слежу за лотами Tracer и пишу, когда появляется подходящий.\n"
        "• «сходи посмотри» или /check — проверить сайт прямо сейчас\n"
        "• /status — когда проверял последний раз\n"
        "• ответь текстом на моё сообщение о лоте — запишу это как метку к мотоциклу "
        "(«дорого», «ремонт»…), она будет на сайте и в следующих сообщениях о нём\n"
        "Отвечаю в течение ~5 минут: чаще меня не будят.")


def poll_commands(tg, state):
    """What the user wrote to the bot since the last run. Only the configured chat counts.

    Each command is {"cmd": "check" | "status" | "help"} or {"cmd": "note", "reply_to", "text"}.
    """
    try:
        updates = tg.call("getUpdates", offset=state.get("tg_offset", 0), timeout=0,
                          allowed_updates=["message"])
    except (RuntimeError, OSError) as e:
        log("could not read messages:", e)
        return []
    commands = []
    for u in updates:
        state["tg_offset"] = u["update_id"] + 1
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != str(CFG["chat_id"]):
            continue
        text = (msg.get("text") or "").strip()
        reply_to = (msg.get("reply_to_message") or {}).get("message_id")
        # a reply to one of the bot's messages is a note on that lot, unless it is a command
        if reply_to and text and not CHECK_RE.fullmatch(text) and not text.startswith("/"):
            commands.append({"cmd": "note", "reply_to": reply_to, "text": text})
        else:
            commands.append({"cmd": "check" if CHECK_RE.search(text) else "status" if STATUS_RE.search(text) else "help"})
    return commands


def whoami(tg):
    updates = tg.call("getUpdates")
    chats = {}
    for u in updates:
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat")
        if chat:
            chats[chat["id"]] = chat.get("username") or chat.get("title") or chat.get("first_name")
    if not chats:
        print("Nothing yet. Send the bot any message in Telegram and run this again.")
    for cid, name in chats.items():
        print(f"TG_CHAT_ID={cid}    # {name}")

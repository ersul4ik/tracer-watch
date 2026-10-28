"""SQLite: what the bot has sent, every lot it has seen, notes, and bookkeeping.

A pass works on store.state, the same dict that used to live in state.json:
state["lots"] holds sent lots by key, the other fields are bookkeeping (tg_offset, last_scan...).
Store reads it from the tables and writes it back, and keeps lots and notes itself.
"""
import json
import sqlite3
import time
from pathlib import Path

from .config import log

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL                -- JSON
);
-- What went to Telegram: one row per lot alert
CREATE TABLE IF NOT EXISTS sent (
    key          TEXT PRIMARY KEY,     -- motoauction lot id or pj:<id>
    sent_at      INTEGER NOT NULL,
    msg_id       INTEGER,
    date_ts      INTEGER,              -- start of the auction day
    kind         TEXT NOT NULL,        -- alert / relist / unsold
    done         INTEGER NOT NULL DEFAULT 0,  -- outcome already sent
    graded       INTEGER NOT NULL DEFAULT 1,  -- had a grade, or the follow-up went out
    same_key     TEXT,                 -- auction|date|number: one lot across both sites
    frame        TEXT,
    bike         TEXT,                 -- what notes attach to, see pricing.bike_id
    relist_of    TEXT,
    unsold_bid   INTEGER,
    title        TEXT,
    url          TEXT,
    result_sold  INTEGER,
    result_price INTEGER
);
-- Every Tracer lot the bot has seen: our own archive, deeper than the site's one year
CREATE TABLE IF NOT EXISTS lots (
    key          TEXT PRIMARY KEY,
    site         TEXT,
    bike         TEXT,
    frame        TEXT,
    same_key     TEXT,
    model        TEXT,
    year         INTEGER,
    rank         REAL,
    mileage      INTEGER,
    start        INTEGER,
    final        INTEGER,              -- price if sold, last bid if not
    availability INTEGER,              -- 0 for sale, 1 sold, 2 not sold
    auction      TEXT,
    auction_date TEXT,                 -- dd.mm.yyyy, as on the sites
    lot_no       TEXT,
    url          TEXT,
    photo        TEXT,
    first_seen   INTEGER NOT NULL,
    last_seen    INTEGER NOT NULL,
    last_reason  TEXT,                 -- why it did not qualify; NULL if it did or for archive rows
    legacy_line  TEXT,                 -- digest line carried over from state.json
    estimate     INTEGER
);
CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    bike       TEXT NOT NULL,
    lot_key    TEXT,
    tag        TEXT,
    text       TEXT,
    source     TEXT NOT NULL,          -- web / telegram / cli
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS notes_bike ON notes (bike);
"""

# Fields of a state["lots"][key] entry and the sent columns they map to
ENTRY_COLUMNS = {"at": "sent_at", "msg": "msg_id", "date_ts": "date_ts", "same": "same_key", "frame": "frame",
                 "bike": "bike", "relist_of": "relist_of", "unsold": "unsold_bid", "title": "title", "url": "url"}
KV_KEYS = ("tg_offset", "last_scan", "digest_day", "digest_at", "fail_since", "alerted", "lots_seeded")
LOT_COLUMNS = ("site", "bike", "frame", "same_key", "model", "year", "rank", "mileage", "start", "final",
               "availability", "auction", "auction_date", "lot_no", "url", "photo", "estimate")


class Store:
    def __init__(self, path=":memory:"):
        self.path = path
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        # a no-op on an existing database: the file changes only when data does
        self.conn.executescript(SCHEMA)
        self.state = self._load_state()
        self._saved = self._snapshot()

    @classmethod
    def open(cls, path, legacy=None):
        """The database at path; when it does not exist yet and an old state.json does, imports it."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() and legacy and Path(legacy).exists():
            # import into a temporary file and move it in place only once it worked:
            # a half-done import must not leave a database that is never imported again
            tmp = path.with_suffix(".importing")
            tmp.unlink(missing_ok=True)
            store = cls(tmp)
            store.import_state_json(json.loads(Path(legacy).read_text()))
            log(f"imported {legacy} into the database: {len(store.state['lots'])} sent lots")
            store.close()
            tmp.replace(path)
        return cls(path)

    def close(self):
        self.conn.close()

    # --- pass state ---------------------------------------------------------------------

    def _load_state(self):
        state = {"lots": {}, "fail_since": None, "alerted": False}
        for row in self.conn.execute("SELECT key, value FROM kv"):
            state[row["key"]] = json.loads(row["value"])
        for row in self.conn.execute("SELECT * FROM sent"):
            entry = {field: row[col] for field, col in ENTRY_COLUMNS.items() if row[col] is not None}
            entry["done"], entry["graded"] = bool(row["done"]), bool(row["graded"])
            if row["result_sold"] is not None:
                entry["result"] = {"sold": bool(row["result_sold"]), "price": row["result_price"]}
            state["lots"][row["key"]] = entry
        return state

    def _snapshot(self):
        return json.dumps(self.state, sort_keys=True, default=str)

    def save(self):
        """Writes the state only if it changed; otherwise every 5-minute ping would make a commit."""
        if self._snapshot() == self._saved:
            return
        with self.conn:
            for key, entry in self.state["lots"].items():
                row = {col: entry.get(field) for field, col in ENTRY_COLUMNS.items()}
                result = entry.get("result") or {}
                row.update(key=key, done=int(bool(entry.get("done"))), graded=int(entry.get("graded", True)),
                           kind="unsold" if entry.get("unsold") else "relist" if entry.get("relist_of") else "alert",
                           result_sold=None if not result else int(bool(result.get("sold"))),
                           result_price=result.get("price"))
                cols = ", ".join(row)
                self.conn.execute(f"INSERT OR REPLACE INTO sent ({cols}) VALUES ({', '.join('?' * len(row))})",
                                  list(row.values()))
            for key in KV_KEYS:
                if key in self.state:
                    self.conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)",
                                      (key, json.dumps(self.state[key])))
        self._saved = self._snapshot()

    def import_state_json(self, old):
        """Old state.json: lots go to sent, skipped to lots (for the digest), the rest to kv."""
        self.state["lots"].update(old.get("lots") or {})
        for key in KV_KEYS:
            if key in old:
                self.state[key] = old[key]
        with self.conn:
            for key, v in (old.get("skipped") or {}).items():
                # all that is left of a skipped lot is its digest line
                self.conn.execute(
                    "INSERT OR IGNORE INTO lots (key, availability, first_seen, last_seen, legacy_line)"
                    " VALUES (?, 0, ?, ?, ?)", (key, v.get("at", 0), v.get("at", 0), v.get("line")))
        self.save()

    # --- lots ------------------------------------------------------------------------------

    def record_lot(self, row, now, reason=None, with_reason=False, first_seen=None):
        """Upserts a lot: on repeat the fields and last_seen update, first_seen stays.

        row is a dict with key and the LOT_COLUMNS. with_reason means the lot is on sale and reason
        (None if it qualifies) must be stored; archive rows have none. first_seen is when the lot
        appeared, when that is known better than "now" (0 means unknown).
        """
        values = {c: row.get(c) for c in LOT_COLUMNS}
        cols = ["key", *values, "first_seen", "last_seen"] + (["last_reason"] if with_reason else [])
        args = [row["key"], *values.values(), now if first_seen is None else first_seen, now]
        args += [reason] if with_reason else []
        updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c not in ("key", "first_seen"))
        with self.conn:
            self.conn.execute(f"INSERT INTO lots ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
                              f" ON CONFLICT(key) DO UPDATE SET {updates}", args)

    def new_skipped_since(self, since):
        """Lots on sale first seen after since that did not qualify, as digest lines."""
        rows = self.conn.execute(
            "SELECT * FROM lots WHERE first_seen > ?"
            " AND (last_reason IS NOT NULL OR legacy_line IS NOT NULL)"
            " AND key NOT IN (SELECT key FROM sent) ORDER BY first_seen", (since,))
        out = []
        for r in rows:
            if r["last_reason"] is None:  # imported from state.json, which kept a ready-made line
                out.append(r["legacy_line"])
            else:
                out.append(f"{r['model']} {r['year'] or '?'} · оценка {r['rank'] or '?'}"
                           f" · торги {(r['auction_date'] or '?')[:5]} — {r['last_reason']}")
        return out

    def forget_unlisted(self, now):
        """Lots on sale not seen in this pass dropped out of the listings: their status is unknown now."""
        with self.conn:
            self.conn.execute("UPDATE lots SET availability = NULL WHERE availability = 0 AND last_seen < ?", (now,))

    def count_lots(self):
        return self.conn.execute("SELECT COUNT(*) FROM lots").fetchone()[0]

    # --- notes -------------------------------------------------------------------------------

    def add_note(self, bike, tag="", text="", lot_key=None, source="web", now=None):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO notes (bike, lot_key, tag, text, source, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (bike, lot_key, tag or "", (text or "").strip(), source, int(now or time.time())))
        return cur.lastrowid

    def delete_note(self, note_id, bike):
        with self.conn:
            return self.conn.execute("DELETE FROM notes WHERE id = ? AND bike = ?", (note_id, bike)).rowcount

    def notes_for(self, bike):
        if not bike:
            return []
        rows = self.conn.execute("SELECT * FROM notes WHERE bike = ? ORDER BY created_at, id", (bike,))
        return [dict(r) for r in rows]

    def all_notes(self):
        notes = {}
        for r in self.conn.execute("SELECT * FROM notes ORDER BY created_at, id"):
            notes.setdefault(r["bike"], []).append(dict(r))
        return notes

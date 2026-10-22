"""Monatsablage für OnStreet-Aufträge.

Verwendet DATABASE_URL (PostgreSQL) für dauerhafte, gemeinsam genutzte Daten.
Lokal nur SQLite zum Testen. Keine Original-CSV-Dateien speichern.
"""
import hashlib
import json
from datetime import datetime, timedelta, date

from cuvenhaus_suite import Storage, persistent, setting

RETENTION_DAYS = 90
FIELDS = ("nr", "raw_nr", "fahrer", "stat", "annahme", "datum", "zeit",
          "kfz", "ag", "art", "start", "ziel", "route", "tarif", "betrag",
          "bemerkung")
KEY_FIELDS = ("nr", "raw_nr")


def _serialize(order):
    return {k: order.get(k) for k in FIELDS}


def _key(order):
    return str(order.get("nr") or order.get("raw_nr") or "").strip()


def _fingerprint(order):
    record = _serialize(order)
    return hashlib.sha256(json.dumps(record, ensure_ascii=False,
                                     sort_keys=True, default=str).encode()).hexdigest()


def init_month_store(db):
    db.execute("""CREATE TABLE IF NOT EXISTS monthly_orders (
        order_key TEXT PRIMARY KEY,
        payload TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )""")


def prune(db, today=None):
    cutoff = (today or date.today()).isoformat()
    db.execute("DELETE FROM monthly_orders WHERE expires_at < ?", (cutoff,))


def upsert_import(db, orders, today=None):
    """Gleiche ID + gleicher Inhalt = Duplikat; ID + neuer Inhalt = Update."""
    today = today or date.today()
    expiry = (today + timedelta(days=RETENTION_DAYS)).isoformat()
    now = datetime.now().isoformat(timespec="seconds")
    stats = {"neu": 0, "unveraendert": 0, "aktualisiert": 0, "ohne_id": 0}
    init_month_store(db)
    prune(db, today)
    for order in orders:
        key = _key(order)
        if not key:
            stats["ohne_id"] += 1
            continue
        fp = _fingerprint(order)
        found = db.execute("SELECT fingerprint FROM monthly_orders WHERE order_key=?", (key,))
        if not found:
            stats["neu"] += 1
        elif found[0][0] == fp:
            stats["unveraendert"] += 1
        else:
            stats["aktualisiert"] += 1
        db.execute("""INSERT INTO monthly_orders(order_key,payload,fingerprint,updated_at,expires_at)
            VALUES(?,?,?,?,?) ON CONFLICT(order_key) DO UPDATE SET
            payload=excluded.payload, fingerprint=excluded.fingerprint,
            updated_at=excluded.updated_at, expires_at=excluded.expires_at""",
            (key, json.dumps(_serialize(order), ensure_ascii=False, default=str),
             fp, now, expiry))
    return stats


def load_orders(db):
    init_month_store(db)
    prune(db)
    rows = db.execute("SELECT payload FROM monthly_orders ORDER BY updated_at")
    records = {}
    for (payload,) in rows:
        o = json.loads(payload)
        # Result is fed through the existing app calculations.
        o["dt"] = None
        for value in (o.get("annahme"), f"{o.get('datum','')} {o.get('zeit','')}"):
            if not value:
                continue
            for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M",
                        "%d.%m.%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    o["dt"] = datetime.strptime(str(value).strip(), fmt)
                    break
                except ValueError:
                    continue
            if o["dt"]:
                break
        o.update(start_zone=None, target_zone=None, auto_zone=None, final_zone=None,
                 zone_text="", zone_warning=False, geofence_checked=False,
                 manual_zone=None)
        records[_key(o)] = o
    return records


def get_db():
    db = Storage()
    init_month_store(db)
    return db

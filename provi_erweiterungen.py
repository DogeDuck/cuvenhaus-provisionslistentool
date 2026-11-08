"""Persistent co-driver claims, verified locations and provision audit.

All tables share the existing SQLite/GitHub backup. Unique driver+order keys
prevent double commissions *per driver*, while co-drivers can each receive
their own commission. Amounts are never split automatically.
"""
from datetime import date, datetime, timedelta
import json
import math
import re


def driver_id(name):
    return " ".join(str(name).casefold().split())


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS co_driver_claims (
        driver_id TEXT NOT NULL, order_nr TEXT NOT NULL,
        claimed_at TEXT NOT NULL, PRIMARY KEY(driver_id,order_nr))""")
    db.execute("""CREATE TABLE IF NOT EXISTS location_overrides (
        address_key TEXT PRIMARY KEY, lat REAL NOT NULL, lon REAL NOT NULL,
        updated_at TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS audit_decisions (
        driver_id TEXT NOT NULL, order_nr TEXT NOT NULL,
        issue_code TEXT NOT NULL, status TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(driver_id,order_nr,issue_code))""")


def _now():
    return datetime.now().isoformat(timespec="seconds")


def claim(db, driver, nr):
    init(db)
    db.execute("""INSERT INTO co_driver_claims(driver_id,order_nr,claimed_at)
        VALUES(?,?,?) ON CONFLICT(driver_id,order_nr) DO NOTHING""",
        (driver_id(driver), str(nr), _now()))


def unclaim(db, driver, nr):
    init(db)
    db.execute("DELETE FROM co_driver_claims WHERE driver_id=? AND order_nr=?",
               (driver_id(driver), str(nr)))


def claims_for(db, driver):
    init(db)
    return {row[0] for row in db.execute(
        "SELECT order_nr FROM co_driver_claims WHERE driver_id=?",
        (driver_id(driver),))}


def claimants(db, nr):
    init(db)
    return [row[0] for row in db.execute(
        "SELECT driver_id FROM co_driver_claims WHERE order_nr=? ORDER BY driver_id",
        (str(nr),))]


def claimants_bulk(db, order_numbers):
    """Return claimants per order in bounded SQLite batches.

    Equivalent to calling claimants() for every order, but avoids N database
    round trips on each Streamlit rerun.
    """
    numbers = sorted({str(nr) for nr in order_numbers if str(nr)})
    if not numbers:
        return {}
    init(db)
    result = {}
    for offset in range(0, len(numbers), 400):
        batch = numbers[offset:offset + 400]
        placeholders = ",".join("?" for _ in batch)
        for nr, driver in db.execute(
            "SELECT order_nr,driver_id FROM co_driver_claims "
            f"WHERE order_nr IN ({placeholders}) ORDER BY order_nr,driver_id",
            tuple(batch),
        ):
            result.setdefault(nr, []).append(driver)
    return result


def address_key(raw):
    return " ".join(str(raw or "").casefold().strip().split())


def validate_coords(lat, lon):
    lat, lon = float(lat), float(lon)
    if not (math.isfinite(lat) and math.isfinite(lon)
            and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Ungültige Koordinaten")
    return lat, lon


def save_location(db, raw_address, lat, lon):
    key = address_key(raw_address)
    if not key:
        raise ValueError("Adresse fehlt")
    lat, lon = validate_coords(lat, lon)
    init(db)
    db.execute("""INSERT INTO location_overrides(address_key,lat,lon,updated_at)
        VALUES(?,?,?,?) ON CONFLICT(address_key) DO UPDATE SET
        lat=excluded.lat,lon=excluded.lon,updated_at=excluded.updated_at""",
        (key, lat, lon, _now()))


def get_location(db, raw_address):
    key = address_key(raw_address)
    if not key:
        return None
    init(db)
    rows = db.execute(
        "SELECT lat,lon FROM location_overrides WHERE address_key=?", (key,))
    return tuple(rows[0]) if rows else None


def get_locations_bulk(db, raw_addresses):
    """Read all confirmed locations with one query per SQLite parameter batch.

    Same normalized address keys and semantics as get_location(); no changes
    to zone boundaries, precedence or geocoding decisions.
    """
    keys = sorted({address_key(raw) for raw in raw_addresses if address_key(raw)})
    if not keys:
        return {}
    init(db)
    found = {}
    for offset in range(0, len(keys), 400):
        batch = keys[offset:offset + 400]
        placeholders = ",".join("?" for _ in batch)
        for key, lat, lon in db.execute(
            f"SELECT address_key,lat,lon FROM location_overrides "
            f"WHERE address_key IN ({placeholders})", tuple(batch)
        ):
            found[key] = (lat, lon)
    return found


def audit(orders, *, standby_check=None, manual_ids=None, claim_map=None):
    """Deterministic findings; no speculative overtime auto-payments."""
    manual_ids = set(manual_ids or ())
    claim_map = claim_map or {}
    findings = []
    seen = set()
    for order in orders:
        nr = str(order.get("nr") or "")
        if not nr:
            continue
        issues = []
        if nr in seen:
            issues.append(("duplicate", "Doppelte Auftragsnummer"))
        seen.add(nr)
        if order.get("zone_warning"):
            issues.append(("zone", "FP-Zone / Standort nicht sicher geprüft"))
        amount = float(order.get("betrag") or 0)
        if amount < 0:
            issues.append(("negative", "Negativer Provisionsbetrag"))
        if amount == 0 and "storno" not in str(order.get("stat") or "").lower():
            issues.append(("zero", "0 € ohne eindeutiges Storno"))
        if amount > 300:
            issues.append(("high", "Ungewöhnlich hoher Betrag"))
        if standby_check is not None and nr not in manual_ids and not standby_check(order):
            issues.append(("outside", "Außerhalb Bereitschaft – manuelle Freigabe prüfen"))
        if len(claim_map.get(nr, [])) > 1:
            issues.append(("shared", "Gemeinsamer Einsatz – Fahrerzuordnung prüfen"))
        for code, description in issues:
            findings.append((nr, code, description))
    return findings


def decisions(db, driver):
    init(db)
    return {(nr, code): status for nr, code, status in db.execute(
        "SELECT order_nr,issue_code,status FROM audit_decisions WHERE driver_id=?",
        (driver_id(driver),))}


def set_decision(db, driver, nr, code, status):
    if status not in ("Offen", "Geprüft", "Ignoriert"):
        raise ValueError("Ungültiger Prüfstatus")
    init(db)
    db.execute("""INSERT INTO audit_decisions(driver_id,order_nr,issue_code,status,updated_at)
        VALUES(?,?,?,?,?) ON CONFLICT(driver_id,order_nr,issue_code)
        DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at""",
        (driver_id(driver), str(nr), code, status, _now()))


def prune(db, today=None):
    """Purge stale driver claims and audit decisions when orders are pruned.

    No deletion of live order references. The order table is the authority.
    """
    init(db)
    db.execute("""DELETE FROM co_driver_claims
        WHERE order_nr NOT IN (SELECT order_key FROM monthly_orders)""")
    db.execute("""DELETE FROM audit_decisions
        WHERE order_nr NOT IN (SELECT order_key FROM monthly_orders)""")

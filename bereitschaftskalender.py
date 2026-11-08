"""Persistent planning calendar. Does not alter the billing/standby rules."""
from datetime import date, timedelta


def friday_for(value):
    if isinstance(value, str):
        value = date.fromisoformat(value)
    return value + timedelta(days=(4 - value.weekday()) % 7)


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS standby_assignments (
        friday TEXT NOT NULL,
        driver TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(friday, driver)
    )""")


def assignments(db, first=None, last=None):
    init(db)
    sql = "SELECT friday, driver, note FROM standby_assignments"
    params = []
    conditions = []
    if first is not None:
        conditions.append("friday >= ?")
        params.append(first.isoformat() if hasattr(first, "isoformat") else str(first))
    if last is not None:
        conditions.append("friday <= ?")
        params.append(last.isoformat() if hasattr(last, "isoformat") else str(last))
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    return [dict(friday=f, driver=d, note=n)
            for f, d, n in db.execute(sql + " ORDER BY friday, driver", params)]


def assign(db, friday, driver, note=""):
    init(db)
    friday = friday_for(friday).isoformat()
    driver = str(driver).strip()
    if not driver or driver == "Alle Fahrer":
        raise ValueError("Bitte einen konkreten Fahrer auswählen")
    db.execute("""INSERT INTO standby_assignments(friday,driver,note)
        VALUES(?,?,?) ON CONFLICT(friday,driver) DO UPDATE SET note=excluded.note""",
        (friday, driver, str(note).strip()))
    return friday


def unassign(db, friday, driver):
    init(db)
    friday = friday_for(friday).isoformat()
    db.execute("DELETE FROM standby_assignments WHERE friday=? AND driver=?",
               (friday, str(driver).strip()))


def overlaps(rows):
    """Multiple drivers on one weekend: review rather than auto-reject."""
    by_friday = {}
    for row in rows:
        by_friday.setdefault(row["friday"], set()).add(row["driver"])
    return {f: sorted(names) for f, names in by_friday.items() if len(names) > 1}

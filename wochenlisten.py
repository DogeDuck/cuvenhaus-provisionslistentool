"""Saubere Trennung der Provisionslisten je Fahrer und Kalenderwoche.

Jede Abrechnungswoche (Mo–So) gehört zum Freitag dieser Woche.
Automatische Bereitschaft bleibt ausschließlich Fr 21:00 bis So 21:00.
Andere Einsätze der betreffenden Woche können manuell ergänzt werden.
"""
from datetime import date, datetime, timedelta


def friday_of_week(day):
    """Der Freitag in derselben Montag-bis-Sonntag-Kalenderwoche."""
    if isinstance(day, datetime):
        day = day.date()
    return day + timedelta(days=4 - day.weekday())


def billing_week_bounds(friday):
    """Mo 00:00 inklusive bis nächsten Mo 00:00 exklusiv."""
    monday = friday - timedelta(days=4)
    start = datetime.combine(monday, datetime.min.time())
    return start, start + timedelta(days=7)


def in_billing_week(order, friday):
    dt = order.get("dt")
    if not isinstance(dt, datetime):
        return False
    start, end = billing_week_bounds(friday)
    return start <= dt < end


def available_weekends(orders, today=None):
    """Eine auswählbare Wochenendliste für jede vorhandene Abrechnungswoche."""
    fridays = {
        friday_of_week(o["dt"])
        for o in orders
        if isinstance(o.get("dt"), datetime)
    }
    if not fridays:
        fridays.add(friday_of_week(today or date.today()))
    return sorted(fridays, reverse=True)


def scope_key(driver, friday):
    return f"{' '.join(str(driver).casefold().split())}|{friday.isoformat()}"


def get_scope(scopes, driver, friday):
    """Mutierbare Werte werden nur für die gewählte Fahrer-/Wochenliste geteilt."""
    key = scope_key(driver, friday)
    if key not in scopes:
        scopes[key] = {
            "manual_added": set(),
            "removed_orders": set(),
            "storno_orders": set(),
            "manual_zones": {},
            "manual_tariffs": {},
        }
    return key, scopes[key]


def other_manual_weekend(scopes, driver, friday, number):
    """Verhindert dieselbe manuelle Provision in zwei Wochen eines Fahrers."""
    if driver == "Alle Fahrer":
        return None
    current = scope_key(driver, friday)
    prefix = scope_key(driver, friday).rsplit("|", 1)[0] + "|"
    for key, state in scopes.items():
        if key != current and key.startswith(prefix):
            if number in state["manual_added"] and number not in state["removed_orders"]:
                return date.fromisoformat(key.rsplit("|", 1)[1])
    return None

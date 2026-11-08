"""Additional review-only alerts; never modify a provision amount."""
from csv_versionsvergleich import duplicate_ids


def import_alerts(orders, version_diff=None, duplicate_numbers=()):
    findings = []
    for nr in sorted(set(duplicate_numbers)):
        findings.append((nr, "csv_duplicate", "Auftragsnummer mehrfach in der CSV"))
    if version_diff:
        for nr, changes in version_diff["geaendert"].items():
            fields = ", ".join(changes)
            findings.append((nr, "csv_changed", "OnStreet-Änderung: " + fields))
        # A missing row in a partial export is NOT a deleted order.
        for nr in version_diff["fehlt_im_export"]:
            findings.append((nr, "csv_missing",
                             "Im aktuellen CSV-Ausschnitt nicht enthalten (nicht gelöscht)"))
    return findings


def price_alert(order, zone_rates, manual_override=False):
    """Warn only on unexplained price differences for normal ADAC jobs."""
    zone = order.get("final_zone")
    expected = zone_rates.get(zone)
    if expected is None or manual_override:
        return None
    tariff = str(order.get("tarif") or "").lower()
    if "storno" in tariff or "storno" in str(order.get("stat") or "").lower():
        return None
    amount = float(order.get("betrag") or 0)
    if abs(amount - expected) > 0.009:
        return (str(order.get("nr") or ""), "price_mismatch",
                f"FP-Tarif {zone}: erwartet {expected:.2f} €, angezeigt {amount:.2f} €")
    return None

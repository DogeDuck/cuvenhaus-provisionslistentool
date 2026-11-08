"""Side-effect-free comparison of OnStreet CSV versions.

Only raw OnStreet source fields are compared; derived tariffs, geocoding and
manual driver/zone overrides must not create false changes.
"""
from collections import Counter

SOURCE_FIELDS = ("raw_nr", "fahrer", "stat", "annahme", "kfz", "ag", "art", "start", "ziel")


def snapshot(order):
    return {field: str(order.get(field) or "").strip() for field in SOURCE_FIELDS}


def compare_versions(previous, incoming):
    """Return changed, new and missing IDs without mutating either input."""
    before = {str(k): snapshot(v) for k, v in previous.items()}
    after = {str(k): snapshot(v) for k, v in incoming.items()}
    new = sorted(set(after) - set(before))
    missing = sorted(set(before) - set(after))
    changed = {}
    for nr in sorted(set(before) & set(after)):
        diffs = {
            field: (before[nr][field], after[nr][field])
            for field in SOURCE_FIELDS
            if before[nr][field] != after[nr][field]
        }
        if diffs:
            changed[nr] = diffs
    return {"neu": new, "fehlt_im_export": missing, "geaendert": changed,
            "unveraendert": len(set(before) & set(after)) - len(changed)}


def duplicate_ids(rows):
    counts = Counter(str(o.get("nr") or "").strip() for o in rows)
    return sorted(nr for nr, count in counts.items() if nr and count > 1)

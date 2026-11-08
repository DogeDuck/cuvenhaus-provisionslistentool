"""Side-effect-free comparison of OnStreet CSV versions.

Only raw OnStreet source fields are compared; derived tariffs, geocoding and
manual driver/zone overrides must not create false changes.
"""
from collections import Counter
import csv
import io
import re

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


def duplicate_csv_numbers(raw_bytes):
    """Detect duplicate OnStreet IDs before the existing importer deduplicates."""
    content = raw_bytes.decode("utf-8-sig", errors="ignore")
    lines = [line for line in content.splitlines() if line.strip()]
    if not lines:
        return []
    delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","
    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    headers = [str(h).strip().casefold() for h in next(reader, ())]
    nr_col = next((i for i, h in enumerate(headers)
                   if "auftrag" in h or "vorgang" in h), None)
    if nr_col is None:
        return []
    ids = []
    for row in reader:
        if nr_col >= len(row):
            continue
        raw = row[nr_col].strip()
        if not raw:
            continue
        match = re.match(r"^\s*(\d+)", raw)
        ids.append({"nr": match.group(1) if match else raw.split()[0]})
    return duplicate_ids(ids)

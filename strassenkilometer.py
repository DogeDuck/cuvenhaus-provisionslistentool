"""OnStreet road kilometre references.

No guessed GPS coordinates: a road reference needs verified survey/road data.
"""
import re

ROAD_RE = re.compile(
    r"(?<![A-Z0-9])(?P<road>[ABLK]\\s*\\d{1,4})"
    r"(?:\\s*-\\s*(?P<section>\\d{1,3}))?"
    r"\\s+(?P<start>\\d{1,4}[.,]\\d{1,3})"
    r"\\s*-\\s*(?P<end>\\d{1,4}[.,]\\d{1,3})"
    r"(?![\\d.,])", re.I
)


def parse_road_reference(raw):
    """Recognize references like 'B42-5 1.5-1.8' without interpreting '-5'."""
    match = ROAD_RE.search(str(raw or ""))
    if not match:
        return None
    start = float(match.group("start").replace(",", "."))
    end = float(match.group("end").replace(",", "."))
    if end < start or end - start > 20:
        return None
    road = re.sub(r"\\s+", "", match.group("road")).upper()
    return {
        "road": road,
        "section": match.group("section"),
        "km_start": start,
        "km_end": end,
        "label": f"{road}" + (f"-{match.group('section')}" if match.group("section") else "")
                 + f" km {start:g}–{end:g}",
    }

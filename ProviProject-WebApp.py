import csv
import hashlib
import html
import io
import json
import os
import re
import sqlite3
import threading
import time
import unicodedata
from datetime import datetime, date, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import pandas as pd
import streamlit as st

# ============================================================
# OPTIONALES PDF-MODUL
# ============================================================
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False


# ============================================================
# STREAMLIT
# ============================================================
st.set_page_config(
    page_title="Cuvenhaus Provision",
    page_icon="🚜",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
    .block-container {
        padding-top: 1.0rem;
        padding-bottom: 1.5rem;
        max-width: 1900px;
    }

    html, body, [class*="css"] {
        font-size: 14px;
    }

    h1 {
        font-size: 1.75rem !important;
        margin-bottom: 0.3rem !important;
    }

    h2, h3 {
        margin-top: 0.4rem !important;
        margin-bottom: 0.4rem !important;
    }

    div[data-testid="stMetric"] {
        padding: 0.35rem 0.5rem;
    }

    div[data-testid="stMetricValue"] {
        font-size: 1.45rem;
    }

    div[data-testid="stVerticalBlock"] {
        gap: 0.45rem;
    }

    .stButton button {
        min-height: 2.2rem;
    }

    .small-note {
        color: #777;
        font-size: 0.78rem;
    }

    .zone-ok {
        font-weight: 600;
    }

    .zone-warning {
        font-weight: 600;
    }

    div[data-testid="stDataFrame"] {
        font-size: 12px;
    }
</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# KONSTANTEN
# ============================================================
APP_DIR = os.path.dirname(os.path.abspath(__file__))
GEOCODE_DB = os.path.join(APP_DIR, "geocode_cache.db")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = (
    "Cuvenhaus-ProvisionsManager/1.0 "
    "(internal employee tool; geocoding for provision calculation)"
)

SUCCESS_TTL_SECONDS = 180 * 24 * 60 * 60
NOT_FOUND_TTL_SECONDS = 24 * 60 * 60
NOMINATIM_MIN_INTERVAL = 1.05
ADDRESS_NORMALIZER_VERSION = "v3"

GEOCODE_LOCK = threading.Lock()
LAST_NOMINATIM_REQUEST = 0.0

ZONE_RANK = {
    "FP 1": 1,
    "FP 2": 2,
    "FP 3": 3,
}

ZONE_RATE = {
    "FP 1": 25.00,
    "FP 2": 30.00,
    "FP 3": 35.00,
}

ZONE_LABEL = {
    "FP 1": "FP1",
    "FP 2": "FP2",
    "FP 3": "FP3",
}

TARIFFS = [
    ("ADAC FP 1 (25,00 €)", "ADAC FP 1", 25.00),
    ("ADAC FP 2 (30,00 €)", "ADAC FP 2", 30.00),
    ("ADAC FP 3 (35,00 €)", "ADAC FP 3", 35.00),
    ("ADAC FP 1 Fehlfahrt (25,00 €)", "ADAC FP 1 Fehlfahrt", 25.00),
    ("ADAC FP 2 Fehlfahrt (30,00 €)", "ADAC FP 2 Fehlfahrt", 30.00),
    ("ADAC FP 3 Fehlfahrt (35,00 €)", "ADAC FP 3 Fehlfahrt", 35.00),
    ("ADAC Pickup WE (20,00 €/h)", "ADAC Pickup WE", 20.00),
    ("Stadt Bonn Voll/Vers. (30,00 €)", "Stadt Bonn Voll/Vers.", 30.00),
    ("Stadt Bonn Leerfahrt (30,00 €)", "Stadt Bonn Leer", 30.00),
    ("Polizei Bonn (30,00 €)", "Polizei Bonn", 30.00),
    ("Polizei Siegburg (30,00 €)", "Polizei Siegburg", 30.00),
    ("Parknotruf Voll (40,00 €)", "Parknotruf Voll", 40.00),
    ("Parknotruf Leer (10,00 €)", "Parknotruf Leer", 10.00),
    ("Falschparker privat (30,00 €)", "Falschparker privat", 30.00),
    ("Selbstzahler (30,00 €)", "Selbstzahler", 30.00),
    (
        "Sonstiges: Werkstatt / Leihwagen (50,00 €)",
        "Werkstatt/Leihwagen",
        50.00,
    ),
]


# ============================================================
# ECHTE ONSTREET-GEOFENCES
# Format: [Breitengrad, Längengrad]
# ============================================================

FP3_POINTS = [
    [50.874306, 6.915825],
    [50.862495, 6.876804],
    [50.851502, 6.836031],
    [50.782071, 6.818229],
    [50.781125, 6.801363],
    [50.753600, 6.801179],
    [50.752904, 6.825427],
    [50.714058, 6.847638],
    [50.671057, 6.875972],
    [50.602513, 6.915761],
    [50.581068, 6.994412],
    [50.552566, 7.094468],
    [50.532287, 7.169196],
    [50.540603, 7.275596],
    [50.569764, 7.372040],
    [50.594187, 7.457722],
    [50.678869, 7.444884],
    [50.729583, 7.437552],
    [50.786818, 7.429033],
    [50.842673, 7.420923],
    [50.899330, 7.416291],
    [50.911256, 7.254920],
    [50.917734, 7.172860],
    [50.917055, 7.131074],
    [50.914866, 7.062492],
    [50.890602, 6.980874],
    [50.897526, 6.964732],
    [50.897558, 6.924642],
    [50.874306, 6.915825],
]

FP2_POINTS = [
    [50.818893, 6.944047],
    [50.796769, 6.902163],
    [50.781762, 6.849481],
    [50.741042, 6.877186],
    [50.718146, 6.907660],
    [50.684914, 6.917703],
    [50.641358, 6.958411],
    [50.627887, 6.984870],
    [50.598921, 7.036144],
    [50.604380, 7.138531],
    [50.607084, 7.218826],
    [50.611442, 7.331522],
    [50.658162, 7.305900],
    [50.692958, 7.252345],
    [50.735564, 7.222828],
    [50.785511, 7.226254],
    [50.828899, 7.191922],
    [50.855783, 7.204977],
    [50.877878, 7.181626],
    [50.887085, 7.093574],
    [50.867372, 7.028152],
    [50.818893, 6.944047],
]

FP1_POINTS = [
    [50.834534, 7.038114],
    [50.823925, 7.010133],
    [50.819370, 7.024709],
    [50.805600, 7.031066],
    [50.794314, 7.029526],
    [50.782923, 7.038800],
    [50.773473, 7.059378],
    [50.756093, 7.100589],
    [50.728727, 7.113995],
    [50.721449, 7.124984],
    [50.717291, 7.116962],
    [50.696553, 7.117609],
    [50.662182, 7.130133],
    [50.641827, 7.157602],
    [50.627812, 7.213391],
    [50.626071, 7.266010],
    [50.672963, 7.281180],
    [50.695567, 7.252347],
    [50.735561, 7.221453],
    [50.783781, 7.229001],
    [50.828906, 7.191240],
    [50.856444, 7.204625],
    [50.847979, 7.075849],
    [50.834534, 7.038114],
]


# ============================================================
# ALLGEMEINE HILFSFUNKTIONEN
# ============================================================

def euro(value):
    return (
        f"{float(value):,.2f} €"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def safe_text(value):
    if value is None:
        return ""
    return str(value).strip()


def format_date_with_weekday(date_str):
    for fmt in ["%d.%m.%Y", "%Y-%m-%d"]:
        try:
            dt = datetime.strptime(safe_text(date_str), fmt)
            days = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
            return f"{days[dt.weekday()]}, {dt.strftime('%d.%m.%Y')}"
        except ValueError:
            pass
    return safe_text(date_str)


def parse_dt(value):
    value = safe_text(value)

    for fmt in [
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d.%m.%Y",
    ]:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass

    return None


def normalize_search_text(value):
    value = safe_text(value).lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_address(value):
    value = safe_text(value)
    if not value:
        return ""
    value = value.replace("\n", " ").replace("\r", " ")
    value = re.sub(r"\s+", " ", value).strip(" ,")
    normalized = normalize_search_text(value)
    normalized = normalized.replace("straße", "strasse")
    normalized = normalized.replace("str.", "strasse")
    normalized = re.sub(r"[^a-z0-9,./\- ]", "", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def comparison_text(value):
    value = normalize_search_text(value)
    value = value.replace("straße", "strasse")
    value = value.replace("str.", "strasse")
    value = re.sub(r"[^a-z0-9]", "", value)
    return value


def smart_city_name(value):
    value = safe_text(value)
    value = re.sub(r"\([^)]{1,8}\)", "", value)
    value = re.sub(r"\b\d{5}\b", "", value)
    value = re.sub(r"\s+", " ", value).strip(" ,")
    if value.isupper():
        value = value.title()
    return value


def smart_street_name(value):
    value = safe_text(value)
    value = re.sub(r"\s+", " ", value).strip(" ,")
    if value.isupper():
        value = value.title()
    return value


def remove_duplicate_fragment(value):
    """Entfernt typische OnStreet-Dopplungen, auch direkt aneinandergeklebt."""
    value = re.sub(r"\s+", " ", safe_text(value)).strip(" ,")
    if not value:
        return ""

    # Exakte doppelte Hälfte: 'ABC 2ABC 2'.
    compact = value.strip()
    n = len(compact)
    for split in range(max(1, n // 2 - 3), min(n, n // 2 + 4)):
        a, b = compact[:split].strip(), compact[split:].strip()
        if a and comparison_text(a) == comparison_text(b):
            return a

    # Doppelte Wortfolge: 'HEINRICH... HEINRICH...'.
    words = compact.split()
    for size in range(len(words) // 2, 0, -1):
        if len(words) >= size * 2:
            a = " ".join(words[:size])
            b = " ".join(words[size:size * 2])
            if comparison_text(a) == comparison_text(b):
                rest = " ".join(words[size * 2:]).strip()
                return (a + (" " + rest if rest else "")).strip()

    # Wiederholung eines längeren Präfixes irgendwo in der zweiten Hälfte.
    normalized = comparison_text(compact)
    if len(normalized) >= 10:
        for i in range(5, len(compact)):
            left = compact[:i].strip()
            right = compact[i:].strip()
            if len(comparison_text(left)) >= 6 and comparison_text(right).startswith(comparison_text(left)):
                return left
    return compact


def clean_onstreet_address(raw):
    """Macht aus OnStreet-Müll eine geocodierbare deutsche Adresse."""
    original = safe_text(raw)
    if not original:
        return {
            "raw": "", "address": "", "street": "", "house_number": "",
            "postal_code": "", "city": "", "has_street": False,
            "has_house_number": False, "is_precise_input": False,
            "warning": "Keine Adresse vorhanden",
        }

    text = original.replace("\n", " ").replace("\r", " ")
    text = re.sub(r"\([^)]{1,8}\)", "", text)  # (BN), (SU) usw.
    text = re.sub(r"\s+", " ", text).strip(" ,")
    parts = [re.sub(r"\s+", " ", p).strip(" ,") for p in text.split(",") if p.strip(" ,")]

    postal_code = ""
    city = ""
    # Der letzte PLZ/Ort-Block ist bei OnStreet meist der sauberste.
    for part in reversed(parts):
        m = re.search(r"\b(\d{5})\b\s*(.*)$", part)
        if m:
            postal_code = m.group(1)
            city_candidate = smart_city_name(m.group(2))
            if city_candidate:
                city = city_candidate
                break

    # Auch ohne PLZ den Ort aus dem letzten Komma-Block übernehmen.
    if not city and len(parts) >= 2:
        tail = smart_city_name(parts[-1])
        if tail and not re.search(r"\d", tail):
            city = tail

    first = parts[0] if parts else text
    first = re.sub(r"^\s*\d{5}\s+", "", first)

    # Führenden Ort aus dem ersten Block entfernen.
    if city:
        city_pat = re.escape(city)
        first = re.sub(rf"^\s*{city_pat}\s+", "", first, flags=re.I)
    else:
        # Häufig: 'Bonn Austr 3...' ohne PLZ. Ersten Ort über den letzten Block erkennen.
        if len(parts) >= 2:
            tail_city = smart_city_name(parts[-1])
            if tail_city:
                city = tail_city
                first = re.sub(rf"^\s*{re.escape(city)}\s+", "", first, flags=re.I)

    first = remove_duplicate_fragment(first)
    unknown_street = bool(re.search(r"unbekannt(?:er|e|es)?\s+stra(?:ss|ß)enname", first, re.I))
    if unknown_street:
        street = ""
    else:
        street = smart_street_name(first)

    # Falls der Ort noch vorne an der Straße hängt, ein zweites Mal entfernen.
    if city and street:
        street = re.sub(rf"^\s*{re.escape(city)}\s+", "", street, flags=re.I).strip()

    hn_match = re.search(r"\b(\d+[a-zA-Z]?(?:\s*[-/]\s*\d+[a-zA-Z]?)?)\b", street)
    house_number = hn_match.group(1).replace(" ", "") if hn_match else ""

    # Nur ein echter Straßenanteil zählt als Straße.
    street_words = comparison_text(street)
    has_street = bool(street and len(street_words) >= 4 and not unknown_street)
    has_house_number = bool(house_number)

    address_parts = []
    if has_street:
        address_parts.append(street)
    locality = " ".join(x for x in [postal_code, city] if x).strip()
    if locality:
        address_parts.append(locality)
    address_parts.append("Deutschland")
    address = ", ".join(address_parts)

    warning = ""
    if unknown_street:
        warning = "Straßenname in OnStreet unbekannt; nur Ort/PLZ verwendbar"
    elif not city:
        warning = "Kein Ort erkannt"
    elif not has_street:
        warning = "Keine brauchbare Straße erkannt"
    elif not has_house_number:
        warning = "Keine Hausnummer; Straßenposition ist nur näherungsweise"

    return {
        "raw": original,
        "address": address,
        "street": street if has_street else "",
        "house_number": house_number,
        "postal_code": postal_code,
        "city": city,
        "has_street": has_street,
        "has_house_number": has_house_number,
        "is_precise_input": bool(has_street and has_house_number and city),
        "warning": warning,
    }


def address_cache_key(address):
    normalized = normalize_address(address)
    payload = f"{ADDRESS_NORMALIZER_VERSION}|{normalized}|de"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def is_storno_order(stat, art="", nr="", ag=""):
    combined = normalize_search_text(
        f"{stat} {art} {nr} {ag}"
    )

    is_fehlfahrt = any(
        x in combined
        for x in ["fehlfahrt", "leerfahrt", " leer "]
    )

    return (
        any(
            x in combined
            for x in [
                "storno",
                "storniert",
                "abgebrochen",
                "widerrufen",
                "annulliert",
                "abgesagt",
            ]
        )
        and not is_fehlfahrt
    )


def is_fehlfahrt_order(stat, art="", nr="", ag=""):
    combined = normalize_search_text(
        f"{stat} {art} {nr} {ag}"
    )

    return any(
        x in combined
        for x in ["fehlfahrt", "leerfahrt", " leer "]
    )


def is_adac_order(ag, art="", nr="", stat=""):
    combined = normalize_search_text(
        f"{ag} {art} {nr} {stat}"
    )
    return "adac" in combined


# ============================================================
# SQLITE-GEOCODING-CACHE
# ============================================================

def get_db_connection():
    conn = sqlite3.connect(GEOCODE_DB, timeout=20, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_geocode_db():
    try:
        with get_db_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS geocode_cache (
                    cache_key TEXT PRIMARY KEY,
                    normalized_address TEXT NOT NULL,
                    original_address TEXT,
                    latitude REAL,
                    longitude REAL,
                    display_name TEXT,
                    status TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    quality TEXT DEFAULT '',
                    details_json TEXT DEFAULT ''
                )
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(geocode_cache)")}
            if "quality" not in columns:
                conn.execute("ALTER TABLE geocode_cache ADD COLUMN quality TEXT DEFAULT ''")
            if "details_json" not in columns:
                conn.execute("ALTER TABLE geocode_cache ADD COLUMN details_json TEXT DEFAULT ''")
            conn.commit()
    except Exception:
        pass


init_geocode_db()


def read_geocode_cache(address, allow_expired=False):
    key = address_cache_key(address)
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM geocode_cache WHERE cache_key = ?", (key,)).fetchone()
    except Exception:
        return None
    if not row:
        return None
    age = time.time() - float(row["updated_at"])
    ttl = SUCCESS_TTL_SECONDS if row["status"] == "OK" else NOT_FOUND_TTL_SECONDS
    expired = age > ttl
    if expired and not allow_expired:
        return None
    try:
        details = json.loads(row["details_json"] or "{}")
    except Exception:
        details = {}
    return {
        "status": row["status"], "lat": row["latitude"], "lon": row["longitude"],
        "display_name": row["display_name"] or "", "address": row["original_address"] or address,
        "normalized_address": row["normalized_address"], "cached": True, "expired": expired,
        "quality": row["quality"] or "", "details": details,
    }


def write_geocode_cache(address, status, lat=None, lon=None, display_name="", quality="", details=None):
    key = address_cache_key(address)
    try:
        with get_db_connection() as conn:
            conn.execute("""
                INSERT INTO geocode_cache (
                    cache_key, normalized_address, original_address, latitude, longitude,
                    display_name, status, updated_at, quality, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    normalized_address=excluded.normalized_address,
                    original_address=excluded.original_address,
                    latitude=excluded.latitude, longitude=excluded.longitude,
                    display_name=excluded.display_name, status=excluded.status,
                    updated_at=excluded.updated_at, quality=excluded.quality,
                    details_json=excluded.details_json
            """, (
                key, normalize_address(address), address, lat, lon, display_name,
                status, time.time(), quality, json.dumps(details or {}, ensure_ascii=False),
            ))
            conn.commit()
    except Exception:
        pass


def _street_similarity(input_street, details):
    result_street = safe_text(
        details.get("road") or details.get("pedestrian") or details.get("residential")
        or details.get("footway") or details.get("path") or details.get("street")
    )
    a, b = comparison_text(input_street), comparison_text(result_street)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _city_similarity(input_city, details):
    result_city = safe_text(
        details.get("city") or details.get("town") or details.get("village")
        or details.get("municipality") or details.get("suburb")
    )
    a, b = comparison_text(input_city), comparison_text(result_city)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def assess_geocode_quality(cleaned, result):
    details = result.get("address") or {}
    if not cleaned.get("has_street"):
        return "estimated"
    if not _street_similarity(cleaned.get("street", ""), details):
        return "estimated"
    if cleaned.get("city") and not _city_similarity(cleaned.get("city", ""), details):
        return "estimated"
    requested_hn = comparison_text(cleaned.get("house_number", ""))
    returned_hn = comparison_text(details.get("house_number", ""))
    if requested_hn:
        if not returned_hn or requested_hn != returned_hn:
            return "estimated"
        return "exact"
    return "estimated"


def geocode_cleaned_address(cleaned):
    """Sucht eine bereinigte Adresse. Cache zuerst, Nominatim nur wenn nötig."""
    global LAST_NOMINATIM_REQUEST
    address = safe_text(cleaned.get("address"))
    if not address or address == "Deutschland":
        return {"status": "EMPTY", "lat": None, "lon": None, "display_name": "", "cached": False,
                "quality": "unknown", "error": "Keine geocodierbare Adresse"}

    cached = read_geocode_cache(address)
    if cached:
        return cached
    stale = read_geocode_cache(address, allow_expired=True)

    params = {"format": "jsonv2", "limit": 3, "countrycodes": "de", "addressdetails": 1}
    # Strukturierte Suche ist für OnStreet-Adressen stabiler als ein einziger q-String.
    if cleaned.get("has_street") and cleaned.get("city"):
        params["street"] = cleaned["street"]
        params["city"] = cleaned["city"]
        if cleaned.get("postal_code"):
            params["postalcode"] = cleaned["postal_code"]
        params["country"] = "Germany"
    else:
        params["q"] = address

    url = f"{NOMINATIM_URL}?{urlencode(params)}"
    try:
        with GEOCODE_LOCK:
            elapsed = time.monotonic() - LAST_NOMINATIM_REQUEST
            if elapsed < NOMINATIM_MIN_INTERVAL:
                time.sleep(NOMINATIM_MIN_INTERVAL - elapsed)
            request = Request(url, headers={"User-Agent": NOMINATIM_USER_AGENT, "Accept": "application/json"})
            LAST_NOMINATIM_REQUEST = time.monotonic()
            with urlopen(request, timeout=12) as response:
                data = json.loads(response.read().decode("utf-8"))

        if not data:
            write_geocode_cache(address, "NOT_FOUND", quality="unknown")
            return {"status": "NOT_FOUND", "lat": None, "lon": None, "display_name": "", "cached": False,
                    "quality": "unknown", "error": "Adresse nicht gefunden"}

        # Bevorzuge den Treffer, dessen Straße und Ort wirklich passen.
        ranked = []
        for result in data:
            quality = assess_geocode_quality(cleaned, result)
            score = 2 if quality == "exact" else 1
            if _street_similarity(cleaned.get("street", ""), result.get("address") or {}):
                score += 2
            if _city_similarity(cleaned.get("city", ""), result.get("address") or {}):
                score += 1
            ranked.append((score, quality, result))
        ranked.sort(key=lambda x: x[0], reverse=True)
        _, quality, result = ranked[0]
        lat, lon = float(result["lat"]), float(result["lon"])
        display_name = safe_text(result.get("display_name"))
        details = result.get("address") or {}
        write_geocode_cache(address, "OK", lat, lon, display_name, quality, details)
        return {"status": "OK", "lat": lat, "lon": lon, "display_name": display_name,
                "cached": False, "expired": False, "quality": quality, "details": details}

    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        if stale and stale.get("status") == "OK":
            stale["stale"] = True
            stale["error"] = "Geocoder nicht erreichbar; alter Cache-Treffer verwendet"
            return stale
        return {"status": "ERROR", "lat": None, "lon": None, "display_name": "", "cached": False,
                "quality": "unknown", "error": str(exc)}


def geocode_address(address):
    """Kompatibilitätsfunktion für alte Aufrufe."""
    return geocode_cleaned_address(clean_onstreet_address(address))


# ============================================================
# POINT-IN-POLYGON
# ============================================================

def point_on_segment(
    lat,
    lon,
    lat1,
    lon1,
    lat2,
    lon2,
    tolerance=1e-10,
):
    cross = (
        (lon - lon1) * (lat2 - lat1)
        - (lat - lat1) * (lon2 - lon1)
    )

    if abs(cross) > tolerance:
        return False

    dot = (
        (lat - lat1) * (lat2 - lat1)
        + (lon - lon1) * (lon2 - lon1)
    )

    if dot < 0:
        return False

    squared_length = (
        (lat2 - lat1) ** 2
        + (lon2 - lon1) ** 2
    )

    return dot <= squared_length


def point_in_polygon(lat, lon, polygon):
    if not polygon:
        return False

    inside = False
    j = len(polygon) - 1

    for i in range(len(polygon)):
        lat_i, lon_i = polygon[i]
        lat_j, lon_j = polygon[j]

        if point_on_segment(
            lat,
            lon,
            lat_i,
            lon_i,
            lat_j,
            lon_j,
        ):
            return True

        intersects = (
            (lon_i > lon) != (lon_j > lon)
            and lat
            < (
                (lat_j - lat_i)
                * (lon - lon_i)
                / ((lon_j - lon_i) or 1e-15)
                + lat_i
            )
        )

        if intersects:
            inside = not inside

        j = i

    return inside


def detect_zone_from_coordinates(lat, lon):
    if lat is None or lon is None:
        return None

    # Wichtig: kleine/innere Zone zuerst.
    if point_in_polygon(lat, lon, FP1_POINTS):
        return "FP 1"

    if point_in_polygon(lat, lon, FP2_POINTS):
        return "FP 2"

    if point_in_polygon(lat, lon, FP3_POINTS):
        return "FP 3"

    return None


# ============================================================
# ALTE PLZ-/ORTSLOGIK NUR ALS FALLBACK
# ============================================================

def detect_adac_zone_fallback(address):
    text = normalize_search_text(address)

    plz_match = re.search(
        r"\b(5\d{4}|50\d{3}|51\d{3})\b",
        text,
    )
    plz = (
        plz_match.group(1)
        if plz_match
        else ""
    )

    fp3_plz = {
        "53359", "53913", "53919", "50321",
        "50354", "50374", "51503", "53819",
        "53804", "53809", "53567", "53577",
        "53560", "53545", "53424", "53489",
        "53501", "53474", "50996", "50997",
        "50999",
    }

    fp3_places = [
        "rheinbach",
        "swisttal",
        "heimerzheim",
        "odendorf",
        "weilerswist",
        "bruhl",
        "hurth",
        "erftstadt",
        "liblar",
        "rosrath",
        "neunkirchen",
        "seelscheid",
        "much",
        "ruppichteroth",
        "uckerath",
        "blankenberg",
        "buchholz",
        "asbach",
        "neustadt wied",
        "vettelschoss",
        "linz am rhein",
        "linz",
        "remagen",
        "sinzig",
        "grafschaft",
        "neuenahr",
        "ahrweiler",
        "rodenkirchen",
    ]

    if (
        plz in fp3_plz
        or any(p in text for p in fp3_places)
    ):
        return "FP 3"

    fp2_plz = {
        "53111", "53113", "53115", "53117",
        "53119", "53121", "53123", "53125",
        "53127", "53129", "53173", "53175",
        "53177", "53332", "53347", "50389",
        "53721", "53773", "53797", "53340",
        "53343", "53572",
    }

    fp2_places = [
        "siegburg",
        "hennef",
        "bornheim",
        "merten",
        "roisdorf",
        "alfter",
        "oedekoven",
        "witterschlick",
        "wesseling",
        "lohmar",
        "meckenheim",
        "wachtberg",
        "unkel",
        "oberpleis",
        "thomasberg",
        "ittenbach",
        "aegidienberg",
        "duisdorf",
        "endenich",
        "tannenbusch",
        "rottgen",
        "venusberg",
        "godesberg",
        "hardtberg",
    ]

    if (
        plz in fp2_plz
        or any(p in text for p in fp2_places)
    ):
        return "FP 2"

    bonn_fp1_terms = [
        "beuel",
        "geislar",
        "putzchen",
        "holzlar",
        "oberkassel",
        "vilich",
        "mehlem",
        "53225",
        "53227",
        "53229",
        "53179",
    ]

    if (
        "bonn" in text
        and not any(x in text for x in bonn_fp1_terms)
    ):
        return "FP 2"

    return None


# ============================================================
# ZONE EINER ADRESSE
# ============================================================

def resolve_address_zone(address):
    raw = safe_text(address)
    cleaned = clean_onstreet_address(raw)
    if not raw:
        return {"zone": None, "source": "missing", "quality": "unknown", "lat": None, "lon": None,
                "warning": True, "message": "Keine Adresse", "cleaned_address": "", "display_name": ""}

    geo = geocode_cleaned_address(cleaned)
    if geo.get("status") == "OK" and geo.get("lat") is not None and geo.get("lon") is not None:
        zone = detect_zone_from_coordinates(geo["lat"], geo["lon"])
        quality = geo.get("quality") or "estimated"
        if geo.get("stale"):
            quality = "estimated"
        if zone:
            exact = quality == "exact"
            return {
                "zone": zone,
                "source": "cache" if geo.get("cached") else "geocoding",
                "quality": quality, "lat": geo["lat"], "lon": geo["lon"],
                "warning": not exact,
                "message": "Geofence exakt erkannt" if exact else "Koordinate erkannt, Adresse aber nicht hausnummerngenau",
                "cleaned_address": cleaned.get("address", ""), "display_name": geo.get("display_name", ""),
            }
        # Eine echte Koordinate außerhalb aller FP-Flächen darf nicht per PLZ zurück in eine Zone gezwungen werden.
        return {
            "zone": None, "source": "geocoding", "quality": quality, "lat": geo["lat"], "lon": geo["lon"],
            "warning": True, "message": "Koordinate liegt außerhalb der bekannten FP-Geofences",
            "cleaned_address": cleaned.get("address", ""), "display_name": geo.get("display_name", ""),
        }

    fallback = detect_adac_zone_fallback(cleaned.get("address") or raw)
    return {
        "zone": fallback, "source": "fallback" if fallback else "unknown",
        "quality": "estimated" if fallback else "unknown", "lat": None, "lon": None,
        "warning": True,
        "message": "PLZ/Ort nur als Schätzung" if fallback else "Adresse konnte nicht zuverlässig bestimmt werden",
        "cleaned_address": cleaned.get("address", ""), "display_name": "",
    }


def highest_route_zone(start_zone, target_zone):
    valid = [z for z in (start_zone, target_zone) if z in ZONE_RANK]
    if not valid:
        return None
    return max(valid, key=lambda z: ZONE_RANK[z])


def highest_zone(*zones):
    valid = [z for z in zones if z in ZONE_RANK]
    if not valid:
        return None
    return max(valid, key=lambda z: ZONE_RANK[z])


def zone_status_symbol(result):
    quality = result.get("quality")
    if quality == "exact":
        return "✓"
    if quality == "estimated":
        return "~"
    return "⚠"


# ============================================================
# ADAC-AUFTRAG BERECHNEN
# ============================================================

def calculate_adac_order(order, force=False):
    if not is_adac_order(
        order.get("ag", ""),
        order.get("art", ""),
        order.get("raw_nr", ""),
        order.get("stat", ""),
    ):
        return order

    if (
        order.get("geofence_checked")
        and not force
    ):
        return order

    start_address = safe_text(
        order.get("start", "")
    )
    target_address = safe_text(
        order.get("ziel", "")
    )

    start_result = resolve_address_zone(
        start_address
    )

    if target_address:
        target_result = resolve_address_zone(
            target_address
        )
    else:
        target_result = {
            "zone": None,
            "source": "missing",
            "lat": None,
            "lon": None,
            "warning": False,
            "message": "Kein Ziel vorhanden",
        }

    start_zone = start_result.get("zone")
    target_zone = target_result.get("zone")

    auto_zone = highest_route_zone(
        start_zone,
        target_zone,
    )

    manual_zone = order.get("manual_zone")

    final_zone = (
        manual_zone
        if manual_zone in ZONE_RANK
        else auto_zone
    )

    order["start_zone"] = start_zone
    order["target_zone"] = target_zone
    order["auto_zone"] = auto_zone
    order["final_zone"] = final_zone

    order["start_zone_source"] = (
        start_result.get("source", "")
    )
    order["target_zone_source"] = (
        target_result.get("source", "")
    )

    order["start_lat"] = start_result.get("lat")
    order["start_lon"] = start_result.get("lon")
    order["target_lat"] = target_result.get("lat")
    order["target_lon"] = target_result.get("lon")
    order["start_cleaned_address"] = start_result.get("cleaned_address", "")
    order["target_cleaned_address"] = target_result.get("cleaned_address", "")
    order["start_quality"] = start_result.get("quality", "unknown")
    order["target_quality"] = target_result.get("quality", "unknown")
    order["start_message"] = start_result.get("message", "")
    order["target_message"] = target_result.get("message", "")

    order["zone_warning"] = bool(
        start_result.get("warning")
        or (
            target_address
            and target_result.get("warning")
        )
        or not final_zone
    )

    order["geofence_checked"] = True

    if final_zone:
        amount = ZONE_RATE[final_zone]

        fehlfahrt = is_fehlfahrt_order(
            order.get("stat", ""),
            order.get("art", ""),
            order.get("raw_nr", ""),
            order.get("ag", ""),
        )

        if is_storno_order(
            order.get("stat", ""),
            order.get("art", ""),
            order.get("raw_nr", ""),
            order.get("ag", ""),
        ):
            order["tarif"] = "Storno (0 €)"
            order["betrag"] = 0.0

        elif fehlfahrt:
            order["tarif"] = (
                f"ADAC {final_zone} Fehlfahrt"
            )
            order["betrag"] = amount

        else:
            order["tarif"] = (
                f"ADAC {final_zone}"
            )
            order["betrag"] = amount

        start_label = (
            f"{ZONE_LABEL.get(start_zone, '?')} {zone_status_symbol(start_result)}"
            if start_address
            else "-"
        )

        target_label = (
            f"{ZONE_LABEL.get(target_zone, '?')} {zone_status_symbol(target_result)}"
            if target_address
            else "-"
        )

        final_label = ZONE_LABEL.get(
            final_zone,
            "?",
        )

        manual_text = (
            " · manuell"
            if manual_zone
            else ""
        )

        order["zone_text"] = (
            f"Start {start_label} · "
            f"Ziel {target_label} → "
            f"{final_label}{manual_text}"
        )

        order["bemerkung"] = (
            f"{order.get('art', '')} / "
            f"{order['tarif']} "
            f"({order['zone_text']})"
        )

    else:
        order["zone_text"] = (
            "⚠ Zone nicht eindeutig erkannt"
        )

        order["bemerkung"] = (
            f"{order.get('art', '')} / "
            f"⚠ ADAC-Zone prüfen"
        )

    return order


# ============================================================
# NORMALE TARIFLOGIK
# ============================================================

def match_tariff_rule(
    stat,
    ag,
    art,
    nr,
    ort,
):
    ag_l = normalize_search_text(ag)
    art_l = normalize_search_text(art)

    combined = normalize_search_text(
        f"{stat} {art} {nr} {ort}"
    )

    is_fehlfahrt = any(
        k in combined
        for k in [
            "fehlfahrt",
            "leerfahrt",
            " leer ",
        ]
    )

    is_storno = (
        any(
            k in combined
            for k in [
                "storno",
                "storniert",
                "abgebrochen",
                "widerrufen",
                "annulliert",
                "abgesagt",
            ]
        )
        and not is_fehlfahrt
    )

    if is_storno:
        return "Storno (0 €)", 0.00

    if (
        "stadt bonn" in ag_l
        or (
            "stadt" in ag_l
            and "bonn" in ag_l
        )
    ):
        if is_fehlfahrt:
            return "Stadt Bonn Leerfahrt", 30.00
        return "Stadt Bonn Voll/Vers.", 30.00

    if (
        "parknotruf" in ag_l
        or "pnr" in combined
    ):
        if is_fehlfahrt:
            return "Parknotruf Leerfahrt", 10.00
        return "Parknotruf Voll", 40.00

    if (
        "leihwagen" in combined
        or "mietwagen" in combined
        or "gutachten" in combined
        or (
            "werkstatt" in combined
            and "adac" not in combined
        )
    ):
        return (
            "Werkstatt / Gutachten / Leihwagen",
            50.00,
        )

    if "polizei bonn" in ag_l:
        return "Polizei Bonn", 30.00

    if (
        "rhein-sieg" in ag_l
        or "siegburg" in ag_l
        or "kreispolizeibehorde" in ag_l
    ):
        return "Polizei Siegburg", 30.00

    if (
        "falschparker" in art_l
        and "stadt" not in ag_l
    ):
        return "Falschparker privat", 30.00

    if (
        "selbstzahler" in combined
        or "eigener wunsch" in combined
    ):
        return "Selbstzahler", 30.00

    if "adac" in ag_l or "adac" in combined:
        fallback_zone = detect_adac_zone_fallback(
            ort
        )

        if fallback_zone:
            rate = ZONE_RATE[fallback_zone]

            if is_fehlfahrt:
                return (
                    f"ADAC {fallback_zone} Fehlfahrt "
                    f"(geschätzt)",
                    rate,
                )

            return (
                f"ADAC {fallback_zone} "
                f"(geschätzt)",
                rate,
            )

        return "ADAC Zone prüfen", 0.00

    if is_fehlfahrt:
        # Kein bestätigter allgemeiner Tarif vorhanden.
        return "Fehlfahrt – Tarif prüfen", 0.00

    return "Abschleppen / Bereitst.", 25.00


# ============================================================
# BEREITSCHAFT
# ============================================================

def weekend_for_date(d):
    # Freitag derselben Bereitschaftswoche finden.
    days_since_friday = (
        d.weekday() - 4
    ) % 7

    friday = d - timedelta(
        days=days_since_friday
    )

    # Montag bis Donnerstag gehören sinnvollerweise
    # zum folgenden Freitag, wenn man sie im Kalender anklickt.
    if d.weekday() <= 3:
        friday = d + timedelta(
            days=(4 - d.weekday())
        )

    return friday


def standby_bounds(friday):
    start = datetime.combine(
        friday,
        datetime.min.time(),
    ).replace(
        hour=21,
        minute=0,
        second=0,
    )

    sunday = friday + timedelta(days=2)

    end = datetime.combine(
        sunday,
        datetime.min.time(),
    ).replace(
        hour=21,
        minute=0,
        second=0,
    )

    return start, end


def is_in_standby(order, friday):
    dt = order.get("dt")

    if not dt:
        return False

    start, end = standby_bounds(friday)

    return start <= dt <= end


def detect_weekends_from_orders(orders):
    result = set()

    for order in orders:
        dt = order.get("dt")

        if not dt:
            continue

        # Nur Wochenenden aufnehmen, in deren Nähe
        # tatsächlich CSV-Daten liegen.
        friday = dt.date() - timedelta(
            days=(dt.weekday() - 4) % 7
        )

        start, end = standby_bounds(friday)

        if (
            start - timedelta(days=1)
            <= dt
            <= end + timedelta(days=1)
        ):
            result.add(friday)

    return sorted(result)


def weekend_label(friday):
    sunday = friday + timedelta(days=2)

    return (
        f"{friday.strftime('%d.%m.%Y')} – "
        f"{sunday.strftime('%d.%m.%Y')} "
        f"(Fr 21:00 → So 21:00)"
    )


# ============================================================
# PDF
# ============================================================

def generate_pdf_bytes(
    rows,
    driver_name,
    period_str,
):
    buf = io.BytesIO()

    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        rightMargin=25,
        leftMargin=25,
        topMargin=25,
        bottomMargin=25,
    )

    styles = getSampleStyleSheet()

    style_normal = ParagraphStyle(
        "CellNormal",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.0,
        leading=9.5,
    )

    style_center = ParagraphStyle(
        "CellCenter",
        parent=style_normal,
        alignment=1,
    )

    style_right = ParagraphStyle(
        "CellRight",
        parent=style_normal,
        alignment=2,
    )

    style_head = ParagraphStyle(
        "CellHead",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=10,
        alignment=1,
    )

    elements = []

    hdr = Table(
        [[
            Paragraph(
                f"<font size=11><b>Mitarbeiter:</b> "
                f"{html.escape(driver_name)}</font>",
                styles["Normal"],
            ),
            Paragraph(
                f"<font size=11><b>Bereitschaft:</b> "
                f"{html.escape(period_str)}</font>",
                styles["Normal"],
            ),
        ]],
        colWidths=[350, 430],
    )

    hdr.setStyle(
        TableStyle([
            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                8,
            ),
            (
                "ALIGN",
                (1, 0),
                (1, 0),
                "RIGHT",
            ),
        ])
    )

    elements.append(hdr)
    elements.append(Spacer(1, 4))

    headers = [
        Paragraph("<b>DATUM</b>", style_head),
        Paragraph(
            "<b>AUFTRAGS-<br/>NUMMER</b>",
            style_head,
        ),
        Paragraph(
            "<b>KENNZEICHEN</b>",
            style_head,
        ),
        Paragraph(
            "<b>AUFTRAGGEBER</b>",
            style_head,
        ),
        Paragraph(
            "<b>BEMERKUNG</b>",
            style_head,
        ),
        Paragraph(
            "<b>BETRAG</b>",
            style_head,
        ),
    ]

    table_data = [headers]
    total = 0.0

    for row in rows:
        amount = float(
            row.get("betrag", 0.0)
        )
        total += amount

        table_data.append([
            Paragraph(
                html.escape(
                    safe_text(row.get("datum"))
                ),
                style_center,
            ),
            Paragraph(
                html.escape(
                    safe_text(row.get("nr"))
                ),
                style_center,
            ),
            Paragraph(
                html.escape(
                    safe_text(row.get("kfz"))
                ),
                style_center,
            ),
            Paragraph(
                html.escape(
                    safe_text(row.get("ag"))
                ),
                style_normal,
            ),
            Paragraph(
                html.escape(
                    safe_text(
                        row.get("bemerkung")
                    )
                ),
                style_normal,
            ),
            Paragraph(
                euro(amount),
                style_right,
            ),
        ])

    for _ in range(
        max(0, 16 - len(rows))
    ):
        table_data.append(
            ["", "", "", "", "", ""]
        )

    table_data.append([
        "",
        "",
        "",
        "",
        Paragraph(
            "<b>SUMME:</b>",
            style_right,
        ),
        Paragraph(
            f"<b>{euro(total)}</b>",
            style_right,
        ),
    ])

    col_widths = [
        70,
        72,
        90,
        165,
        300,
        83,
    ]

    table = Table(
        table_data,
        colWidths=col_widths,
        repeatRows=1,
    )

    table.setStyle(
        TableStyle([
            (
                "GRID",
                (0, 0),
                (-1, -2),
                0.7,
                colors.black,
            ),
            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "MIDDLE",
            ),
            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                3,
            ),
            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                3,
            ),
            (
                "BOX",
                (4, -1),
                (5, -1),
                0.9,
                colors.black,
            ),
        ])
    )

    elements.append(table)

    doc.build(elements)

    buf.seek(0)
    return buf.getvalue()


# ============================================================
# SESSION STATE
# ============================================================

DEFAULT_STATE = {
    "orders": {},
    "detected_drivers": [],
    "file_hash": "",
    "manual_added": set(),
    "removed_orders": set(),
    "storno_orders": set(),
    "manual_zones": {},
    "manual_tariffs": {},
    "initialized_contexts": set(),
}

for key, default in DEFAULT_STATE.items():
    if key not in st.session_state:
        if isinstance(default, set):
            st.session_state[key] = set()
        elif isinstance(default, dict):
            st.session_state[key] = {}
        elif isinstance(default, list):
            st.session_state[key] = []
        else:
            st.session_state[key] = default


# ============================================================
# CSV IMPORT
# ============================================================

def find_header_index(headers, candidates):
    # Erst exakte Treffer.
    for candidate in candidates:
        candidate = candidate.lower()

        for i, header in enumerate(headers):
            if header == candidate:
                return i

    # Danach Teiltreffer.
    for candidate in candidates:
        candidate = candidate.lower()

        for i, header in enumerate(headers):
            if candidate in header:
                return i

    return None


def cell(row, idx):
    if idx is None:
        return ""

    if idx >= len(row):
        return ""

    return safe_text(row[idx])


def import_csv_bytes(raw_bytes):
    content = raw_bytes.decode(
        "utf-8-sig",
        errors="ignore",
    )

    lines = [
        line
        for line in content.splitlines()
        if line.strip()
    ]

    if len(lines) < 2:
        return {}, [], []

    delimiter = (
        ";"
        if lines[0].count(";")
        > lines[0].count(",")
        else ","
    )

    reader = csv.reader(
        lines,
        delimiter=delimiter,
    )

    rows = list(reader)

    headers = [
        safe_text(h).lower()
        for h in rows[0]
    ]

    idx_stat = find_header_index(
        headers,
        ["aktueller status", "status"],
    )

    idx_nr = find_header_index(
        headers,
        ["auftrag", "vorgang"],
    )

    idx_fahrer = find_header_index(
        headers,
        ["fahrer", "mitarbeiter"],
    )

    idx_annahme = find_header_index(
        headers,
        ["annahme", "datum"],
    )

    idx_kfz = find_header_index(
        headers,
        ["kennzeichen", "kfz"],
    )

    idx_ag = find_header_index(
        headers,
        ["auftraggeber", "kunde"],
    )

    idx_art = find_header_index(
        headers,
        ["auftragsart", "leistung"],
    )

    idx_start = find_header_index(
        headers,
        [
            "einsatzort",
            "startort",
            "übernahmeort",
            "uebernahmeort",
        ],
    )

    idx_ziel = find_header_index(
        headers,
        [
            "zielort",
            "abladeort",
            "verbringungsort",
        ],
    )

    orders = {}
    drivers = set()

    for row in rows[1:]:
        if not any(
            safe_text(x)
            for x in row
        ):
            continue

        raw_nr = cell(row, idx_nr)

        if not raw_nr:
            continue

        nr_match = re.match(
            r"^\s*(\d+)",
            raw_nr,
        )

        nr = (
            nr_match.group(1)
            if nr_match
            else raw_nr.split()[0]
        )

        stat = cell(row, idx_stat)
        fahrer = cell(row, idx_fahrer)
        annahme = cell(row, idx_annahme)
        raw_kfz = cell(row, idx_kfz)
        ag = cell(row, idx_ag)
        art = cell(row, idx_art)
        start = cell(row, idx_start)
        ziel = cell(row, idx_ziel)

        kfz_clean = re.sub(
            r"\(.*?\)",
            "",
            raw_kfz,
        ).strip()

        if not kfz_clean:
            kfz_clean = (
                "OHNE"
                if "ohne" in raw_kfz.lower()
                else "-"
            )

        dt = parse_dt(annahme)

        if dt:
            datum = dt.strftime("%d.%m.%Y")
            zeit = dt.strftime("%H:%M")
        else:
            datum = annahme
            zeit = ""

        tarif, betrag = match_tariff_rule(
            stat,
            ag,
            art,
            raw_nr,
            start,
        )

        order = {
            "nr": nr,
            "raw_nr": raw_nr,
            "fahrer": fahrer,
            "stat": stat,
            "annahme": annahme,
            "dt": dt,
            "datum": datum,
            "zeit": zeit,
            "kfz": kfz_clean,
            "ag": ag,
            "art": art,
            "start": start,
            "ziel": ziel,
            "route": start,
            "tarif": tarif,
            "betrag": float(betrag),
            "bemerkung": (
                f"{art} / {tarif}"
                if tarif not in art
                else art
            ),
            "start_zone": None,
            "target_zone": None,
            "auto_zone": None,
            "final_zone": None,
            "zone_text": "",
            "zone_warning": False,
            "geofence_checked": False,
            "manual_zone": None,
        }

        orders[nr] = order

        if fahrer:
            drivers.add(fahrer)

    return (
        orders,
        sorted(drivers),
        headers,
    )


# ============================================================
# HEADER / UPLOAD
# ============================================================

st.title("🚜 Cuvenhaus Provisions-Manager")

uploaded_file = st.file_uploader(
    "📂 OnStreet-CSV auswählen",
    type=["csv"],
)

if uploaded_file is not None:
    raw = uploaded_file.getvalue()

    current_hash = hashlib.sha256(
        raw
    ).hexdigest()

    if (
        st.session_state.file_hash
        != current_hash
    ):
        orders, drivers, headers = (
            import_csv_bytes(raw)
        )

        st.session_state.orders = orders
        st.session_state.detected_drivers = drivers
        st.session_state.file_hash = current_hash

        st.session_state.manual_added = set()
        st.session_state.removed_orders = set()
        st.session_state.storno_orders = set()
        st.session_state.manual_zones = {}
        st.session_state.manual_tariffs = {}
        st.session_state.initialized_contexts = set()

        st.rerun()


if not st.session_state.orders:
    st.info(
        "Bitte oben den OnStreet-CSV-Export auswählen."
    )
    st.stop()


# ============================================================
# FAHRER + BEREITSCHAFT
# ============================================================

all_orders = list(
    st.session_state.orders.values()
)

driver_options = (
    ["Alle Fahrer"]
    + st.session_state.detected_drivers
)

default_driver_idx = 0

for i, driver in enumerate(
    driver_options
):
    d = driver.lower()

    if (
        "can-erik" in d
        or "can erik" in d
        or "ross" in d
    ):
        default_driver_idx = i
        break


top1, top2, top3 = st.columns(
    [1.2, 1.6, 1.4]
)

with top1:
    active_driver = st.selectbox(
        "👤 Fahrer",
        driver_options,
        index=default_driver_idx,
    )


driver_orders = [
    order
    for order in all_orders
    if (
        active_driver == "Alle Fahrer"
        or normalize_search_text(
            active_driver
        )
        in normalize_search_text(
            order.get("fahrer", "")
        )
    )
]


weekends = detect_weekends_from_orders(
    driver_orders
)

if not weekends:
    default_friday = weekend_for_date(
        date.today()
    )
    weekends = [default_friday]


with top2:
    weekend_options = {
        weekend_label(friday): friday
        for friday in weekends
    }

    selected_weekend_label = st.selectbox(
        "📅 Bereitschaftswochenende",
        list(weekend_options.keys()),
    )

    selected_friday = weekend_options[
        selected_weekend_label
    ]


with top3:
    calendar_day = st.date_input(
        "Anderes Wochenende wählen",
        value=selected_friday,
        help=(
            "Einen Tag auswählen. "
            "Die App setzt automatisch das "
            "zugehörige Bereitschaftswochenende."
        ),
    )

    calendar_friday = weekend_for_date(
        calendar_day
    )

    if calendar_friday != selected_friday:
        selected_friday = calendar_friday


standby_start, standby_end = (
    standby_bounds(selected_friday)
)

st.caption(
    "Bereitschaft: "
    f"{standby_start.strftime('%d.%m.%Y %H:%M')} "
    "bis "
    f"{standby_end.strftime('%d.%m.%Y %H:%M')} "
    "· Zeitbasis dieses CSV: Annahme"
)


# ============================================================
# AUTOMATISCHE BEREITSCHAFT INITIALISIEREN
# ============================================================

context_key = (
    f"{active_driver}|"
    f"{selected_friday.isoformat()}|"
    f"{st.session_state.file_hash}"
)

if (
    context_key
    not in st.session_state.initialized_contexts
):
    for order in driver_orders:
        nr = order["nr"]

        if (
            is_in_standby(
                order,
                selected_friday,
            )
            and not is_storno_order(
                order.get("stat", ""),
                order.get("art", ""),
                order.get("raw_nr", ""),
                order.get("ag", ""),
            )
        ):
            if (
                nr
                not in st.session_state.removed_orders
            ):
                st.session_state.manual_added.add(
                    nr
                )

    st.session_state.initialized_contexts.add(
        context_key
    )


# ============================================================
# MANUELLE SUCHE
# ============================================================

st.markdown("#### 🔎 Auftrag manuell hinzufügen")

search_col, add_col = st.columns(
    [5, 1]
)

with search_col:
    search_input = st.text_input(
        "Kennzeichen oder Auftragsnummer",
        placeholder=(
            "z. B. 26945 oder SU-LC1517"
        ),
        label_visibility="collapsed",
    )


search_matches = []

if search_input.strip():
    q = normalize_search_text(
        search_input
    )

    for order in all_orders:
        haystack = normalize_search_text(
            f"{order.get('nr', '')} "
            f"{order.get('raw_nr', '')} "
            f"{order.get('kfz', '')}"
        )

        if q in haystack:
            search_matches.append(order)


with add_col:
    if st.button(
        "➕ Hinzufügen",
        use_container_width=True,
        disabled=not bool(search_matches),
    ):
        if len(search_matches) == 1:
            target = search_matches[0]

            st.session_state.manual_added.add(
                target["nr"]
            )

            st.session_state.removed_orders.discard(
                target["nr"]
            )

            st.rerun()


if search_input.strip():
    if not search_matches:
        st.warning(
            "Kein Auftrag mit dieser Nummer "
            "oder diesem Kennzeichen gefunden."
        )

    elif len(search_matches) == 1:
        match = search_matches[0]

        already = (
            match["nr"]
            in st.session_state.manual_added
        )

        st.caption(
            f"Treffer: Auftrag {match['nr']} · "
            f"{match['kfz']} · "
            f"{match['fahrer']} · "
            f"{match['datum']} {match['zeit']}"
            + (
                " · bereits provisioniert"
                if already
                else ""
            )
        )

    else:
        match_labels = [
            (
                f"{o['nr']} | {o['kfz']} | "
                f"{o['fahrer']} | "
                f"{o['datum']} {o['zeit']}"
            )
            for o in search_matches
        ]

        selected_match_label = st.selectbox(
            "Mehrere Treffer gefunden",
            match_labels,
        )

        selected_index = match_labels.index(
            selected_match_label
        )

        selected_match = search_matches[
            selected_index
        ]

        if st.button(
            "Ausgewählten Treffer übernehmen"
        ):
            st.session_state.manual_added.add(
                selected_match["nr"]
            )

            st.session_state.removed_orders.discard(
                selected_match["nr"]
            )

            st.rerun()


# ============================================================
# PROVISIONIERTE AUFTRÄGE
# ============================================================

def belongs_to_active_driver(order):
    if active_driver == "Alle Fahrer":
        return True

    return (
        normalize_search_text(
            active_driver
        )
        in normalize_search_text(
            order.get("fahrer", "")
        )
    )


provisioned_orders = []

for order in all_orders:
    nr = order["nr"]

    if not belongs_to_active_driver(order):
        continue

    if nr not in st.session_state.manual_added:
        continue

    if nr in st.session_state.removed_orders:
        continue

    if (
        nr in st.session_state.manual_zones
    ):
        order["manual_zone"] = (
            st.session_state.manual_zones[nr]
        )

    if is_adac_order(
        order.get("ag", ""),
        order.get("art", ""),
        order.get("raw_nr", ""),
        order.get("stat", ""),
    ):
        calculate_adac_order(order)

    if nr in st.session_state.storno_orders:
        order["betrag"] = 0.0
        order["tarif"] = "Storno (0 €)"
        order["bemerkung"] = "Storno (0 €)"

    if nr in st.session_state.manual_tariffs:
        manual = (
            st.session_state.manual_tariffs[nr]
        )

        order["betrag"] = manual["betrag"]
        order["tarif"] = manual["tarif"]
        order["bemerkung"] = (
            f"{order.get('art', '')} / "
            f"{manual['tarif']} · manuell"
        )

    provisioned_orders.append(order)


provisioned_orders.sort(
    key=lambda x: (
        x.get("dt")
        or datetime.min
    )
)


# ============================================================
# PROBLEMZÄHLER
# ============================================================

problem_orders = [
    o
    for o in provisioned_orders
    if o.get("zone_warning")
]


total_brutto = sum(
    float(o.get("betrag", 0.0))
    for o in provisioned_orders
)

total_netto = total_brutto * 0.60


m1, m2, m3, m4 = st.columns(4)

m1.metric(
    "📋 Touren",
    len(provisioned_orders),
)

m2.metric(
    "💰 Brutto",
    euro(total_brutto),
)

m3.metric(
    "💵 ca. Netto 60 %",
    euro(total_netto),
)

m4.metric(
    "⚠ Prüfen",
    len(problem_orders),
)


# ============================================================
# FILTER
# ============================================================

filter1, filter2 = st.columns(
    [1, 3]
)

with filter1:
    only_problems = st.checkbox(
        "Nur Problemfälle anzeigen"
    )


# ============================================================
# LINKE / RECHTE MONITORANSICHT
# ============================================================

left, right = st.columns(
    [1, 1],
    gap="medium",
)


# ------------------------------------------------------------
# LINKS: ALLE AUFTRÄGE
# ------------------------------------------------------------
with left:
    st.subheader("📥 Alle Aufträge")

    left_orders = [
        o
        for o in driver_orders
        if (
            not only_problems
            or o.get("zone_warning")
        )
    ]

    left_rows = []

    for order in left_orders:
        nr = order["nr"]

        in_provision = (
            nr in st.session_state.manual_added
            and nr
            not in st.session_state.removed_orders
        )

        standby = is_in_standby(
            order,
            selected_friday,
        )

        left_rows.append({
            "✓": "✓" if in_provision else "",
            "Zeit": (
                f"{order['datum']} "
                f"{order['zeit']}"
            ),
            "Auftrag": order["nr"],
            "Kennzeichen": order["kfz"],
            "Auftraggeber": order["ag"],
            "Start": order["start"],
            "Ziel": order["ziel"],
            "Bereitschaft": (
                "JA" if standby else ""
            ),
        })

    if left_rows:
        st.dataframe(
            pd.DataFrame(left_rows),
            use_container_width=True,
            hide_index=True,
            height=520,
        )
    else:
        st.info(
            "Keine Aufträge für diesen Filter."
        )

    st.caption(
        "Nicht automatisch übernommene Touren "
        "können oben jederzeit per Auftragsnummer "
        "oder Kennzeichen hinzugefügt werden."
    )


# ------------------------------------------------------------
# RECHTS: PROVISION
# ------------------------------------------------------------
with right:
    st.subheader("💰 Provision")

    display_orders = [
        o
        for o in provisioned_orders
        if (
            not only_problems
            or o.get("zone_warning")
        )
    ]

    right_rows = []

    for order in display_orders:
        zone_display = (
            order.get("zone_text")
            or order.get("tarif")
            or ""
        )

        if order.get("zone_warning"):
            zone_display = (
                "⚠ " + zone_display
            )

        right_rows.append({
            "Zeit": (
                f"{order['datum']} "
                f"{order['zeit']}"
            ),
            "Auftrag": order["nr"],
            "Kennzeichen": order["kfz"],
            "Zone / Tarif": zone_display,
            "Betrag": euro(
                order.get("betrag", 0.0)
            ),
        })

    if right_rows:
        st.dataframe(
            pd.DataFrame(right_rows),
            use_container_width=True,
            hide_index=True,
            height=360,
        )
    else:
        st.info(
            "Noch keine provisionierten "
            "Aufträge."
        )


# ============================================================
# AUFTRAG BEARBEITEN
# ============================================================

if provisioned_orders:
    st.markdown("#### ✏️ Auftrag bearbeiten")

    edit_labels = [
        (
            f"{o['nr']} | {o['kfz']} | "
            f"{euro(o.get('betrag', 0))}"
        )
        for o in provisioned_orders
    ]

    edit_label = st.selectbox(
        "Auftrag auswählen",
        edit_labels,
        label_visibility="collapsed",
    )

    edit_index = edit_labels.index(
        edit_label
    )

    edit_order = provisioned_orders[
        edit_index
    ]

    edit_nr = edit_order["nr"]

    e1, e2, e3, e4 = st.columns(
        [1, 1, 1, 1]
    )

    with e1:
        if st.button(
            "↩️ Entfernen",
            use_container_width=True,
        ):
            st.session_state.removed_orders.add(
                edit_nr
            )

            st.session_state.manual_added.discard(
                edit_nr
            )

            st.rerun()

    with e2:
        if st.button(
            "🚫 Storno 0 €",
            use_container_width=True,
        ):
            st.session_state.storno_orders.add(
                edit_nr
            )

            st.rerun()

    with e3:
        if st.button(
            "♻️ Storno zurück",
            use_container_width=True,
        ):
            st.session_state.storno_orders.discard(
                edit_nr
            )

            st.rerun()

    with e4:
        if (
            is_adac_order(
                edit_order.get("ag", ""),
                edit_order.get("art", ""),
                edit_order.get("raw_nr", ""),
                edit_order.get("stat", ""),
            )
            and st.button(
                "🌍 Neu prüfen",
                use_container_width=True,
            )
        ):
            edit_order["geofence_checked"] = False

            calculate_adac_order(
                edit_order,
                force=True,
            )

            st.rerun()


    # --------------------------------------------------------
    # ADAC DETAILS / MANUELLE ZONE
    # --------------------------------------------------------
    if is_adac_order(
        edit_order.get("ag", ""),
        edit_order.get("art", ""),
        edit_order.get("raw_nr", ""),
        edit_order.get("stat", ""),
    ):
        def coord_text(lat, lon):
            if lat is None or lon is None:
                return "–"
            return f"{lat:.6f}, {lon:.6f}"

        st.markdown(
            f"**Start (OnStreet):** {edit_order.get('start') or '–'}  \n"
            f"**Start bereinigt:** {edit_order.get('start_cleaned_address') or '–'}  \n"
            f"**Start Koordinate:** {coord_text(edit_order.get('start_lat'), edit_order.get('start_lon'))}  \n"
            f"**Ziel (OnStreet):** {edit_order.get('ziel') or '–'}  \n"
            f"**Ziel bereinigt:** {edit_order.get('target_cleaned_address') or '–'}  \n"
            f"**Ziel Koordinate:** {coord_text(edit_order.get('target_lat'), edit_order.get('target_lon'))}  \n"
            f"**Erkennung:** {edit_order.get('zone_text') or 'noch nicht geprüft'}"
        )

        if edit_order.get("zone_warning"):
            st.warning(
                "Mindestens eine Adresse konnte "
                "nicht sicher über das echte "
                "Geofence bestimmt werden. "
                "Bitte Zone prüfen."
            )

        z1, z2 = st.columns(
            [2, 1]
        )

        current_zone = (
            st.session_state.manual_zones.get(
                edit_nr
            )
            or edit_order.get("final_zone")
            or "FP 1"
        )

        zone_options = [
            "FP 1",
            "FP 2",
            "FP 3",
        ]

        with z1:
            manual_zone = st.selectbox(
                "Manuelle ADAC-Zone",
                zone_options,
                index=zone_options.index(
                    current_zone
                ),
                key=f"zone_{edit_nr}",
            )

        with z2:
            st.write("")
            if st.button(
                "💾 Zone übernehmen",
                use_container_width=True,
                key=f"save_zone_{edit_nr}",
            ):
                st.session_state.manual_zones[
                    edit_nr
                ] = manual_zone

                edit_order["manual_zone"] = (
                    manual_zone
                )

                edit_order[
                    "geofence_checked"
                ] = False

                calculate_adac_order(
                    edit_order,
                    force=True,
                )

                st.rerun()

        if (
            edit_nr
            in st.session_state.manual_zones
        ):
            if st.button(
                "Automatische Zone wieder verwenden",
                key=f"auto_zone_{edit_nr}",
            ):
                del st.session_state.manual_zones[
                    edit_nr
                ]

                edit_order["manual_zone"] = None
                edit_order[
                    "geofence_checked"
                ] = False

                calculate_adac_order(
                    edit_order,
                    force=True,
                )

                st.rerun()


    # --------------------------------------------------------
    # TARIF MANUELL
    # --------------------------------------------------------
    with st.expander(
        "Tarif / Betrag manuell ändern",
        expanded=False,
    ):
        tariff_names = [
            t[0]
            for t in TARIFFS
        ] + ["Freier Betrag..."]

        tariff_choice = st.selectbox(
            "Tarif",
            tariff_names,
            key=f"tariff_choice_{edit_nr}",
        )

        custom_amount = 25.0

        if tariff_choice == "Freier Betrag...":
            custom_amount = st.number_input(
                "Betrag in €",
                min_value=0.0,
                max_value=1000.0,
                value=float(
                    edit_order.get(
                        "betrag",
                        25.0,
                    )
                ),
                step=5.0,
                key=f"custom_amount_{edit_nr}",
            )

        if st.button(
            "💾 Tarif speichern",
            use_container_width=True,
            key=f"save_tariff_{edit_nr}",
        ):
            if tariff_choice == "Freier Betrag...":
                st.session_state.manual_tariffs[
                    edit_nr
                ] = {
                    "tarif": (
                        f"Manuell "
                        f"({custom_amount:.2f} €)"
                    ),
                    "betrag": float(
                        custom_amount
                    ),
                }

            else:
                for (
                    label,
                    short,
                    amount,
                ) in TARIFFS:
                    if label == tariff_choice:
                        st.session_state.manual_tariffs[
                            edit_nr
                        ] = {
                            "tarif": short,
                            "betrag": float(
                                amount
                            ),
                        }
                        break

            st.rerun()

        if (
            edit_nr
            in st.session_state.manual_tariffs
        ):
            if st.button(
                "Manuellen Tarif zurücksetzen",
                key=f"reset_tariff_{edit_nr}",
            ):
                del st.session_state.manual_tariffs[
                    edit_nr
                ]

                edit_order[
                    "geofence_checked"
                ] = False

                if is_adac_order(
                    edit_order.get("ag", ""),
                    edit_order.get("art", ""),
                    edit_order.get(
                        "raw_nr",
                        "",
                    ),
                    edit_order.get("stat", ""),
                ):
                    calculate_adac_order(
                        edit_order,
                        force=True,
                    )

                st.rerun()


# ============================================================
# PROBLEMFÄLLE KOMPAKT
# ============================================================

if problem_orders:
    with st.expander(
        f"⚠ {len(problem_orders)} Auftrag/Aufträge prüfen",
        expanded=False,
    ):
        for order in problem_orders:
            st.write(
                f"**{order['nr']} · {order['kfz']}** — "
                f"{order.get('zone_text', '')}"
            )

            st.caption(
                f"Start: {order.get('start') or '–'} | "
                f"Ziel: {order.get('ziel') or '–'}"
            )


# ============================================================
# EXPORT
# ============================================================

st.markdown("---")
st.subheader("📤 Export & WhatsApp")

driver_title = (
    active_driver
    if active_driver != "Alle Fahrer"
    else "Alle Fahrer"
)

period_title = (
    f"{selected_friday.strftime('%d.%m.%Y')} – "
    f"{(selected_friday + timedelta(days=2)).strftime('%d.%m.%Y')}"
)

wa_lines = [
    f"📋 *Bereitschafts-Abrechnung – {driver_title}*",
    f"📅 {period_title}",
    (
        f"💰 *Gesamt:* "
        f"{len(provisioned_orders)} Touren = "
        f"*{euro(total_brutto)}*"
    ),
    "",
]

for order in provisioned_orders:
    zone_part = (
        f" | {order.get('zone_text')}"
        if order.get("zone_text")
        else ""
    )

    wa_lines.append(
        f"• *{order['nr']}* | "
        f"{order['datum']} {order['zeit']} | "
        f"{order['kfz']} | "
        f"{order['tarif']}"
        f"{zone_part} | "
        f"{euro(order['betrag'])}"
    )

wa_text = "\n".join(
    wa_lines
)


exp1, exp2, exp3 = st.columns(
    [1.5, 1, 1]
)

with exp1:
    st.text_area(
        "WhatsApp-Text",
        value=wa_text,
        height=180,
    )


with exp2:
    if (
        HAS_REPORTLAB
        and provisioned_orders
    ):
        pdf_bytes = generate_pdf_bytes(
            provisioned_orders,
            driver_title,
            period_title,
        )

        st.download_button(
            "📄 PDF herunterladen",
            data=pdf_bytes,
            file_name=(
                "Abrechnung_"
                f"{selected_friday.isoformat()}.pdf"
            ),
            mime="application/pdf",
            use_container_width=True,
        )
    elif not HAS_REPORTLAB:
        st.warning(
            "ReportLab fehlt. "
            "PDF-Export ist nicht verfügbar."
        )


with exp3:
    csv_buf = io.StringIO()

    writer = csv.writer(
        csv_buf,
        delimiter=";",
    )

    writer.writerow([
        "DATUM",
        "ZEIT",
        "AUFTRAGS-NUMMER",
        "KENNZEICHEN",
        "FAHRER",
        "AUFTRAGGEBER",
        "EINSATZORT",
        "ZIELORT",
        "ZONE",
        "BEMERKUNG",
        "BETRAG",
    ])

    for order in provisioned_orders:
        writer.writerow([
            order["datum"],
            order["zeit"],
            order["nr"],
            order["kfz"],
            order["fahrer"],
            order["ag"],
            order["start"],
            order["ziel"],
            order.get("zone_text", ""),
            order["bemerkung"],
            f"{float(order['betrag']):.2f}",
        ])

    writer.writerow([
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "SUMME:",
        f"{total_brutto:.2f}",
    ])

    st.download_button(
        "💾 CSV exportieren",
        data=csv_buf.getvalue().encode(
            "utf-8-sig"
        ),
        file_name=(
            "Abrechnung_"
            f"{selected_friday.isoformat()}.csv"
        ),
        mime="text/csv",
        use_container_width=True,
    )


# ============================================================
# TECHNISCHE INFO
# ============================================================

st.markdown("---")

st.caption(
    "ADAC-Geofences: OnStreet FP1 / FP2 / FP3 · "
    "Tarifregel: höchste Zone aus Einsatzort und Zielort gewinnt · "
    "FP1 25 € · FP2 30 € · FP3 35 € · "
    "Geocoding: OpenStreetMap Nominatim mit lokalem SQLite-Cache · "
    "Bereitschaft: Freitag 21:00 bis Sonntag 21:00 · "
    "Zeitbasis: Annahme, da der verwendete OnStreet-CSV-Export "
    "keinen Abschlusszeitpunkt enthält."
)

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
from zugang import require_access

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

# Passwortseite als Erstes anzeigen: keine App-/Datenbankinitialisierung davor.
require_access()

# Teurere App-Module erst nach erfolgreicher Zugangskontrolle importieren.
from ki_assistent import render_ai_panel
from provi_befehl import render_command_panel
from fp_karte import render_fp_map
from strassenkilometer import parse_road_reference, parse_road_identifier
from csv_versionsvergleich import compare_versions, duplicate_csv_numbers
from provisions_waechter import import_alerts, price_alert
from bereitschaftskalender import (assign as save_standby, unassign as remove_standby,
    assignments as load_standby, overlaps as standby_overlaps)
from cuvenhaus_suite import render_suite
from monatsarchiv import get_db as get_month_db, upsert_import, load_orders
from autosicherung import show_setup as show_backup_setup
from wochenlisten import available_weekends, in_billing_week, billing_week_bounds, get_scope, other_manual_weekend
from provi_erweiterungen import (claim as save_codriver_claim, unclaim as remove_codriver_claim,
    claims_for, claimants, save_location, get_locations_bulk, audit as audit_commissions,
    decisions as audit_decisions, set_decision, prune as prune_claims)

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

    /* Cuvenhaus ADAC Dark: visuals only, never business logic. */
    .stApp {
        background: #0c111b;
        color: #e9edf5;
    }
    .block-container { max-width: 1540px; }
    h1, h2, h3 { color: #f8fafc !important; }
    [data-testid="stMetric"] {
        background: #172130;
        border: 1px solid #293547;
        border-radius: 14px;
        padding: 12px 16px !important;
    }
    [data-testid="stMetricValue"] { color: #ffcc00; }
    [data-testid="stVerticalBlockBorderWrapper"] > div {
        border-color: #344052 !important;
        border-radius: 14px !important;
    }
    .stButton button[kind="primary"] {
        background: #ffcc00;
        color: #101820;
        border-color: #ffcc00;
        font-weight: 700;
    }
    .stButton button:focus-visible, input:focus-visible {
        outline: 2px solid #ffcc00;
        outline-offset: 2px;
    }
    .stButton button { border-radius: 10px; }
    [data-testid="stExpander"] {
        border: 1px solid #344052;
        border-radius: 12px;
    }
    .cuvenhaus-card-header {
        display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
        margin-bottom: 4px;
    }
    .cuvenhaus-chip {
        display: inline-block; padding: 3px 9px; border-radius: 999px;
        background: #273242; color: #e8edf5; font-size: .75rem;
        border: 1px solid #3c495b;
    }
    .cuvenhaus-chip.warn {
        background: #453719; color: #ffdf7a; border-color: #6c5626;
    }
    .cuvenhaus-chip.ok {
        background: #193b31; color: #a6f1c8; border-color: #316c55;
    }
    @media (max-width: 700px) {
        .block-container { padding-left: .7rem; padding-right: .7rem; }
        [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
        [data-testid="column"] { min-width: min(100%, 260px) !important; flex: 1 1 100% !important; }
        [data-testid="stMetric"] { padding: 10px !important; }
        .stButton button { min-height: 46px; }
        [data-testid="stDataFrame"] { max-width: 100%; overflow-x: auto; }
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
@media (max-width: 700px) {
      .block-container { padding-left: .65rem; padding-right: .65rem; }
      .stButton button { min-height: 44px; width: 100%; }
      div[data-testid="stDataFrame"] { overflow-x: auto; }
      h1 { font-size: 1.4rem !important; }
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
ADDRESS_NORMALIZER_VERSION = "v6"

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

    # Exakte doppelte Hälfte: 'PROVINZIALSTRASSE 2PROVINZIALSTRASSE 2'.
    compact = value.strip()
    n = len(compact)
    for split in range(max(1, n // 2 - 6), min(n, n // 2 + 7)):
        a, b = compact[:split].strip(), compact[split:].strip()
        if a and comparison_text(a) == comparison_text(b):
            return a

    # Doppelte Wortfolge: 'HEINRICH-KÖRNER-STR HEINRICH-KÖRNER-STR'.
    words = compact.split()
    for size in range(len(words) // 2, 0, -1):
        if len(words) >= size * 2:
            a = " ".join(words[:size])
            b = " ".join(words[size:size * 2])
            if comparison_text(a) == comparison_text(b):
                rest = " ".join(words[size * 2:]).strip()
                return (a + (" " + rest if rest else "")).strip()

    # Verklebte Wiederholung eines ausreichend langen Präfixes.
    for i in range(6, len(compact)):
        left = compact[:i].strip()
        right = compact[i:].strip()
        left_cmp = comparison_text(left)
        if len(left_cmp) >= 7 and comparison_text(right).startswith(left_cmp):
            return left

    return compact


# Straßenmarker helfen nur beim Aufteilen von "PLZ Ort Straße Hausnummer".
# Die eigentliche Geocodierung bleibt unstrukturiert genug, damit Nominatim
# auch ungewöhnliche deutsche Straßennamen selbst interpretieren kann.
STREET_MARKER_RE = re.compile(
    r"(?i)(?:"
    r"stra(?:ß|ss)e|str\.?\b|weg\b|allee\b|platz\b|gasse\b|ring\b|ufer\b|"
    r"chaussee\b|\bch\b|damm\b|markt\b|pfad\b|steig(?:e)?\b|wall\b|"
    r"graben\b|promenade\b|br(?:ü|ue)cke\b|steg\b|siedlung\b|"
    r"(?:^|[-\wÄÖÜäöüß])str\b"
    r")"
)


def _looks_like_street(value):
    value = safe_text(value)
    if not value:
        return False
    if re.search(r"unbekannt(?:er|e|es)?\s+stra(?:ss|ß)enname", value, re.I):
        return True
    return bool(STREET_MARKER_RE.search(value))


def _street_start_index(value):
    """Findet ungefähr, wo in 'Sankt Augustin Hauptstraße 18' die Straße beginnt."""
    value = safe_text(value)
    if not value:
        return None
    tokens = value.split()
    for i, token in enumerate(tokens):
        if STREET_MARKER_RE.search(token):
            # Straßennamen können aus mehreren Wörtern bestehen. Normalerweise ist
            # der Marker im letzten Namenswort, deshalb ein Wort davor mitnehmen,
            # wenn davor noch mindestens ein Ortswort übrig bleibt.
            return i
    return None


def _strip_location_prefix(value, postal_code="", city=""):
    result = safe_text(value)
    if postal_code:
        result = re.sub(rf"^\s*{re.escape(postal_code)}\s+", "", result, flags=re.I)
    if city:
        result = re.sub(rf"^\s*{re.escape(city)}\s+", "", result, flags=re.I)
    return result.strip(" ,")


def _split_city_and_street_after_postcode(remainder):
    """Teilt z.B. 'Sankt Augustin Hauptstraße 18' in Ort und Straße."""
    remainder = re.sub(r"\s+", " ", safe_text(remainder)).strip(" ,")
    if not remainder:
        return "", ""
    idx = _street_start_index(remainder)
    # In "Meckenheim Am Wiesenpfad 13", Am is part of the street.
    if idx is not None and idx > 1:
        tokens = remainder.split()
        if tokens[idx - 1].casefold() in {"am", "im", "an", "auf", "in", "zum", "zur", "unter"}:
            idx -= 1
        elif idx > 2 and tokens[idx - 2].casefold() in {"an", "auf", "in", "unter", "zwischen"} and tokens[idx - 1].casefold() in {"der", "dem", "den", "die"}:
            idx -= 2
    if idx is None:
        # Suffixless streets: "Wachtberg Zwischen den Hüllen 47".
        tokens = remainder.split()
        if (len(tokens) >= 4
                and tokens[0].casefold() in {"wachtberg", "bonn", "bornheim",
                    "alfter", "troisdorf", "siegburg", "niederkassel",
                    "königswinter", "bad", "sankt"}
                and re.fullmatch(r"\d{1,4}[a-zA-Z]?", tokens[-1])):
            city_words = 2 if tokens[0].casefold() in {"bad", "sankt"} else 1
            if len(tokens) - city_words >= 3:
                return (smart_city_name(" ".join(tokens[:city_words])),
                        smart_street_name(" ".join(tokens[city_words:])))
        return smart_city_name(remainder), ""
    tokens = remainder.split()
    city = " ".join(tokens[:idx]).strip()
    street = " ".join(tokens[idx:]).strip()
    return smart_city_name(city), smart_street_name(street)


def _remove_house_number(street, house_number):
    street = safe_text(street)
    if not street or not house_number:
        return street
    return re.sub(
        rf"\s*\b{re.escape(house_number)}\b\s*$",
        "",
        street,
        flags=re.I,
    ).strip(" ,")


def clean_onstreet_address(raw):
    """Bereinigt typische OnStreet-Adressen, ohne Informationen wegzuwerfen."""
    original = safe_text(raw)
    empty = {
        "raw": "", "address": "", "search_text": "", "street": "",
        "street_without_number": "", "house_number": "", "postal_code": "",
        "city": "", "has_street": False, "has_house_number": False,
        "is_precise_input": False, "unknown_street": False,
        "warning": "Keine Adresse vorhanden",
    }
    if not original:
        return empty

    # Kreis-/Kennzeichenzusätze wie (BN), (SU), (K) entfernen.
    text = original.replace("\n", " ").replace("\r", " ")
    text = re.sub(r"\(\s*[A-ZÄÖÜ]{1,5}\s*\)", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ,")
    # OnStreet hängt manchmal Namen ohne Trennzeichen an Hausnummern:
    # "Bonner Talweg 287Thomas Steinseifer" -> "Bonner Talweg 287".
    # Nur die direkt an einer Hausnummer klebende Namensfolge abtrennen.
    text = re.sub(r"(\b\d{1,4}[a-z]?)(?=[A-ZÄÖÜ][a-zäöüß]{2,}(?:\s+[A-ZÄÖÜ][a-zäöüß]+)+)([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)+)", r"\1", text)
    # Collapse identical adjacent house numbers, not legitimate number ranges.
    text = re.sub(r"\b(\d{1,4}[a-zA-Z]?)\s+\1\b", r"\1", text, flags=re.I)
    parts = [re.sub(r"\s+", " ", p).strip(" ,") for p in text.split(",") if p.strip(" ,")]

    postal_code = ""
    city = ""
    street = ""

    # 1) Einen sauberen PLZ-Ort-Block bevorzugen, meist der letzte OnStreet-Teil.
    for part in reversed(parts):
        m = re.match(r"^\s*(\d{5})\s+(.+?)\s*$", part)
        if not m:
            continue
        rest = m.group(2).strip()
        # Ein Block ohne erkennbaren Straßenmarker ist sehr wahrscheinlich PLZ + Ort.
        if not _looks_like_street(rest) and not re.search(r"\b\d+[a-zA-Z]?\s*$", rest):
            postal_code = m.group(1)
            city = smart_city_name(rest)
            break

    # 2) Wenn kein reiner Ortsblock existiert, einen kombinierten Block zerlegen.
    if not postal_code:
        for part in parts:
            m = re.match(r"^\s*(\d{5})\s+(.+?)\s*$", part)
            if not m:
                continue
            postal_code = m.group(1)
            city_guess, street_guess = _split_city_and_street_after_postcode(m.group(2))
            city = city_guess
            if street_guess:
                street = street_guess
            break

    # 3) Ohne PLZ ist der letzte kommagetrennte Text oft der Ort: 'Bonn ..., Bonn'.
    if not city and len(parts) >= 2:
        tail = parts[-1]
        if not re.search(r"\d", tail) and not _looks_like_street(tail):
            city = smart_city_name(tail)

    # 4) Besten Straßenblock suchen. Erst Block mit Marker, dann erster Nicht-Ortsblock.
    candidates = []
    for part in parts:
        candidate = part
        if postal_code:
            candidate = re.sub(rf"^\s*{re.escape(postal_code)}\s+", "", candidate, flags=re.I)
        if city:
            candidate = re.sub(rf"^\s*{re.escape(city)}\s+", "", candidate, flags=re.I)
        candidate = candidate.strip(" ,")
        if not candidate:
            continue
        # Reiner Ortsblock nicht als Straße missverstehen.
        if city and comparison_text(candidate) == comparison_text(city):
            continue
        candidate = remove_duplicate_fragment(candidate)
        candidates.append(candidate)

    if not street:
        for candidate in candidates:
            if _looks_like_street(candidate):
                street = candidate
                break

    if not street and candidates:
        # Bei 'Bonn Austr 3-50, Bonn' erkennt der Marker ggf. nichts.
        # Ein Kandidat mit Hausnummer ist dann immer noch besser als nur der Ort.
        for candidate in candidates:
            if re.search(r"\b\d+[a-zA-Z]?(?:\s*[-/]\s*\d+[a-zA-Z]?)?\b", candidate):
                street = candidate
                break

    street = smart_street_name(remove_duplicate_fragment(street))
    unknown_street = bool(re.search(r"unbekannt(?:er|e|es)?\s+stra(?:ss|ß)enname", street, re.I))
    if unknown_street:
        street = ""

    # Hausnummer am Straßenende. PLZ kann dadurch nicht versehentlich zur Hausnummer werden.
    hn_match = re.search(r"\b(\d+[a-zA-Z]?(?:\s*[-/]\s*\d+[a-zA-Z]?)?)\s*$", street)
    house_number = re.sub(r"\s+", "", hn_match.group(1)) if hn_match else ""
    street_without_number = _remove_house_number(street, house_number)

    has_street = bool(street_without_number and len(comparison_text(street_without_number)) >= 3 and not unknown_street)
    has_house_number = bool(house_number)

    # Der wichtigste Suchstring: so konkret wie möglich, aber ohne OnStreet-Dopplungen.
    address_parts = []
    if has_street:
        address_parts.append(street)
    locality = " ".join(x for x in [postal_code, city] if x).strip()
    if locality:
        address_parts.append(locality)
    address_parts.append("Deutschland")
    address = ", ".join(address_parts)

    # Unstrukturierter Zusatz-String als zweite Chance für Nominatim.
    # Hier darf die Stadt vor der Straße stehen, Nominatim kann das meist gut zerlegen.
    search_bits = []
    if postal_code:
        search_bits.append(postal_code)
    if city:
        search_bits.append(city)
    if has_street:
        search_bits.append(street)
    search_text = " ".join(search_bits).strip()
    if search_text:
        search_text += ", Deutschland"
    else:
        search_text = address

    warning = ""
    if unknown_street:
        warning = "Straßenname in OnStreet unbekannt; nur Ort/PLZ verwendbar"
    elif not city and not postal_code:
        warning = "Kein Ort und keine PLZ erkannt"
    elif not has_street:
        warning = "Keine brauchbare Straße erkannt; Ort/PLZ nur näherungsweise"
    elif not has_house_number:
        warning = "Keine Hausnummer; Straßenposition ist nur näherungsweise"

    return {
        "raw": original,
        "address": address,
        "search_text": search_text,
        "street": street if has_street else "",
        "street_without_number": street_without_number if has_street else "",
        "house_number": house_number,
        "postal_code": postal_code,
        "city": city,
        "has_street": has_street,
        "has_house_number": has_house_number,
        "is_precise_input": bool(has_street and has_house_number and (city or postal_code)),
        "unknown_street": unknown_street,
        "warning": warning,
    }


def street_name_variants(street):
    """Liefert wenige sinnvolle Schreibweisen für Str./Straße/Strasse und Ch."""
    street = safe_text(street)
    if not street:
        return []

    variants = [street]

    # Suffixe nur am Wortende ändern, damit z.B. 'Straßburger' nicht zerlegt wird.
    replacements = []
    replacements.append(re.sub(r"(?i)\bstr\.?$", "Straße", street))
    replacements.append(re.sub(r"(?i)\bstr\.?$", "Strasse", street))
    replacements.append(re.sub(r"(?i)(?:-|\s)str\.?\b", " Straße", street))
    replacements.append(re.sub(r"(?i)(?:-|\s)str\.?\b", " Strasse", street))
    replacements.append(re.sub(r"(?i)straße\b", "Strasse", street))
    replacements.append(re.sub(r"(?i)strasse\b", "Straße", street))
    replacements.append(re.sub(r"(?i)straße\b", "Str", street))
    replacements.append(re.sub(r"(?i)strasse\b", "Str", street))
    replacements.append(re.sub(r"(?i)\bCh\b", "Chaussee", street))

    for item in replacements:
        item = re.sub(r"\s+", " ", item).strip(" ,")
        if item and comparison_text(item) not in {comparison_text(v) for v in variants}:
            variants.append(item)

    return variants[:5]


def build_geocode_queries(cleaned):
    """Baut wenige, gestaffelte Nominatim-Suchvarianten statt einer fragilen Einzelabfrage."""
    queries = []

    def add(query, level):
        query = re.sub(r"\s+", " ", safe_text(query)).strip(" ,")
        if not query:
            return
        if not query.lower().endswith("deutschland"):
            query = f"{query}, Deutschland"
        key = normalize_address(query)
        if key and all(normalize_address(q["query"]) != key for q in queries):
            queries.append({"query": query, "level": level})

    street = cleaned.get("street", "")
    street_base = cleaned.get("street_without_number", "")
    hn = cleaned.get("house_number", "")
    postal = cleaned.get("postal_code", "")
    city = cleaned.get("city", "")
    locality = " ".join(x for x in [postal, city] if x).strip()

    # 1) Möglichst konkrete, bereinigte Adresse.
    for variant in street_name_variants(street):
        add(", ".join(x for x in [variant, locality] if x), "house" if hn else "street")

    # 2) Der zusammenhängende OnStreet-Inhalt hilft bei ungewöhnlicher Orts-/Straßentrennung.
    add(cleaned.get("search_text", ""), "raw_cleaned")

    # 3) Wenn Hausnummer problematisch ist, Straße ohne Hausnummer als Näherung.
    if street_base:
        for variant in street_name_variants(street_base):
            add(", ".join(x for x in [variant, locality] if x), "street")
            if city and postal:
                add(f"{variant}, {city}", "street")

    # 4) Nur als letzte Näherung Ort/PLZ. Kein 'exakt'-Status möglich.
    if locality:
        add(locality, "locality")

    # Maximal vier echte HTTP-Abfragen pro bislang unbekannter Adresse.
    # In der Praxis trifft meist die erste oder zweite Variante.
    return queries[:4]

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
    candidates = [
        details.get("city"), details.get("town"), details.get("village"),
        details.get("municipality"), details.get("suburb"), details.get("city_district"),
    ]
    a = comparison_text(input_city)
    if not a:
        return False
    for candidate in candidates:
        b = comparison_text(candidate)
        if b and (a == b or a in b or b in a):
            return True
    return False


def _postal_similarity(input_postal, details):
    a = safe_text(input_postal)
    b = safe_text(details.get("postcode"))
    return bool(a and b and a == b)


def assess_geocode_result(cleaned, result, query_level=""):
    """Bewertet einen Nominatim-Treffer und verhindert selbstbewusste Stadtmittelpunkte."""
    details = result.get("address") or {}
    input_street = cleaned.get("street_without_number") or cleaned.get("street", "")
    street_ok = _street_similarity(input_street, details) if cleaned.get("has_street") else False
    city_ok = _city_similarity(cleaned.get("city", ""), details) if cleaned.get("city") else False
    postal_ok = _postal_similarity(cleaned.get("postal_code", ""), details) if cleaned.get("postal_code") else False

    requested_hn = comparison_text(cleaned.get("house_number", ""))
    returned_hn = comparison_text(details.get("house_number", ""))
    house_ok = bool(requested_hn and returned_hn and requested_hn == returned_hn)

    # Bekannte Widersprüche sind Ausschlusskriterien, keine bloß schlechtere Punktzahl.
    if requested_hn and returned_hn and not house_ok:
        return {"accepted": False, "score": 0, "quality": "unknown"}
    if cleaned.get("postal_code") and details.get("postcode") and not postal_ok:
        return {"accepted": False, "score": 0, "quality": "unknown"}

    locality_ok = postal_ok or city_ok or (not cleaned.get("city") and not cleaned.get("postal_code"))

    # Treffer in einem völlig anderen Ort nicht verwenden.
    if (cleaned.get("city") or cleaned.get("postal_code")) and not locality_ok:
        return {"accepted": False, "score": 0, "quality": "unknown"}

    score = 0
    if postal_ok:
        score += 4
    if city_ok:
        score += 3
    if street_ok:
        score += 6
    if house_ok:
        score += 8
    if query_level == "house":
        score += 1

    if street_ok and house_ok:
        quality = "exact"
    elif street_ok:
        quality = "estimated"
    elif locality_ok and query_level == "locality":
        quality = "estimated"
    elif locality_ok and not cleaned.get("has_street"):
        quality = "estimated"
    else:
        return {"accepted": False, "score": score, "quality": "unknown"}

    return {
        "accepted": True,
        "score": score,
        "quality": quality,
        "street_ok": street_ok,
        "city_ok": city_ok,
        "postal_ok": postal_ok,
        "house_ok": house_ok,
    }


def _nominatim_request(query):
    global LAST_NOMINATIM_REQUEST
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": 5,
        "countrycodes": "de",
        "addressdetails": 1,
    }
    url = f"{NOMINATIM_URL}?{urlencode(params)}"
    with GEOCODE_LOCK:
        elapsed = time.monotonic() - LAST_NOMINATIM_REQUEST
        if elapsed < NOMINATIM_MIN_INTERVAL:
            time.sleep(NOMINATIM_MIN_INTERVAL - elapsed)
        request = Request(
            url,
            headers={
                "User-Agent": NOMINATIM_USER_AGENT,
                "Accept": "application/json",
            },
        )
        LAST_NOMINATIM_REQUEST = time.monotonic()
        with urlopen(request, timeout=12) as response:
            return json.loads(response.read().decode("utf-8"))


def geocode_cleaned_address(cleaned):
    """Cache zuerst; sonst gestaffelte Nominatim-Suche mit wenigen Varianten."""
    canonical = safe_text(cleaned.get("address")) or safe_text(cleaned.get("search_text"))
    if not canonical or canonical == "Deutschland":
        return {
            "status": "EMPTY", "lat": None, "lon": None, "display_name": "",
            "cached": False, "quality": "unknown", "error": "Keine geocodierbare Adresse",
            "query_used": "",
        }

    cached = read_geocode_cache(canonical)
    if cached:
        meta = cached.get("details") or {}
        cached["query_used"] = safe_text(meta.get("_query_used"))
        cached["query_level"] = safe_text(meta.get("_query_level"))
        return cached

    stale = read_geocode_cache(canonical, allow_expired=True)
    queries = build_geocode_queries(cleaned)
    best = None
    got_any_http_response = False

    try:
        for variant in queries:
            query = variant["query"]
            level = variant["level"]
            data = _nominatim_request(query)
            got_any_http_response = True
            if not data:
                continue

            for result in data:
                assessment = assess_geocode_result(cleaned, result, level)
                if not assessment.get("accepted"):
                    continue
                candidate = {
                    "score": assessment["score"],
                    "quality": assessment["quality"],
                    "result": result,
                    "query_used": query,
                    "query_level": level,
                }
                if best is None or candidate["score"] > best["score"]:
                    best = candidate

            # Hausnummer + Straße + Ort passen: keine weiteren Community-API-Abfragen nötig.
            if best and best["quality"] == "exact":
                break
            # Ein sehr guter Straßentreffer genügt ebenfalls. Weitere Varianten würden nur Last erzeugen.
            if best and best["score"] >= 10:
                break

        if best:
            result = best["result"]
            lat = float(result["lat"])
            lon = float(result["lon"])
            display_name = safe_text(result.get("display_name"))
            details = dict(result.get("address") or {})
            details["_query_used"] = best["query_used"]
            details["_query_level"] = best["query_level"]
            write_geocode_cache(
                canonical, "OK", lat, lon, display_name,
                best["quality"], details,
            )
            return {
                "status": "OK", "lat": lat, "lon": lon,
                "display_name": display_name, "cached": False, "expired": False,
                "quality": best["quality"], "details": details,
                "query_used": best["query_used"], "query_level": best["query_level"],
            }

        if got_any_http_response:
            write_geocode_cache(canonical, "NOT_FOUND", quality="unknown", details={
                "_query_used": " | ".join(q["query"] for q in queries),
            })
        return {
            "status": "NOT_FOUND", "lat": None, "lon": None, "display_name": "",
            "cached": False, "quality": "unknown", "error": "Adresse nicht gefunden",
            "query_used": " | ".join(q["query"] for q in queries),
        }

    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        if stale and stale.get("status") == "OK":
            stale["stale"] = True
            stale["quality"] = "estimated"
            stale["error"] = "Geocoder nicht erreichbar; alter Cache-Treffer verwendet"
            meta = stale.get("details") or {}
            stale["query_used"] = safe_text(meta.get("_query_used"))
            return stale
        return {
            "status": "ERROR", "lat": None, "lon": None, "display_name": "",
            "cached": False, "quality": "unknown", "error": str(exc), "query_used": "",
        }


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


def boundary_distance_m(lat, lon, polygon):
    """Abstand zur nächsten Polygonkante in Metern (lokale ebene Näherung)."""
    import math
    if not polygon or len(polygon) < 2:
        return float("inf")
    lat_scale = 111_320.0
    lon_scale = lat_scale * math.cos(math.radians(lat))
    best = float("inf")
    for (a_lat, a_lon), (b_lat, b_lon) in zip(polygon, polygon[1:] + polygon[:1]):
        ax = (a_lon - lon) * lon_scale
        ay = (a_lat - lat) * lat_scale
        bx = (b_lon - lon) * lon_scale
        by = (b_lat - lat) * lat_scale
        vx, vy = bx - ax, by - ay
        length2 = vx * vx + vy * vy
        t = max(0.0, min(1.0, -(ax * vx + ay * vy) / length2)) if length2 else 0.0
        best = min(best, math.hypot(ax + t * vx, ay + t * vy))
    return best


def zone_boundary_warning(lat, lon):
    """Bei nahen Grenzen keine vorgetäuschte hausnummerngenaue Sicherheit."""
    if lat is None or lon is None:
        return False
    return any(boundary_distance_m(lat, lon, poly) < 150.0
               for poly in (FP1_POINTS, FP2_POINTS, FP3_POINTS))


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
        return {
            "zone": None, "source": "missing", "quality": "unknown",
            "lat": None, "lon": None, "warning": True, "message": "Keine Adresse",
            "cleaned_address": "", "display_name": "", "query_used": "",
        }

    road_ref = parse_road_identifier(raw)

    # Verified user coordinates override uncertain external geocoding.
    override = st.session_state.get("verified_locations", {}).get(
        " ".join(raw.casefold().split())
    )
    if override is not None:
        lat, lon = override
        zone = detect_zone_from_coordinates(lat, lon)
        return {
            "zone": zone, "source": "manual_verified",
            "quality": "exact" if zone else "unknown",
            "lat": lat, "lon": lon,
            "warning": zone is None or road_ref is not None,
            "message": (
                f"Manuell bestätigte Koordinate für Straßenkennung {road_ref['label']}; "
                "ohne Streckenabschnitt bitte prüfen, ob der Punkt tatsächlich auf dieser Straße liegt"
                if road_ref else
                ("Manuell bestätigter Standort" if zone
                 else "Manueller Standort außerhalb der FP-Gebiete")
            ),
            "cleaned_address": cleaned.get("address", ""),
            "display_name": "Manuell bestätigt", "query_used": "",
        }

    if road_ref:
        return {
            "zone": None, "source": "road_km_unverified",
            "quality": "unknown", "lat": None, "lon": None,
            "warning": True,
            "message": (
                f"Straßenreferenz erkannt: {road_ref['label']}. "
                "Ohne verifizierte Abschnitts- und Kilometrierungsdaten "
                "keine genaue GPS-Position; bitte Position bestätigen."
            ),
            "cleaned_address": road_ref["label"],
            "display_name": "", "query_used": "",
        }

    geo = geocode_cleaned_address(cleaned)
    if geo.get("status") == "OK" and geo.get("lat") is not None and geo.get("lon") is not None:
        zone = detect_zone_from_coordinates(geo["lat"], geo["lon"])
        quality = geo.get("quality") or "estimated"
        if geo.get("stale"):
            quality = "estimated"

        if zone:
            near_boundary = zone_boundary_warning(geo["lat"], geo["lon"])
            exact = quality == "exact" and not near_boundary
            return {
                "zone": zone,
                "source": "cache" if geo.get("cached") else "geocoding",
                "quality": quality,
                "lat": geo["lat"], "lon": geo["lon"],
                "warning": not exact,
                "message": (
                    "Nahe FP-Grenze (unter 150 m); manuell auf Karte prüfen"
                    if near_boundary
                    else "Adresse hausnummerngenau geocodiert"
                    if exact
                    else "Straße/Ort geocodiert; Position ist näherungsweise"
                ),
                "cleaned_address": cleaned.get("address", ""),
                "display_name": geo.get("display_name", ""),
                "query_used": geo.get("query_used", ""),
            }

        return {
            "zone": None, "source": "geocoding", "quality": quality,
            "lat": geo["lat"], "lon": geo["lon"], "warning": True,
            "message": "Gefundene Koordinate liegt außerhalb der bekannten FP-Geofences",
            "cleaned_address": cleaned.get("address", ""),
            "display_name": geo.get("display_name", ""),
            "query_used": geo.get("query_used", ""),
        }

    # Nur bekannte PLZ-/Ortsregeln als Schätzung. Kein pauschales 'irgendwas = FP1'.
    fallback = detect_adac_zone_fallback(cleaned.get("address") or raw)
    return {
        "zone": fallback,
        "source": "fallback" if fallback else "unknown",
        "quality": "estimated" if fallback else "unknown",
        "lat": None, "lon": None,
        "warning": True,
        "message": (
            "Online-Geocoding ohne Treffer; bekannte PLZ/Ort-Regel als Schätzung"
            if fallback
            else "Adresse konnte weder online noch per bekannter PLZ/Ort-Regel bestimmt werden"
        ),
        "cleaned_address": cleaned.get("address", ""),
        "display_name": "",
        "query_used": geo.get("query_used", "") if isinstance(geo, dict) else "",
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
    order["start_query_used"] = start_result.get("query_used", "")
    order["target_query_used"] = target_result.get("query_used", "")
    order["start_display_name"] = start_result.get("display_name", "")
    order["target_display_name"] = target_result.get("display_name", "")

    order["zone_warning"] = bool(
        (start_address and not start_zone)
        or (target_address and not target_zone)
        or start_result.get("warning")
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
    "weekend_scopes": {},
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

show_backup_setup()

if st.button("🔎 Backup-Verbindung prüfen", key="backup_connection_check"):
    from autosicherung import config, _repo_info, BackupError
    try:
        backup_config = config()
        if backup_config is None:
            st.warning("Backup-Einstellungen fehlen in Streamlit Secrets.")
        else:
            _repo_info(*backup_config)
            st.success("✅ Privates GitHub-Repository erreichbar (Leserechte bestätigt).")
    except BackupError as exc:
        st.error("Backup nicht erreichbar: " + str(exc))
        st.info("In GitHub beim Token unter Repository access das private Backup-Repository auswählen. Unter Contents die Berechtigung Read and write einstellen.")

st.title("🚜 Cuvenhaus Provisions-Manager")
st.caption("Adresssuche: © OpenStreetMap contributors · Nominatim. Treffer werden lokal gecacht und nur bei Bedarf online gesucht.")

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
        # Compare source CSV before archive upsert. Missing rows may simply
        # mean the export is partial; never delete them from the archive.
        _previous = st.session_state.orders
        if not _previous:
            _snapshot_db = get_month_db()
            try:
                _previous = load_orders(_snapshot_db)
            finally:
                _snapshot_db.close()
        st.session_state["csv_version_diff"] = compare_versions(_previous, orders)
        st.session_state["csv_import_duplicates"] = duplicate_csv_numbers(raw)

        try:
            db_month = get_month_db()
            try:
                st.session_state.month_import_result = upsert_import(db_month, orders.values())
                orders = load_orders(db_month)
            finally:
                db_month.close()
            if getattr(db_month, "backup_error", ""):
                st.session_state["month_backup_error"] = getattr(db_month, "backup_error", "")
            else:
                st.session_state.pop("month_backup_error", None)
        except Exception as exc:
            st.error('Lokale Monatsdatenbank konnte nicht gespeichert werden: ' + str(exc))
            st.stop()
        st.session_state.orders = orders
        st.session_state.detected_drivers = sorted({
            str(o.get('fahrer', '')).strip() for o in orders.values()
            if str(o.get('fahrer', '')).strip()
        })
        st.session_state.file_hash = current_hash

        st.session_state.manual_added = set()
        st.session_state.removed_orders = set()
        st.session_state.storno_orders = set()
        st.session_state.manual_zones = {}
        st.session_state.manual_tariffs = {}
        st.session_state.initialized_contexts = set()

        st.rerun()


if not st.session_state.orders:
    try:
        db_month = get_month_db()
        try:
            restored = load_orders(db_month)
        finally:
            db_month.close()
        if getattr(db_month, "backup_error", ""):
            st.session_state["month_backup_error"] = getattr(db_month, "backup_error", "")
        if restored:
            st.session_state.orders = restored
            st.session_state.detected_drivers = sorted({
                str(o.get('fahrer', '')).strip() for o in restored.values()
                if str(o.get('fahrer', '')).strip()
            })
            st.session_state.file_hash = 'monatsarchiv'
    except Exception as exc:
        st.error('Monatsdatenbank oder automatische Sicherung konnte nicht geladen werden: ' + str(exc))
        st.stop()

if st.session_state.get("month_backup_error"):
    st.warning("⚠️ GitHub-Backup nicht erreichbar: "
               + st.session_state["month_backup_error"]
               + " Die CSV ist lokal gespeichert und kann bearbeitet werden. "
               "Auf Streamlit Cloud ist sie damit noch nicht dauerhaft gesichert.")

if st.session_state.get("csv_version_diff"):
    _diff = st.session_state["csv_version_diff"]
    with st.expander(
        f"🔄 CSV-Versionsvergleich · {len(_diff['neu'])} neu · "
        f"{len(_diff['geaendert'])} geändert · "
        f"{len(_diff['fehlt_im_export'])} nicht im Export",
        expanded=bool(_diff["geaendert"]),
    ):
        st.caption("Vergleich der OnStreet-Quelldaten vor dem Import. "
                   "Fehlende Aufträge werden NICHT aus dem Monatsarchiv gelöscht. "
                   "Manuelle Provisionskorrekturen zählen nicht als CSV-Änderung.")
        if _diff["neu"]:
            st.write("**Neu:** " + ", ".join("#" + n for n in _diff["neu"][:50]))
        for _nr, _changes in list(_diff["geaendert"].items())[:60]:
            with st.expander(f"#{_nr} · {', '.join(_changes)}"):
                for _field, (_old, _new) in _changes.items():
                    st.write(f"**{_field}**: {_old or '–'} → {_new or '–'}")
        if _diff["fehlt_im_export"]:
            st.info(f"{len(_diff['fehlt_im_export'])} archivierte Aufträge "
                    "fehlen im aktuellen CSV-Ausschnitt. Das ist keine Löschung.")

if st.session_state.get('month_import_result'):
    stats = st.session_state.month_import_result
    st.info(f"Monatsimport: {stats['neu']} neu · {stats['aktualisiert']} aktualisiert · {stats['unveraendert']} unverändert. Aufbewahrung: 90 Tage nach letztem Import.")

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


top1, top2, top3 = st.columns([1.2, 1.8, 1.1])

with top1:
    active_driver = st.selectbox(
        "👤 Fahrer",
        driver_options,
        index=default_driver_idx,
    )

# Die Monatsdatei bleibt im Archiv. Für jede Wochenendliste werden NUR
# Aufträge derselben Montag-Sonntag-Kalenderwoche berücksichtigt.
driver_orders = [
    o for o in all_orders
    if (
        active_driver == "Alle Fahrer"
        or normalize_search_text(active_driver)
        in normalize_search_text(o.get("fahrer", ""))
    )
]

weekends = available_weekends(driver_orders)

with top2:
    selected_friday = st.selectbox(
        "📋 Provisionsliste / Wochenende",
        weekends,
        format_func=weekend_label,
        key="weekend_list_choice",
        help="Jedes Wochenende hat seine eigene Provisionsliste. "
             "Die übrigen Tage der zugehörigen Woche kannst du manuell ergänzen.",
    )

week_orders = [o for o in driver_orders if in_billing_week(o, selected_friday)]
all_week_orders = [o for o in all_orders if in_billing_week(o, selected_friday)]
week_start, week_end = billing_week_bounds(selected_friday)
standby_start, standby_end = standby_bounds(selected_friday)

with top3:
    st.metric("Aufträge der Woche", len(week_orders))

st.caption(
    f"📋 Abrechnungswoche: {week_start.strftime('%d.%m.%Y')}–"
    f"{(week_end - timedelta(days=1)).strftime('%d.%m.%Y')} "
    f"· Bereitschaft: {standby_start.strftime('%d.%m. %H:%M')} "
    f"bis {standby_end.strftime('%d.%m. %H:%M')} "
    "· Zeitbasis: Annahme"
)

# Read-only planning overview; changing the plan never silently changes pay.
with st.expander("📅 Bereitschaftskalender · Planung", expanded=False):
    st.caption("Freitag 21:00 bis Sonntag 21:00. "
               "Kalendereinträge sind Planung und ändern keine Provisionen.")
    _plan_date = st.date_input("Wochenende auswählen", value=selected_friday,
                               key="standby_plan_date")
    _plan_driver = st.selectbox("Fahrer einteilen",
                                st.session_state.detected_drivers or [""],
                                key="standby_plan_driver")
    _plan_note = st.text_input("Notiz (optional)", key="standby_plan_note")
    _p1, _p2 = st.columns(2)
    with _p1:
        if st.button("Bereitschaft speichern", key="standby_save"):
            _db = get_month_db()
            try:
                save_standby(_db, _plan_date, _plan_driver, _plan_note)
            finally:
                _db.close()
            st.rerun()
    with _p2:
        if st.button("Eintragung entfernen", key="standby_delete"):
            _db = get_month_db()
            try:
                remove_standby(_db, _plan_date, _plan_driver)
            finally:
                _db.close()
            st.rerun()
    _db = get_month_db()
    try:
        _plans = load_standby(_db)
    finally:
        _db.close()
    if _plans:
        st.dataframe(pd.DataFrame(_plans), use_container_width=True,
                     hide_index=True)
        _overlap = standby_overlaps(_plans)
        if _overlap:
            for _day, _names in _overlap.items():
                st.warning(f"{_day}: mehrere Fahrer eingetragen "
                           f"({', '.join(_names)}) – Einteilung prüfen.")
    else:
        st.info("Noch keine Bereitschaften eingetragen.")

# Keine globale Auftragsauswahl mehr: manuell hinzugefügte/entfernte Aufträge
# sowie Betrags- und Zonenänderungen gehören zu Fahrer UND Wochenende.
# Restore shared driver claims and manually confirmed map positions from SQLite.
# These survive CSV reimports and Streamlit session restarts when backup succeeds.
try:
    _claim_db = get_month_db()
    try:
        saved_claims = claims_for(_claim_db, active_driver) if active_driver != "Alle Fahrer" else set()
        verified_locations = get_locations_bulk(
            _claim_db,
            (_address for _o in all_week_orders
             for _address in (_o.get("start", ""), _o.get("ziel", "")))
        )
    finally:
        _claim_db.close()
except Exception as _claim_error:
    saved_claims = set()
    verified_locations = {}
    st.warning("Gespeicherte Fahrer-/Standortzuordnungen konnten nicht geladen werden: " + str(_claim_error))
st.session_state.verified_locations = verified_locations

weekend_scopes = st.session_state.weekend_scopes
scope_id, current_scope = get_scope(weekend_scopes, active_driver, selected_friday)
if st.session_state.get("active_week_scope") != scope_id:
    st.session_state.active_week_scope = scope_id
    st.session_state["add_result"] = None
for field in ("manual_added", "removed_orders", "storno_orders",
              "manual_zones", "manual_tariffs"):
    st.session_state[field] = current_scope[field]
# Persisted co-driver claims are restored only in the matching week.
for _o in all_week_orders:
    if _o["nr"] in saved_claims:
        st.session_state.manual_added.add(_o["nr"])
        st.session_state.removed_orders.discard(_o["nr"])



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


def add_order_to_current_week(target):
    """Immer nur in der aktuell ausgewählten Wochenendliste provisionieren."""
    nr = target["nr"]
    earlier = other_manual_weekend(
        weekend_scopes, active_driver, selected_friday, nr
    )
    if earlier is not None:
        st.session_state.add_result = ("other_week", nr, earlier.strftime("%d.%m.%Y"))
        return

    automatic = (
        belongs_to_active_driver(target)
        and is_in_standby(target, selected_friday)
        and not is_storno_order(
            target.get("stat", ""), target.get("art", ""),
            target.get("raw_nr", ""), target.get("ag", ""),
        )
    )
    existing = (
        (nr in st.session_state.manual_added or automatic)
        and nr not in st.session_state.removed_orders
    )
    if existing:
        st.session_state.add_result = ("info", nr)
        return

    if active_driver == "Alle Fahrer":
        st.session_state.add_result = ("error", nr, "Bitte zuerst einen Fahrer auswählen.")
        return
    # Shared assignments are stored permanently and separately per driver.
    if not belongs_to_active_driver(target):
        try:
            _db = get_month_db()
            try:
                save_codriver_claim(_db, active_driver, nr)
            finally:
                _db.close()
        except Exception as exc:
            st.session_state.add_result = ("error", nr, str(exc))
            return
    st.session_state.manual_added.add(nr)
    st.session_state.removed_orders.discard(nr)
    st.session_state.add_result = ("success", nr, target.get("fahrer", ""))


# ============================================================
# MANUELLE SUCHE
# ============================================================

st.markdown("#### 🔎 Auftrag manuell hinzufügen")
st.caption("Suche in ALLEN Aufträgen dieser Woche – auch wenn ein Kollege als Fahrer eingetragen ist. Gemeinsame Einsätze kannst du für dich manuell übernehmen; automatische Provision bleibt auf deinen Fahrer beschränkt.")

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
        key="week_order_search",
    )


search_matches = []

if search_input.strip():
    q = normalize_search_text(
        search_input
    )

    for order in all_week_orders:
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

            add_order_to_current_week(target)
            st.rerun()


if st.session_state.get("add_result"):
    result = st.session_state.pop("add_result")
    result_type, result_number = result[:2]
    if result_type == "success":
        st.success(f"✅ Auftrag {result_number} zu deiner Wochenendliste hinzugefügt. OnStreet-Fahrer: {result[2]}. Der Auftrag zählt jetzt in deiner Provisionssumme.")
    elif result_type == "error":
        st.error(f"Auftrag {result_number} nicht gespeichert: {result[2]}")
    elif result_type == "other_week":
        st.warning(f"Auftrag {result_number} wurde bereits der Liste vom {result[2]} manuell zugeordnet. Keine doppelte Provision.")
    else:
        st.info(f"ℹ️ Auftrag {result_number} ist in dieser Liste bereits enthalten. Kein Doppler.")

if search_input.strip():
    if not search_matches:
        st.warning(
            "Kein Auftrag mit dieser Nummer "
            "oder diesem Kennzeichen gefunden."
        )

    elif len(search_matches) == 1:
        match = search_matches[0]

        automatic = (
            belongs_to_active_driver(match)
            and is_in_standby(match, selected_friday)
            and not is_storno_order(
                match.get("stat", ""), match.get("art", ""),
                match.get("raw_nr", ""), match.get("ag", ""),
            )
        )
        already = (
            (match["nr"] in st.session_state.manual_added or automatic)
            and match["nr"] not in st.session_state.removed_orders
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
            add_order_to_current_week(selected_match)
            st.rerun()


# ============================================================
# PROVISIONIERTE AUFTRÄGE
# ============================================================

provisioned_orders = []

for order in all_week_orders:
    nr = order["nr"]

    if not belongs_to_active_driver(order) and nr not in st.session_state.manual_added:
        continue

    # Nur dieses Wochenende automatisch, daneben explizite manuelle Aufträge.
    if (nr not in st.session_state.manual_added
            and not (belongs_to_active_driver(order)
                     and is_in_standby(order, selected_friday)
                     and not is_storno_order(order.get("stat", ""),
                                             order.get("art", ""),
                                             order.get("raw_nr", ""),
                                             order.get("ag", "")))):
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

    if nr in st.session_state.manual_tariffs:
        manual = st.session_state.manual_tariffs[nr]
        order["betrag"] = manual["betrag"]
        order["tarif"] = manual["tarif"]
        order["bemerkung"] = (
            f"{order.get('art', '')} / "
            f"{manual['tarif']} · manuell"
        )

    # Storno hat immer Vorrang vor jedem manuellen Preis.
    if nr in st.session_state.storno_orders:
        order["betrag"] = 0.0
        order["tarif"] = "Storno (0 €)"
        order["bemerkung"] = "Storno (0 €)"

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
    only_problems = st.checkbox("Nur Problemfälle anzeigen")

with filter2:
    ui_quick_filter = st.selectbox(
        "🔎 Schnellfilter",
        ["Alle Aufträge", "ADAC", "Storno", "Manuell hinzugefügt",
         "Gemeinsame Einsätze", "FP-Zone unklar"],
        key="ui_quick_filter",
    )
    ui_search = st.text_input(
        "Aufträge durchsuchen",
        placeholder="Auftragsnummer, Kennzeichen, Fahrer oder Adresse",
        key="ui_order_search",
    )


def matches_ui_filters(order):
    nr = order["nr"]
    if only_problems and not order.get("zone_warning"):
        return False
    if ui_quick_filter == "ADAC" and not is_adac_order(
        order.get("ag", ""), order.get("art", ""),
        order.get("raw_nr", ""), order.get("stat", "")
    ):
        return False
    if ui_quick_filter == "Storno" and not (
        nr in st.session_state.storno_orders or is_storno_order(
            order.get("stat", ""), order.get("art", ""),
            order.get("raw_nr", ""), order.get("ag", "")
        )
    ):
        return False
    if ui_quick_filter == "Manuell hinzugefügt" and nr not in st.session_state.manual_added:
        return False
    if ui_quick_filter == "Gemeinsame Einsätze" and not (
        nr in st.session_state.manual_added
        and not belongs_to_active_driver(order)
    ):
        return False
    if ui_quick_filter == "FP-Zone unklar" and not order.get("zone_warning"):
        return False
    query = normalize_search_text(ui_search.strip())
    if query and not any(query in normalize_search_text(order.get(field, ""))
                         for field in ("nr", "kfz", "fahrer", "start", "ziel")):
        return False
    return True


# ============================================================
# ÜBERSICHT + DIREKTES BEARBEITEN
# ============================================================


def parse_money_text(value):
    value = safe_text(value).replace("€", "").replace(" ", "")
    if not value:
        return None
    # Deutsch: 1.234,56 -> 1234.56 / 27,50 -> 27.50
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    try:
        amount = float(value)
    except ValueError:
        return None
    if amount < 0 or amount > 10000:
        return None
    return round(amount, 2)


def quality_label(quality):
    if quality == "exact":
        return "✓ exakt"
    if quality == "estimated":
        return "~ geschätzt"
    return "⚠ unbekannt"


def apply_inline_changes(order, zone_choice, tariff_choice, custom_amount_text):
    nr = order["nr"]

    if is_adac_order(
        order.get("ag", ""), order.get("art", ""),
        order.get("raw_nr", ""), order.get("stat", ""),
    ):
        if zone_choice == "Automatisch":
            st.session_state.manual_zones.pop(nr, None)
            order["manual_zone"] = None
        elif zone_choice in ZONE_RANK:
            st.session_state.manual_zones[nr] = zone_choice
            order["manual_zone"] = zone_choice
        order["geofence_checked"] = False
        calculate_adac_order(order, force=True)

    custom_amount = parse_money_text(custom_amount_text)

    if tariff_choice != "Keine Änderung":
        for label, short, amount in TARIFFS:
            if label == tariff_choice:
                st.session_state.manual_tariffs[nr] = {
                    "tarif": short,
                    "betrag": float(custom_amount if custom_amount is not None else amount),
                }
                break
    elif custom_amount is not None:
        st.session_state.manual_tariffs[nr] = {
            "tarif": order.get("tarif") or "Manueller Betrag",
            "betrag": float(custom_amount),
        }


left, right = st.columns([0.82, 1.18], gap="large")


# ------------------------------------------------------------
# LINKS: ALLE AUFTRÄGE
# ------------------------------------------------------------
with left:
    st.subheader("📥 Aufträge dieser Abrechnungswoche")
    st.caption("✓ = bereits in der Provision. Weitere Touren kannst du oben per Nummer oder Kennzeichen hinzufügen.")

    left_orders = [
        o for o in all_week_orders
        if (belongs_to_active_driver(o) or o["nr"] in st.session_state.manual_added)
        and matches_ui_filters(o)
    ]

    left_rows = []
    for order in left_orders:
        nr = order["nr"]
        in_provision = (
            (nr in st.session_state.manual_added
             or (belongs_to_active_driver(order)
                 and is_in_standby(order, selected_friday)
                 and not is_storno_order(order.get("stat", ""),
                                         order.get("art", ""),
                                         order.get("raw_nr", ""),
                                         order.get("ag", ""))))
            and nr not in st.session_state.removed_orders
        )
        standby = is_in_standby(order, selected_friday)
        left_rows.append({
            "✓": "✓" if in_provision else "",
            "Zeit": f"{order['datum']} {order['zeit']}",
            "Auftrag": order["nr"],
            "Kennzeichen": order["kfz"],
            "Auftraggeber": order["ag"],
            "Bereitschaft": "JA" if standby else "",
        })

    if left_rows:
        st.dataframe(
            pd.DataFrame(left_rows),
            use_container_width=True,
            hide_index=True,
            height=560,
        )
    else:
        st.info("Keine Aufträge für diesen Filter.")


# ------------------------------------------------------------
# RECHTS: PROVISION DIREKT BEARBEITEN
# ------------------------------------------------------------
with right:
    st.subheader("💰 Provision direkt bearbeiten")
    st.caption("Preis, ADAC-Zone, Storno und Entfernen stehen jetzt direkt beim jeweiligen Auftrag. Endlich keine Knopf-Schnitzeljagd mehr.")

    display_orders = [
        o for o in provisioned_orders
        if matches_ui_filters(o)
    ]

    if not display_orders:
        st.info("Noch keine provisionierten Aufträge.")

    for order in display_orders:
        nr = order["nr"]
        is_adac = is_adac_order(
            order.get("ag", ""), order.get("art", ""),
            order.get("raw_nr", ""), order.get("stat", ""),
        )
        is_manual_tariff = nr in st.session_state.manual_tariffs
        is_manual_zone = nr in st.session_state.manual_zones
        is_storno_manual = nr in st.session_state.storno_orders

        with st.container(border=True):
            # Compact, readable status tags; actual values remain unchanged.
            _card_tags = []
            if nr in st.session_state.manual_added:
                _card_tags.append(("Manuell", "ok"))
            if not belongs_to_active_driver(order):
                _card_tags.append(("Gemeinsamer Einsatz", "ok"))
            if order.get("zone_warning"):
                _card_tags.append(("FP prüfen", "warn"))
            if is_storno_manual:
                _card_tags.append(("Storno", "warn"))
            if _card_tags:
                st.markdown(
                    '<div class="cuvenhaus-card-header">'
                    + "".join(
                        f'<span class="cuvenhaus-chip {css}">{html.escape(label)}</span>'
                        for label, css in _card_tags
                    )
                    + '</div>',
                    unsafe_allow_html=True,
                )
            h1, h2, h3, h4 = st.columns([1.15, 1.0, 1.65, 0.85])
            with h1:
                st.markdown(f"**#{nr}**")
                st.caption(f"{order['datum']} · {order['zeit']}")
            with h2:
                st.markdown(f"**{order.get('kfz') or '–'}**")
                st.caption(order.get("ag") or "–")
            with h3:
                zone_or_tariff = order.get("zone_text") if is_adac else order.get("tarif")
                st.markdown(f"**{zone_or_tariff or '–'}**")
                if is_adac and order.get("zone_warning"):
                    st.caption("⚠ Adresse/Zone bitte prüfen")
                elif is_manual_tariff or is_manual_zone:
                    st.caption("Manuell angepasst")
            with h4:
                st.markdown(f"### {euro(order.get('betrag', 0.0))}")

            if is_adac:
                _auto_zone = order.get("auto_zone")
                _manual_price = st.session_state.manual_tariffs.get(nr)
                _zone_override = st.session_state.manual_zones.get(nr)
                _expected_auto = ZONE_RATE.get(_auto_zone)
                _actual = float(order.get("betrag") or 0)
                if _manual_price:
                    st.warning(
                        f"💶 Gespeicherter manueller Preis: "
                        f"{euro(_manual_price['betrag'])} "
                        f"({html.escape(str(_manual_price.get('tarif', '')))}). "
                        f"Automatische GPS-Zone: {_auto_zone or 'unbekannt'}"
                        + (f" ({euro(_expected_auto)})" if _expected_auto is not None else "")
                        + ". 'Neu prüfen' entfernt den manuellen Preis nicht."
                    )
                    if st.button(
                        "↩️ Manuellen Preis entfernen und FP neu berechnen",
                        key=f"reset_manual_price_{nr}",
                        use_container_width=True,
                    ):
                        st.session_state.manual_tariffs.pop(nr, None)
                        order["geofence_checked"] = False
                        calculate_adac_order(order, force=True)
                        st.rerun()
                elif _zone_override:
                    st.info(f"Manuell gewählte Zone: {_zone_override}. "
                            f"GPS-Ergebnis: {_auto_zone or 'unbekannt'}.")
                elif (_expected_auto is not None
                      and abs(_actual - _expected_auto) > 0.009
                      and nr not in st.session_state.storno_orders):
                    st.warning(
                        f"FP-Preisabweichung: GPS-Zone {_auto_zone} "
                        f"= {euro(_expected_auto)}, angezeigt {euro(_actual)}. "
                        "Bitte Tarif und Auftragsstatus prüfen."
                    )

            # Preis direkt am Auftrag: Auswahl + freier Betrag nebeneinander.
            p1, p2 = st.columns([1.7, 1.0])
            tariff_options = ["Keine Änderung"] + [t[0] for t in TARIFFS]
            with p1:
                tariff_choice = st.selectbox(
                    "Tarif ändern auf",
                    tariff_options,
                    index=0,
                    key=f"inline_tariff_{nr}",
                )
            with p2:
                custom_amount_text = st.text_input(
                    "Eigener Betrag €",
                    value="",
                    placeholder=f"z. B. {float(order.get('betrag', 0.0)):.2f}",
                    key=f"inline_amount_{nr}",
                    help="Optional. Wenn du hier einen Betrag eingibst, überschreibt er den Betrag der Tarifauswahl.",
                )

            if is_adac:
                zone_options = ["Automatisch", "FP 1", "FP 2", "FP 3"]
                current_manual = st.session_state.manual_zones.get(nr)
                zone_index = zone_options.index(current_manual) if current_manual in zone_options else 0
                zone_choice = st.selectbox(
                    "ADAC-Zone",
                    zone_options,
                    index=zone_index,
                    key=f"inline_zone_{nr}",
                    help="Automatisch = Koordinaten aus der Adresssuche gegen FP1 → FP2 → FP3 prüfen.",
                )
            else:
                zone_choice = "Automatisch"

            a1, a2, a3, a4 = st.columns([1.15, 1.0, 1.0, 1.0])
            with a1:
                if st.button("💾 Speichern", key=f"inline_save_{nr}", use_container_width=True):
                    amount_candidate = parse_money_text(custom_amount_text)
                    if custom_amount_text.strip() and amount_candidate is None:
                        st.error("Der freie Betrag ist ungültig. Beispiel: 27,50")
                    else:
                        apply_inline_changes(order, zone_choice, tariff_choice, custom_amount_text)
                        st.rerun()

            with a2:
                storno_label = "♻️ Storno zurück" if is_storno_manual else "🚫 Storno 0 €"
                if st.button(storno_label, key=f"inline_storno_{nr}", use_container_width=True):
                    if is_storno_manual:
                        st.session_state.storno_orders.discard(nr)
                    else:
                        st.session_state.storno_orders.add(nr)
                    st.rerun()

            with a3:
                if st.button("↩️ Entfernen", key=f"inline_remove_{nr}", use_container_width=True):
                    if not belongs_to_active_driver(order):
                        try:
                            _db = get_month_db()
                            try:
                                remove_codriver_claim(_db, active_driver, nr)
                            finally:
                                _db.close()
                        except Exception as exc:
                            st.error("Gemeinsame Zuordnung konnte nicht entfernt werden: " + str(exc))
                            st.stop()
                    st.session_state.removed_orders.add(nr)
                    st.session_state.manual_added.discard(nr)
                    st.rerun()

            with a4:
                if is_adac:
                    if st.button("🌍 Neu prüfen", key=f"inline_recheck_{nr}", use_container_width=True):
                        # Aktuelle v4-Cache-Einträge dieser beiden Adressen entfernen, damit wirklich neu gesucht wird.
                        for raw_addr in [order.get("start", ""), order.get("ziel", "")]:
                            cleaned = clean_onstreet_address(raw_addr)
                            canonical = cleaned.get("address") or cleaned.get("search_text")
                            if canonical:
                                try:
                                    with get_db_connection() as conn:
                                        conn.execute("DELETE FROM geocode_cache WHERE cache_key = ?", (address_cache_key(canonical),))
                                        conn.commit()
                                except Exception:
                                    pass
                        order["geofence_checked"] = False
                        calculate_adac_order(order, force=True)
                        st.rerun()
                else:
                    if (is_manual_tariff or is_manual_zone) and st.button(
                        "↩️ Reset", key=f"inline_reset_{nr}", use_container_width=True
                    ):
                        st.session_state.manual_tariffs.pop(nr, None)
                        st.session_state.manual_zones.pop(nr, None)
                        st.rerun()

            if is_manual_tariff or is_manual_zone:
                if st.button(
                    "Automatische Werte wiederherstellen",
                    key=f"inline_full_reset_{nr}",
                    use_container_width=False,
                ):
                    st.session_state.manual_tariffs.pop(nr, None)
                    st.session_state.manual_zones.pop(nr, None)
                    order["manual_zone"] = None
                    order["geofence_checked"] = False
                    if is_adac:
                        calculate_adac_order(order, force=True)
                    st.rerun()

            if is_adac:
                with st.expander("📍 Adresssuche / FP-Prüfung", expanded=bool(order.get("zone_warning"))):
                    def coord_text(lat, lon):
                        if lat is None or lon is None:
                            return "–"
                        return f"{lat:.6f}, {lon:.6f}"

                    s1, s2 = st.columns(2)
                    with s1:
                        st.markdown("**Start**")
                        st.write(order.get("start") or "–")
                        st.caption(f"Bereinigt: {order.get('start_cleaned_address') or '–'}")
                        st.caption(f"Suchanfrage: {order.get('start_query_used') or '–'}")
                        st.caption(f"Koordinate: {coord_text(order.get('start_lat'), order.get('start_lon'))}")
                        st.caption(f"Status: {quality_label(order.get('start_quality'))} · {order.get('start_message') or ''}")
                        if order.get("start_display_name"):
                            st.caption(f"OSM-Treffer: {order.get('start_display_name')}")
                    with s2:
                        st.markdown("**Ziel**")
                        st.write(order.get("ziel") or "–")
                        st.caption(f"Bereinigt: {order.get('target_cleaned_address') or '–'}")
                        st.caption(f"Suchanfrage: {order.get('target_query_used') or '–'}")
                        st.caption(f"Koordinate: {coord_text(order.get('target_lat'), order.get('target_lon'))}")
                        if order.get("ziel"):
                            st.caption(f"Status: {quality_label(order.get('target_quality'))} · {order.get('target_message') or ''}")
                        else:
                            st.caption("Status: kein Ziel vorhanden")
                        if order.get("target_display_name"):
                            st.caption(f"OSM-Treffer: {order.get('target_display_name')}")

                    st.caption("Zonenregel: Einzelpunkt FP1 → FP2 → FP3. Für die gesamte Tour gewinnt anschließend die höhere Zone.")
                    st.markdown("**🗺️ Festpreisgebiete auf der Karte**")
                    if order.get("zone_warning"):
                        st.warning("Mindestens ein Standort ist nur geschätzt. "
                                   "Die Karte zeigt dann die FP-Gebiete, nicht einen erfundenen Einsatzort.")
                    render_fp_map(order, FP1_POINTS, FP2_POINTS, FP3_POINTS)

                    for _place_label, _raw_address in (
                        ("Start", order.get("start", "")),
                        ("Ziel", order.get("ziel", "")),
                    ):
                        _road = parse_road_identifier(_raw_address)
                        if _road:
                            st.info(
                                f"{_place_label}: {_road['label']} erkannt. "
                                "Der Straßenabschnitt ist nicht eindeutig verifiziert. "
                                "Ohne amtliche Kilometrierungsdaten wird "
                                "keine GPS-Position erfunden. "
                                "Bitte eine geprüfte Position unten hinterlegen."
                            )
                    st.markdown("**📌 Standort dauerhaft korrigieren**")
                    st.caption("Koordinaten als Dezimalgrad eingeben (z. B. aus Google Maps "
                               "oder OpenStreetMap). Die geprüfte Position wird für "
                               "dieselbe OnStreet-Adresse wiederverwendet.")
                    for _which, _raw, _latkey, _lonkey in (
                        ("start", order.get("start", ""), "start_lat", "start_lon"),
                        ("ziel", order.get("ziel", ""), "target_lat", "target_lon"),
                    ):
                        if not _raw:
                            continue
                        with st.form(key=f"verified_coords_{scope_id}_{nr}_{_which}"):
                            st.caption(f"{_which.upper()}: {_raw}")
                            _ca, _cb = st.columns(2)
                            with _ca:
                                _lat_input = st.text_input("Breitengrad", value=str(order.get(_latkey) or ""),
                                                           key=f"lat_{scope_id}_{nr}_{_which}")
                            with _cb:
                                _lon_input = st.text_input("Längengrad", value=str(order.get(_lonkey) or ""),
                                                           key=f"lon_{scope_id}_{nr}_{_which}")
                            _submitted = st.form_submit_button("📍 Position prüfen und speichern")
                            if _submitted:
                                try:
                                    _lat = float(_lat_input.replace(",", "."))
                                    _lon = float(_lon_input.replace(",", "."))
                                    _db = get_month_db()
                                    try:
                                        save_location(_db, _raw, _lat, _lon)
                                    finally:
                                        _db.close()
                                    st.session_state.verified_locations[
                                        " ".join(_raw.casefold().split())
                                    ] = (_lat, _lon)
                                    order["geofence_checked"] = False
                                    calculate_adac_order(order, force=True)
                                    st.success("Position gespeichert, FP-Zone neu berechnet.")
                                    st.rerun()
                                except (ValueError, TypeError) as exc:
                                    st.error("Ungültige Koordinaten: " + str(exc))
                                except Exception as exc:
                                    st.error("Standort konnte nicht gespeichert werden: " + str(exc))

# ============================================================
# PROVISIONSPRÜFER MIT DAUERHAFTEN ENTSCHEIDUNGEN
# ============================================================

if active_driver != "Alle Fahrer":
    try:
        _audit_db = get_month_db()
        try:
            _claim_map = {}
            for _p in provisioned_orders:
                _claim_map[_p["nr"]] = sorted(set(claimants(_audit_db, _p["nr"])) | {" ".join(str(_p.get("fahrer", "")).casefold().split())})
            _saved_decisions = audit_decisions(_audit_db, active_driver)
        finally:
            _audit_db.close()
        _findings = audit_commissions(
            provisioned_orders,
            standby_check=lambda o: is_in_standby(o, selected_friday),
            manual_ids=st.session_state.manual_added,
            claim_map=_claim_map,
        )
        _extra = import_alerts(
            all_week_orders,
            st.session_state.get("csv_version_diff"),
            st.session_state.get("csv_import_duplicates", ()),
        )
        _visible_nrs = {str(o.get("nr")) for o in all_week_orders}
        _findings.extend((nr, code, msg) for nr, code, msg in _extra
                         if nr in _visible_nrs)
        for _o in provisioned_orders:
            if is_adac_order(_o.get("ag", ""), _o.get("art", ""),
                             _o.get("raw_nr", ""), _o.get("stat", "")):
                _price_issue = price_alert(
                    _o, ZONE_RATE,
                    manual_override=(_o["nr"] in st.session_state.manual_tariffs
                                     or _o["nr"] in st.session_state.manual_zones
                                     or _o["nr"] in st.session_state.storno_orders),
                )
                if _price_issue:
                    _findings.append(_price_issue)
        _findings = list(dict.fromkeys(_findings))
        _open_count = sum(1 for _nr, _code, _desc in _findings
                          if _saved_decisions.get((_nr, _code), "Offen") == "Offen")
        with st.expander(f"🛡️ Provisionsprüfer · {_open_count} offene Hinweise", expanded=False):
            st.caption("Auffälligkeiten sind Hinweise, keine automatische Ablehnung. "
                       "Manuelle Überstunden bleiben manuell freigegeben.")
            if not _findings:
                st.success("Keine Auffälligkeiten in dieser Wochenendliste.")
            for _nr, _code, _desc in _findings[:80]:
                _current = _saved_decisions.get((_nr, _code), "Offen")
                _x, _y = st.columns([4, 2])
                with _x:
                    st.write(f"**#{_nr}** · {_desc}")
                with _y:
                    _new = st.selectbox(
                        "Prüfstatus", ["Offen", "Geprüft", "Ignoriert"],
                        index=["Offen", "Geprüft", "Ignoriert"].index(_current),
                        key=f"audit_{scope_id}_{_nr}_{_code}",
                        label_visibility="collapsed",
                    )
                    if _new != _current:
                        _db = get_month_db()
                        try:
                            set_decision(_db, active_driver, _nr, _code, _new)
                        finally:
                            _db.close()
                        st.rerun()
            if len(_findings) > 80:
                st.info(f"Es werden die ersten 80 von {len(_findings)} Hinweisen angezeigt.")
    except Exception as exc:
        st.warning("Provisionsprüfung momentan nicht verfügbar: " + str(exc))


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


# Optionaler, schreibgeschützter KI-Bereich zur aktuellen Auswahl
render_ai_panel(week_orders, provisioned_orders)


render_command_panel(
    week_orders, active_driver, driver_options, is_in_standby,
    is_storno_order, calculate_adac_order, is_adac_order,
    generate_pdf_bytes, HAS_REPORTLAB,
)


render_suite(
    all_orders, provisioned_orders, st.session_state.file_hash,
    active_driver, str(selected_friday),
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

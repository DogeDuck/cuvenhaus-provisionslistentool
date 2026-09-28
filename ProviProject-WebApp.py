import csv
from datetime import datetime, timedelta
import hashlib
import html
import io
import re

import pandas as pd
import streamlit as st


# ============================================================
# PDF-MODUL
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


# ============================================================
# DESIGN
# ============================================================

st.markdown(
    """
<style>

.block-container {
    max-width: 1450px;
    padding-top: 1.2rem;
    padding-bottom: 4rem;
}

h1 {
    margin-bottom: 0.15rem !important;
}

.cv-subtitle {
    color: #64748b;
    margin-bottom: 1rem;
}

.cv-shift {
    padding: 12px 15px;
    border: 1px solid #bbf7d0;
    background: #f0fdf4;
    border-radius: 12px;
    margin: 10px 0 16px 0;
}

.cv-card {
    border: 1px solid #e2e8f0;
    border-radius: 13px 13px 5px 5px;
    padding: 13px 14px 11px 14px;
    margin-top: 10px;
    background: white;
}

.cv-card-provi {
    border-left: 4px solid #22c55e;
}

.cv-card-storno {
    border-left: 4px solid #ef4444;
    opacity: 0.8;
}

.cv-card-top {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    align-items: center;
}

.cv-order {
    font-weight: 750;
    font-size: 1rem;
}

.cv-price {
    font-weight: 750;
    font-size: 1.05rem;
}

.cv-meta {
    color: #64748b;
    font-size: .84rem;
    margin-top: 4px;
}

.cv-tariff {
    font-size: .82rem;
    margin-top: 7px;
    color: #334155;
}

.cv-auto {
    display: inline-block;
    font-size: .7rem;
    font-weight: 750;
    color: #166534;
    background: #dcfce7;
    border-radius: 999px;
    padding: 3px 7px;
    margin-top: 7px;
}

.cv-storno-label {
    display: inline-block;
    font-size: .7rem;
    font-weight: 750;
    color: #991b1b;
    background: #fee2e2;
    border-radius: 999px;
    padding: 3px 7px;
    margin-top: 7px;
}

div[data-testid="stMetric"] {
    border: 1px solid #e2e8f0;
    padding: 12px 15px;
    border-radius: 12px;
    background: white;
}

div[data-testid="stButton"] button,
div[data-testid="stDownloadButton"] button {
    min-height: 42px;
    border-radius: 8px;
}

@media (max-width: 800px) {
    .block-container {
        padding-left: 0.8rem;
        padding-right: 0.8rem;
    }

    .cv-card {
        padding: 11px;
    }
}

</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# TARIFE
# ============================================================

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
# HILFSFUNKTIONEN
# ============================================================

def money(value):
    return (
        f"{float(value):,.2f} €"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def parse_dt(value):
    if not value:
        return None

    value = str(value).strip()

    formats = [
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d.%m.%Y",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass

    return None


def order_datetime(order):
    combined = (
        f"{order.get('datum', '')} "
        f"{order.get('zeit', '')}"
    ).strip()

    return (
        parse_dt(combined)
        or parse_dt(order.get("datum", ""))
    )


def format_date(value):
    dt = parse_dt(value)

    if not dt:
        return str(value)

    weekdays = [
        "Mo", "Di", "Mi",
        "Do", "Fr", "Sa", "So"
    ]

    return (
        f"{weekdays[dt.weekday()]}, "
        f"{dt.strftime('%d.%m.%Y')}"
    )


# ============================================================
# ADAC FESTPREISGEBIETE
# ============================================================

def detect_adac_zone(einsatzort_str):

    text = str(einsatzort_str or "").lower()

    plz_match = re.search(
        r"\b(5\d{4}|50\d{3}|51\d{3})\b",
        text,
    )

    plz = (
        plz_match.group(1)
        if plz_match
        else ""
    )

    # --------------------------------------------------------
    # FP3 – LILA – 35 €
    # --------------------------------------------------------

    fp3_plz = {
        "53359", "53913", "53919",
        "50321", "50354", "50374",
        "51503", "53819", "53804",
        "53809", "53567", "53577",
        "53560", "53545", "53424",
        "53489", "53501", "53474",
        "50996", "50997", "50999",
    }

    fp3_places = [
        "rheinbach",
        "swisttal",
        "heimerzheim",
        "odendorf",
        "weilerswist",
        "brühl",
        "hürth",
        "erftstadt",
        "liblar",
        "rösrath",
        "neunkirchen",
        "seelscheid",
        "much",
        "ruppichteroth",
        "uckerath",
        "blankenberg",
        "buchholz",
        "asbach",
        "neustadt (wied)",
        "neustadt wied",
        "vettelschoß",
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
        or any(
            re.search(
                r"\b" + re.escape(place) + r"\b",
                text,
            )
            for place in fp3_places
        )
    ):
        return "FP 3", 35.00

    # --------------------------------------------------------
    # FP2 – GELB – 30 €
    # --------------------------------------------------------

    fp2_plz = {
        "53111", "53113", "53115",
        "53117", "53119", "53121",
        "53123", "53125", "53127",
        "53129", "53173", "53175",
        "53177", "53332", "53347",
        "50389", "53721", "53773",
        "53797", "53340", "53343",
        "53572",
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
        "röttgen",
        "venusberg",
        "godesberg",
        "hardtberg",
    ]

    if (
        plz in fp2_plz
        or any(
            re.search(
                r"\b" + re.escape(place) + r"\b",
                text,
            )
            for place in fp2_places
        )
    ):
        return "FP 2", 30.00

    if (
        "bonn" in text
        and not any(
            place in text
            for place in [
                "beuel",
                "geislar",
                "pützchen",
                "holzlar",
                "oberkassel",
                "vilich",
                "mehlem",
                "53225",
                "53227",
                "53229",
                "53179",
            ]
        )
    ):
        return "FP 2", 30.00

    # --------------------------------------------------------
    # FP1 – GRÜN – 25 €
    # --------------------------------------------------------

    return "FP 1", 25.00


# ============================================================
# TARIFERKENNUNG
# ============================================================

def match_tariff_rule(stat, ag, art, nr, ort):

    ag_l = str(ag).lower()
    art_l = str(art).lower()

    combined = (
        f"{str(stat).lower()} "
        f"{art_l} "
        f"{str(nr).lower()} "
        f"{str(ort).lower()}"
    )

    is_fehlfahrt = any(
        word in combined
        for word in [
            "fehlfahrt",
            "leerfahrt",
            "leer",
        ]
    )

    is_storno = (
        any(
            word in combined
            for word in [
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

    # Storno = 0 €
    if is_storno:
        return "Storno (0 €)", 0.00

    # Stadt Bonn
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

    # Parknotruf
    if (
        "parknotruf" in ag_l
        or "pnr" in combined
    ):
        if is_fehlfahrt:
            return "Parknotruf Leerfahrt", 10.00

        return "Parknotruf Voll", 40.00

    # Werkstatt / Mietwagen
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

    # Polizei
    if "polizei bonn" in ag_l:
        return "Polizei Bonn", 30.00

    if (
        "rhein-sieg" in ag_l
        or "siegburg" in ag_l
        or "kreispolizeibehörde" in ag_l
    ):
        return "Polizei Siegburg", 30.00

    # Falschparker
    if (
        "falschparker" in art_l
        and "stadt" not in ag_l
    ):
        return "Falschparker privat", 30.00

    # Selbstzahler
    if (
        "selbstzahler" in combined
        or "eigener wunsch" in combined
    ):
        return "Selbstzahler", 30.00

    # ADAC
    if (
        "adac" in ag_l
        or "adac" in combined
    ):

        zone_name, zone_rate = (
            detect_adac_zone(ort)
        )

        # WICHTIG:
        # Fehlfahrten werden bezahlt.
        if is_fehlfahrt:
            return (
                f"ADAC {zone_name} Fehlfahrt",
                zone_rate,
            )

        return (
            f"ADAC {zone_name}",
            zone_rate,
        )

    # Andere Fehl-/Leerfahrt ohne Tarifregel
    if is_fehlfahrt:
        return "Fehlfahrt (0 €)", 0.00

    return "Abschleppen / Bereitst.", 25.00


# ============================================================
# BEREITSCHAFT
#
# Freitag 21:00 Uhr
# bis
# Sonntag 21:00 Uhr
# ============================================================

def get_shift_for_datetime(dt):
    """
    Gibt Beginn und Ende des Bereitschafts-Wochenendes
    zurück, zu dem ein Datum gehört bzw. dessen Freitag
    in derselben Kalenderwoche liegt.
    """

    if dt is None:
        return None, None

    # Montag der betreffenden Woche
    monday = (
        dt
        - timedelta(days=dt.weekday())
    ).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    friday = monday + timedelta(days=4)

    start = friday.replace(
        hour=21,
        minute=0,
        second=0,
        microsecond=0,
    )

    sunday = monday + timedelta(days=6)

    end = sunday.replace(
        hour=21,
        minute=0,
        second=0,
        microsecond=0,
    )

    return start, end


def is_in_standby(order, shift_start, shift_end):

    dt = order_datetime(order)

    if not dt:
        return False

    return (
        shift_start
        <= dt
        <= shift_end
    )


def get_available_shifts(orders):
    """
    Sucht alle Wochenenden, die in der CSV relevant sind.
    """

    shifts = {}

    for order in orders.values():

        dt = order_datetime(order)

        if not dt:
            continue

        start, end = get_shift_for_datetime(dt)

        if start is None:
            continue

        key = start.strftime("%Y-%m-%d")

        shifts[key] = (
            start,
            end,
        )

    return sorted(
        shifts.values(),
        key=lambda x: x[0],
        reverse=True,
    )


def shift_label(shift):
    start, end = shift

    return (
        f"Fr {start.strftime('%d.%m.%Y')} · 21:00 "
        f"→ So {end.strftime('%d.%m.%Y')} · 21:00"
    )


# ============================================================
# PDF
# ============================================================

def generate_pdf_bytes(
    rows,
    driver_name,
    period_string,
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
        fontSize=8.5,
        leading=10.5,
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
        fontSize=9,
        leading=11,
        alignment=1,
    )

    elements = []

    header = Table(
        [[
            Paragraph(
                (
                    "<font size=12>"
                    "<b>Mitarbeiter:</b> &nbsp; "
                    f"{html.escape(driver_name)}"
                    "</font>"
                ),
                styles["Normal"],
            ),
            Paragraph(
                (
                    "<font size=12>"
                    "<b>Bereitschaft:</b> &nbsp; "
                    f"{html.escape(period_string)}"
                    "</font>"
                ),
                styles["Normal"],
            ),
        ]],
        colWidths=[420, 360],
    )

    header.setStyle(
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

    elements.append(header)
    elements.append(Spacer(1, 4))

    headers = [
        Paragraph("<b>DATUM</b>", style_head),
        Paragraph(
            "<b>AUFTRAGS-<br/>NUMMER</b>",
            style_head,
        ),
        Paragraph("<b>KENNZEICHEN</b>", style_head),
        Paragraph("<b>AUFTRAGGEBER</b>", style_head),
        Paragraph("<b>BEMERKUNG</b>", style_head),
        Paragraph("<b>BETRAG</b>", style_head),
    ]

    table_data = [headers]

    total = 0.0

    for row in rows:

        amount = float(row["betrag"])

        total += amount

        table_data.append([
            Paragraph(
                html.escape(str(row["datum"])),
                style_center,
            ),
            Paragraph(
                html.escape(str(row["nr"])),
                style_center,
            ),
            Paragraph(
                html.escape(str(row["kfz"])),
                style_center,
            ),
            Paragraph(
                html.escape(str(row["ag"])),
                style_normal,
            ),
            Paragraph(
                html.escape(str(row["bemerkung"])),
                style_normal,
            ),
            Paragraph(
                money(amount),
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
            f"<b>{money(total)}</b>",
            style_right,
        ),
    ])

    table = Table(
        table_data,
        colWidths=[
            75,
            75,
            95,
            185,
            275,
            85,
        ],
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

if "orders" not in st.session_state:
    st.session_state.orders = {}

if "tour_status" not in st.session_state:
    st.session_state.tour_status = {}

if "detected_drivers" not in st.session_state:
    st.session_state.detected_drivers = []

if "file_hash" not in st.session_state:
    st.session_state.file_hash = ""

if "auto_initialized" not in st.session_state:
    st.session_state.auto_initialized = ""


STATUS_OPEN = "offen"
STATUS_PROVI = "provisioniert"
STATUS_REMOVED = "entfernt"
STATUS_STORNO = "storniert"


def get_status(nr):

    return st.session_state.tour_status.get(
        nr,
        STATUS_OPEN,
    )


def set_status(nr, status):

    st.session_state.tour_status[nr] = status


def is_storno_order(order):

    tariff = str(
        order.get("tarif", "")
    ).lower()

    status = str(
        order.get("stat", "")
    ).lower()

    bemerkung = str(
        order.get("bemerkung", "")
    ).lower()

    combined = (
        f"{tariff} {status} {bemerkung}"
    )

    return any(
        word in combined
        for word in [
            "storno",
            "storniert",
            "abgebrochen",
            "widerrufen",
            "annulliert",
            "abgesagt",
        ]
    )


# ============================================================
# HEADER
# ============================================================

st.title("🚜 Cuvenhaus Provisionsabrechnung")

st.markdown(
    """
<div class="cv-subtitle">
Bereitschaft automatisch erkennen und abrechnen
</div>
""",
    unsafe_allow_html=True,
)


# ============================================================
# CSV IMPORT
# ============================================================

uploaded_file = st.file_uploader(
    "📂 OnStreet CSV auswählen",
    type=["csv"],
)


if uploaded_file is not None:

    raw_bytes = uploaded_file.getvalue()

    current_hash = hashlib.sha256(
        raw_bytes
    ).hexdigest()

    if (
        st.session_state.file_hash
        != current_hash
    ):

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

            st.error(
                "Die CSV enthält keine Aufträge."
            )

            st.stop()

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
            h.strip().lower()
            for h in rows[0]
        ]

        def get_idx(candidates):

            for i, header in enumerate(headers):

                if any(
                    candidate in header
                    for candidate in candidates
                ):
                    return i

            return None

        idx_stat = get_idx([
            "aktueller status",
            "status",
        ])

        idx_nr = get_idx([
            "auftrag",
            "vorgang",
        ])

        idx_fahrer = get_idx([
            "fahrer",
            "mitarbeiter",
        ])

        idx_annahme = get_idx([
            "annahme",
            "datum",
        ])

        idx_kfz = get_idx([
            "kennzeichen",
            "kfz",
        ])

        idx_ag = get_idx([
            "auftraggeber",
            "kunde",
        ])

        idx_art = get_idx([
            "auftragsart",
            "leistung",
        ])

        idx_ort = get_idx([
            "einsatzort",
            "ort",
            "straße",
        ])

        if idx_nr is None:

            st.error(
                "Die Spalte mit der Auftragsnummer "
                "wurde nicht gefunden."
            )

            st.stop()

        new_orders = {}

        found_drivers = set()

        for row in rows[1:]:

            if not any(row):
                continue

            def cell(index):

                if (
                    index is None
                    or index >= len(row)
                ):
                    return ""

                return row[index].strip()

            raw_nr = cell(idx_nr)

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

            stat = cell(idx_stat)
            fahrer = cell(idx_fahrer)
            annahme = cell(idx_annahme)
            raw_kfz = cell(idx_kfz)
            ag = cell(idx_ag)
            art = cell(idx_art)
            ort = cell(idx_ort)

            kfz_clean = re.sub(
                r"\(.*?\)",
                "",
                raw_kfz,
            ).strip()

            if not kfz_clean:

                if "ohne" in raw_kfz.lower():
                    kfz_clean = "OHNE"
                else:
                    kfz_clean = "-"

            parsed = parse_dt(annahme)

            if parsed:

                datum = parsed.strftime(
                    "%d.%m.%Y"
                )

                zeit = parsed.strftime(
                    "%H:%M"
                )

            else:

                datum = annahme
                zeit = ""

                if " " in annahme:

                    parts = annahme.split(
                        " ",
                        1,
                    )

                    datum = parts[0]
                    zeit = parts[1][:5]

            tarif, betrag = (
                match_tariff_rule(
                    stat,
                    ag,
                    art,
                    raw_nr,
                    ort,
                )
            )

            bemerkung = (
                f"{art} / {tarif}"
                if tarif not in art
                else art
            )

            if fahrer:
                found_drivers.add(fahrer)

            new_orders[nr] = {
                "nr": nr,
                "fahrer": fahrer,
                "stat": stat,
                "datum": datum,
                "zeit": zeit,
                "kfz": kfz_clean,
                "ag": ag,
                "art": art,
                "tarif": tarif,
                "betrag": float(betrag),
                "bemerkung": bemerkung,
                "route": ort,
            }

        st.session_state.orders = new_orders

        st.session_state.detected_drivers = sorted(
            list(found_drivers)
        )

        # Bei neuer CSV Status neu aufbauen.
        st.session_state.tour_status = {
            nr: STATUS_OPEN
            for nr in new_orders
        }

        st.session_state.file_hash = current_hash

        st.session_state.auto_initialized = ""

        st.rerun()


# ============================================================
# OHNE CSV STOPPEN
# ============================================================

if not st.session_state.orders:

    st.info(
        "👆 Lade zuerst deine OnStreet-CSV hoch."
    )

    st.stop()


# ============================================================
# FAHRER
# ============================================================

top1, top2 = st.columns(
    [1.2, 2.2]
)

with top1:

    driver_options = (
        ["Alle Fahrer"]
        + st.session_state.detected_drivers
    )

    default_idx = 0

    for index, driver in enumerate(
        driver_options
    ):

        driver_lower = driver.lower()

        if (
            "ross" in driver_lower
            or "can" in driver_lower
        ):
            default_idx = index
            break

    active_driver = st.selectbox(
        "👤 Fahrer",
        driver_options,
        index=default_idx,
    )


def belongs_to_driver(order):

    if active_driver == "Alle Fahrer":
        return True

    return (
        active_driver.lower()
        in order.get(
            "fahrer",
            "",
        ).lower()
    )


driver_orders = {
    nr: order
    for nr, order
    in st.session_state.orders.items()
    if belongs_to_driver(order)
}


# ============================================================
# BEREITSCHAFTEN FINDEN
# ============================================================

available_shifts = get_available_shifts(
    driver_orders
)


if not available_shifts:

    st.warning(
        "Für diesen Fahrer wurden keine "
        "gültigen Datumsangaben gefunden."
    )

    st.stop()


with top2:

    selected_shift_label = st.selectbox(
        "📅 Bereitschaft",
        [
            shift_label(shift)
            for shift in available_shifts
        ],
    )


selected_shift_index = [
    shift_label(shift)
    for shift in available_shifts
].index(
    selected_shift_label
)


shift_start, shift_end = (
    available_shifts[
        selected_shift_index
    ]
)


# ============================================================
# AUTOMATISCHE PROVISIONIERUNG
# ============================================================

auto_key = (
    f"{st.session_state.file_hash}"
    f"|{active_driver}"
    f"|{shift_start.isoformat()}"
)


if (
    st.session_state.auto_initialized
    != auto_key
):

    # Zuerst alle Touren des aktuell ausgewählten
    # Fahrers wieder neutral behandeln.
    #
    # Wichtig:
    # Nur automatische Initialisierung.
    # Danach bleiben manuelle Änderungen erhalten.

    for nr, order in driver_orders.items():

        if is_storno_order(order):

            set_status(
                nr,
                STATUS_STORNO,
            )

            continue

        if is_in_standby(
            order,
            shift_start,
            shift_end,
        ):

            # Fehlfahrten / Leerfahrten werden
            # ausdrücklich NICHT ausgeschlossen.
            set_status(
                nr,
                STATUS_PROVI,
            )

        else:

            set_status(
                nr,
                STATUS_OPEN,
            )

    st.session_state.auto_initialized = (
        auto_key
    )

    st.rerun()


# ============================================================
# BEREITSCHAFT INFO
# ============================================================

automatic_count = sum(
    1
    for nr, order in driver_orders.items()
    if (
        is_in_standby(
            order,
            shift_start,
            shift_end,
        )
        and get_status(nr)
        == STATUS_PROVI
    )
)


st.markdown(
    f"""
<div class="cv-shift">
<b>✓ Bereitschaft erkannt</b><br>
Freitag {shift_start.strftime('%d.%m.%Y')} · 21:00 Uhr
&nbsp;→&nbsp;
Sonntag {shift_end.strftime('%d.%m.%Y')} · 21:00 Uhr<br>
<b>{automatic_count} Aufträge aktuell provisioniert</b>
</div>
""",
    unsafe_allow_html=True,
)


# ============================================================
# SUCHE
# ============================================================

search_input = st.text_input(
    "🔎 Auftrag oder Kennzeichen suchen",
    placeholder="z. B. 26945 oder BN-AB 123",
)


def matches_search(order):

    if not search_input:
        return True

    query = search_input.strip().lower()

    return (
        query in order["nr"].lower()
        or query in order["kfz"].lower()
        or query in order["ag"].lower()
    )


# ============================================================
# LISTEN
# ============================================================

all_orders = [
    order
    for order in driver_orders.values()
    if matches_search(order)
]


all_orders.sort(
    key=lambda order:
        order_datetime(order)
        or datetime.min
)


provi_orders = [
    order
    for order in driver_orders.values()
    if (
        get_status(order["nr"])
        == STATUS_PROVI
        and matches_search(order)
    )
]


provi_orders.sort(
    key=lambda order:
        order_datetime(order)
        or datetime.min
)


# ============================================================
# KENNZAHLEN
# ============================================================

all_provi_orders = [
    order
    for order in driver_orders.values()
    if get_status(order["nr"])
    == STATUS_PROVI
]


total_brutto = sum(
    float(order["betrag"])
    for order in all_provi_orders
)


total_netto = (
    total_brutto * 0.60
)


m1, m2, m3 = st.columns(3)

m1.metric(
    "📋 Provisionierte Touren",
    len(all_provi_orders),
)

m2.metric(
    "💰 Brutto-Provision",
    money(total_brutto),
)

m3.metric(
    "💵 Ca. Netto (~60 %)",
    money(total_netto),
)


st.markdown("---")


# ============================================================
# 2-SPALTEN-LAYOUT
# ============================================================

col_all, col_provi = st.columns(
    [1, 1],
    gap="large",
)


# ============================================================
# LINKS: ALLE AUFTRÄGE
# ============================================================

with col_all:

    st.subheader(
        f"📥 Alle Aufträge ({len(all_orders)})"
    )

    st.caption(
        "Alle Aufträge des ausgewählten Fahrers. "
        "Aufträge außerhalb der Bereitschaft können "
        "manuell übernommen werden."
    )

    if not all_orders:

        st.info(
            "Keine passenden Aufträge gefunden."
        )

    for order in all_orders:

        nr = order["nr"]

        status = get_status(nr)

        dt = order_datetime(order)

        inside_shift = (
            is_in_standby(
                order,
                shift_start,
                shift_end,
            )
        )

        card_class = "cv-card"

        if status == STATUS_STORNO:
            card_class += " cv-card-storno"

        st.markdown(
            f"""
<div class="{card_class}">
<div class="cv-card-top">
<div class="cv-order">
#{html.escape(order["nr"])}
</div>
<div class="cv-price">
{money(order["betrag"])}
</div>
</div>

<div class="cv-meta">
{html.escape(format_date(order["datum"]))}
 · {html.escape(order["zeit"])}
 · {html.escape(order["kfz"])}
</div>

<div class="cv-meta">
{html.escape(order["ag"])}
</div>

<div class="cv-tariff">
{html.escape(order["tarif"])}
</div>

{
    '<span class="cv-auto">BEREITSCHAFT</span>'
    if inside_shift and status != STATUS_STORNO
    else ''
}

{
    '<span class="cv-storno-label">STORNO · 0 €</span>'
    if status == STATUS_STORNO
    else ''
}

</div>
""",
            unsafe_allow_html=True,
        )

        if status == STATUS_STORNO:

            st.caption(
                "Dieser Auftrag wurde als Storno erkannt "
                "und wird nicht provisioniert."
            )

        elif status == STATUS_PROVI:

            st.success(
                "✓ In Provisionsabrechnung"
            )

        else:

            if st.button(
                "＋ Übernehmen",
                key=f"take_{nr}",
                use_container_width=True,
            ):

                set_status(
                    nr,
                    STATUS_PROVI,
                )

                st.rerun()


# ============================================================
# RECHTS: PROVISIONSABRECHNUNG
# ============================================================

with col_provi:

    st.subheader(
        f"💰 Provisionsabrechnung "
        f"({len(provi_orders)})"
    )

    st.caption(
        "Bereitschaftstouren werden automatisch "
        "hier eingetragen."
    )

    if not provi_orders:

        st.info(
            "Noch keine provisionierten Aufträge."
        )

    for order in provi_orders:

        nr = order["nr"]

        inside_shift = (
            is_in_standby(
                order,
                shift_start,
                shift_end,
            )
        )

        st.markdown(
            f"""
<div class="cv-card cv-card-provi">

<div class="cv-card-top">
<div class="cv-order">
✓ #{html.escape(order["nr"])}
</div>
<div class="cv-price">
{money(order["betrag"])}
</div>
</div>

<div class="cv-meta">
{html.escape(format_date(order["datum"]))}
 · {html.escape(order["zeit"])}
 · {html.escape(order["kfz"])}
</div>

<div class="cv-meta">
{html.escape(order["ag"])}
</div>

<div class="cv-tariff">
{html.escape(order["tarif"])}
</div>

{
    '<span class="cv-auto">AUTOMATISCHE BEREITSCHAFT</span>'
    if inside_shift
    else '<span class="cv-auto">MANUELL ÜBERNOMMEN</span>'
}

</div>
""",
            unsafe_allow_html=True,
        )

        action1, action2 = st.columns(2)

        with action1:

            if st.button(
                "↩ Entfernen",
                key=f"remove_{nr}",
                use_container_width=True,
            ):

                set_status(
                    nr,
                    STATUS_REMOVED,
                )

                st.rerun()

        with action2:

            if st.button(
                "🚫 Storno",
                key=f"storno_{nr}",
                use_container_width=True,
            ):

                set_status(
                    nr,
                    STATUS_STORNO,
                )

                st.rerun()


# ============================================================
# MANUELLE KORREKTUREN
# ============================================================

st.markdown("---")

st.subheader("✏️ Korrekturen")


edit_col1, edit_col2 = st.columns(2)


# ------------------------------------------------------------
# STORNO ZURÜCKNEHMEN
# ------------------------------------------------------------

with edit_col1:

    storno_orders = [
        order
        for order in driver_orders.values()
        if get_status(order["nr"])
        == STATUS_STORNO
    ]

    with st.expander(
        "🚫 Storno zurücknehmen"
    ):

        if not storno_orders:

            st.caption(
                "Keine stornierten Aufträge."
            )

        else:

            undo_storno = st.selectbox(
                "Storno-Auftrag",
                [
                    f"{o['nr']} | "
                    f"{o['kfz']} | "
                    f"{o['datum']}"
                    for o in storno_orders
                ],
                key="undo_storno_select",
            )

            if st.button(
                "Storno zurücknehmen",
                key="undo_storno_button",
                use_container_width=True,
            ):

                target_nr = (
                    undo_storno
                    .split(" | ")[0]
                )

                order = (
                    st.session_state
                    .orders[target_nr]
                )

                if is_in_standby(
                    order,
                    shift_start,
                    shift_end,
                ):

                    set_status(
                        target_nr,
                        STATUS_PROVI,
                    )

                else:

                    set_status(
                        target_nr,
                        STATUS_OPEN,
                    )

                st.rerun()


# ------------------------------------------------------------
# TARIF ÄNDERN
# ------------------------------------------------------------

with edit_col2:

    with st.expander(
        "💶 Tarif / Festpreis ändern"
    ):

        if not all_provi_orders:

            st.caption(
                "Keine provisionierten Touren."
            )

        else:

            edit_target = st.selectbox(
                "Auftrag",
                [
                    (
                        f"{o['nr']} | "
                        f"{o['kfz']} | "
                        f"{money(o['betrag'])}"
                    )
                    for o in all_provi_orders
                ],
                key="tariff_target",
            )

            tariff_names = (
                [t[0] for t in TARIFFS]
                + ["Freier Betrag..."]
            )

            selected_tariff = st.selectbox(
                "Neuer Tarif",
                tariff_names,
                key="tariff_select",
            )

            custom_amount = 25.0

            if (
                selected_tariff
                == "Freier Betrag..."
            ):

                custom_amount = st.number_input(
                    "Betrag in €",
                    min_value=0.0,
                    max_value=500.0,
                    value=25.0,
                    step=5.0,
                )

            if st.button(
                "💾 Tarif speichern",
                key="save_tariff",
                use_container_width=True,
            ):

                target_nr = (
                    edit_target
                    .split(" | ")[0]
                )

                order = (
                    st.session_state
                    .orders[target_nr]
                )

                if (
                    selected_tariff
                    == "Freier Betrag..."
                ):

                    order["betrag"] = float(
                        custom_amount
                    )

                    order["tarif"] = (
                        f"Manuell "
                        f"({money(custom_amount)})"
                    )

                else:

                    for (
                        tariff_label,
                        tariff_short,
                        tariff_value,
                    ) in TARIFFS:

                        if (
                            tariff_label
                            == selected_tariff
                        ):

                            order["betrag"] = (
                                tariff_value
                            )

                            order["tarif"] = (
                                tariff_short
                            )

                            break

                order["bemerkung"] = (
                    f"{order['art']} / "
                    f"{order['tarif']}"
                )

                st.success(
                    f"Tarif für Auftrag "
                    f"{target_nr} gespeichert."
                )

                st.rerun()


# ============================================================
# EXPORT
# ============================================================

st.markdown("---")

st.subheader("📤 Abrechnung & Export")


export_orders = sorted(
    all_provi_orders,
    key=lambda order:
        order_datetime(order)
        or datetime.min,
)


export_total = sum(
    float(order["betrag"])
    for order in export_orders
)


driver_title = (
    active_driver
    if active_driver != "Alle Fahrer"
    else "Alle Fahrer"
)


period_string = (
    f"{shift_start.strftime('%d.%m.%Y')} "
    f"21:00 – "
    f"{shift_end.strftime('%d.%m.%Y')} "
    f"21:00"
)


# ============================================================
# WHATSAPP
# ============================================================

wa_lines = [
    (
        f"📋 *Bereitschafts-Abrechnung – "
        f"{driver_title}*"
    ),
    (
        f"🕘 {period_string}"
    ),
    "",
    (
        f"💰 *Gesamt:* "
        f"{len(export_orders)} Touren = "
        f"*{money(export_total)}*"
    ),
    "",
]


for order in export_orders:

    wa_lines.append(
        (
            f"• *{order['nr']}* | "
            f"{order['datum']} | "
            f"{order['kfz']} | "
            f"{order['bemerkung']} "
            f"({money(order['betrag'])})"
        )
    )


wa_text = "\n".join(
    wa_lines
)


export_col1, export_col2 = st.columns(
    [1.3, 1]
)


with export_col1:

    st.text_area(
        "📋 WhatsApp-Text",
        value=wa_text,
        height=180,
    )


# ============================================================
# PDF + CSV
# ============================================================

with export_col2:

    if (
        HAS_REPORTLAB
        and export_orders
    ):

        pdf_bytes = generate_pdf_bytes(
            export_orders,
            driver_title,
            period_string,
        )

        st.download_button(
            label="📄 PDF herunterladen",
            data=pdf_bytes,
            file_name=(
                "Abrechnung_"
                f"{shift_start.strftime('%Y-%m-%d')}"
                ".pdf"
            ),
            mime="application/pdf",
            use_container_width=True,
        )

    elif not HAS_REPORTLAB:

        st.warning(
            "ReportLab fehlt. "
            "PDF-Export ist nicht verfügbar."
        )

    csv_buf = io.StringIO()

    writer = csv.writer(
        csv_buf,
        delimiter=";",
    )

    writer.writerow([
        "DATUM",
        "AUFTRAGS-NUMMER",
        "KENNZEICHEN",
        "AUFTRAGGEBER",
        "BEMERKUNG",
        "BETRAG",
    ])

    for order in export_orders:

        writer.writerow([
            order["datum"],
            order["nr"],
            order["kfz"],
            order["ag"],
            order["bemerkung"],
            f"{float(order['betrag']):.2f}",
        ])

    writer.writerow([
        "",
        "",
        "",
        "",
        "SUMME:",
        f"{export_total:.2f}",
    ])

    st.download_button(
        label="💾 CSV exportieren",
        data=csv_buf.getvalue().encode(
            "utf-8-sig"
        ),
        file_name=(
            "Abrechnung_"
            f"{shift_start.strftime('%Y-%m-%d')}"
            ".csv"
        ),
        mime="text/csv",
        use_container_width=True,
        disabled=(
            len(export_orders) == 0
        ),
    )


# ============================================================
# INFO
# ============================================================

with st.expander(
    "ℹ️ Regeln dieser Abrechnung"
):

    st.markdown(
        """
**Automatische Bereitschaft**

Freitag **21:00 Uhr** bis Sonntag **21:00 Uhr**.

Alle Aufträge des ausgewählten Fahrers innerhalb dieses
Zeitraums werden automatisch in die Provisionsabrechnung
übernommen.

**Fehlfahrten und Leerfahrten werden provisioniert.**

**Storno wird nicht provisioniert und mit 0 € behandelt.**

Aufträge außerhalb der Bereitschaft können links manuell
übernommen werden.

**ADAC Festpreis**

🟢 FP1 = 25,00 €  
🟡 FP2 = 30,00 €  
🟣 FP3 = 35,00 €
"""
    )

import csv
import hashlib
import html
import io
import re
from datetime import datetime

import pandas as pd
import streamlit as st


# ============================================================
# PDF
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
# APP
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
    max-width: 1180px;
    padding-top: 1.4rem;
    padding-bottom: 4rem;
}

h1 {
    margin-bottom: .15rem !important;
}

.cv-subtitle {
    color: #64748b;
    margin-bottom: 1.4rem;
}

.cv-steps {
    display:flex;
    gap:7px;
    flex-wrap:wrap;
    margin:12px 0 24px 0;
}

.cv-step {
    padding:7px 12px;
    border-radius:999px;
    background:#f1f5f9;
    border:1px solid #e2e8f0;
    font-size:.82rem;
    font-weight:600;
}

.cv-step-done {
    background:#ecfdf5;
    border-color:#bbf7d0;
    color:#166534;
}

.cv-section {
    margin-top:1.5rem;
    margin-bottom:.5rem;
    font-size:1.25rem;
    font-weight:700;
}

.cv-card {
    border:1px solid #e2e8f0;
    border-radius:15px 15px 6px 6px;
    padding:15px 16px 13px 16px;
    background:white;
    margin-top:12px;
}

.cv-card-top {
    display:flex;
    justify-content:space-between;
    align-items:center;
    gap:12px;
}

.cv-status {
    font-size:.72rem;
    font-weight:800;
    letter-spacing:.04em;
}

.cv-open {
    color:#64748b;
}

.cv-done {
    color:#15803d;
}

.cv-storno {
    color:#b91c1c;
}

.cv-price {
    font-size:1.15rem;
    font-weight:750;
}

.cv-order {
    font-size:1.03rem;
    font-weight:700;
    margin-top:13px;
}

.cv-meta {
    color:#64748b;
    font-size:.88rem;
    margin-top:3px;
}

.cv-tariff {
    margin-top:9px;
    font-size:.83rem;
    color:#475569;
}

div[data-testid="stButton"] button,
div[data-testid="stDownloadButton"] button {
    min-height:44px;
    border-radius:9px;
    font-weight:600;
}

div[data-testid="stMetric"] {
    border:1px solid #e2e8f0;
    padding:14px 16px;
    border-radius:13px;
    background:#fff;
}

@media (max-width: 700px) {

    .block-container {
        padding-left:1rem;
        padding-right:1rem;
        padding-top:1rem;
    }

    .cv-steps {
        gap:5px;
    }

    .cv-step {
        font-size:.72rem;
        padding:6px 9px;
    }

    .cv-card {
        padding:14px;
    }

    div[data-testid="stHorizontalBlock"] {
        gap:.5rem;
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
    value = f"{order.get('datum', '')} {order.get('zeit', '')}".strip()
    return parse_dt(value) or parse_dt(order.get("datum", ""))


def format_date(value):
    dt = parse_dt(str(value))

    if not dt:
        return str(value)

    weekdays = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

    return f"{weekdays[dt.weekday()]}, {dt.strftime('%d.%m.%Y')}"


def detect_adac_zone(einsatzort_str):

    text = str(einsatzort_str or "").lower()

    plz_match = re.search(
        r"\\b(5\\d{4}|50\\d{3}|51\\d{3})\\b",
        text,
    )

    plz = plz_match.group(1) if plz_match else ""

    # FP3 – lila
    fp3_plz = {
        "53359", "53913", "53919", "50321", "50354", "50374",
        "51503", "53819", "53804", "53809", "53567", "53577",
        "53560", "53545", "53424", "53489", "53501", "53474",
        "50996", "50997", "50999",
    }

    fp3_places = [
        "rheinbach", "swisttal", "heimerzheim", "odendorf",
        "weilerswist", "brühl", "hürth", "erftstadt", "liblar",
        "rösrath", "neunkirchen", "seelscheid", "much",
        "ruppichteroth", "uckerath", "blankenberg", "buchholz",
        "asbach", "neustadt (wied)", "neustadt wied",
        "vettelschoß", "linz am rhein", "linz", "remagen",
        "sinzig", "grafschaft", "neuenahr", "ahrweiler",
        "rodenkirchen",
    ]

    if (
        plz in fp3_plz
        or any(
            re.search(r"\\b" + re.escape(place) + r"\\b", text)
            for place in fp3_places
        )
    ):
        return "FP 3", 35.00

    # FP2 – gelb
    fp2_plz = {
        "53111", "53113", "53115", "53117", "53119",
        "53121", "53123", "53125", "53127", "53129",
        "53173", "53175", "53177", "53332", "53347",
        "50389", "53721", "53773", "53797", "53340",
        "53343", "53572",
    }

    fp2_places = [
        "siegburg", "hennef", "bornheim", "merten",
        "roisdorf", "alfter", "oedekoven", "witterschlick",
        "wesseling", "lohmar", "meckenheim", "wachtberg",
        "unkel", "oberpleis", "thomasberg", "ittenbach",
        "aegidienberg", "duisdorf", "endenich", "tannenbusch",
        "röttgen", "venusberg", "godesberg", "hardtberg",
    ]

    if (
        plz in fp2_plz
        or any(
            re.search(r"\\b" + re.escape(place) + r"\\b", text)
            for place in fp2_places
        )
    ):
        return "FP 2", 30.00

    if (
        "bonn" in text
        and not any(
            value in text
            for value in [
                "beuel", "geislar", "pützchen", "holzlar",
                "oberkassel", "vilich", "mehlem",
                "53225", "53227", "53229", "53179",
            ]
        )
    ):
        return "FP 2", 30.00

    # FP1 – grün
    return "FP 1", 25.00


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
        x in combined
        for x in ["fehlfahrt", "leerfahrt", "leer"]
    )

    is_storno = (
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

    if is_storno:
        return "Storno (0 €)", 0.0

    if "stadt bonn" in ag_l or (
        "stadt" in ag_l and "bonn" in ag_l
    ):
        if is_fehlfahrt:
            return "Stadt Bonn Leerfahrt", 30.00

        return "Stadt Bonn Voll/Vers.", 30.00

    if "parknotruf" in ag_l or "pnr" in combined:
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
        return "Werkstatt / Gutachten / Leihwagen", 50.00

    if "polizei bonn" in ag_l:
        return "Polizei Bonn", 30.00

    if (
        "rhein-sieg" in ag_l
        or "siegburg" in ag_l
        or "kreispolizeibehörde" in ag_l
    ):
        return "Polizei Siegburg", 30.00

    if "falschparker" in art_l and "stadt" not in ag_l:
        return "Falschparker privat", 30.00

    if (
        "selbstzahler" in combined
        or "eigener wunsch" in combined
    ):
        return "Selbstzahler", 30.00

    if "adac" in ag_l or "adac" in combined:

        zone, rate = detect_adac_zone(ort)

        if is_fehlfahrt:
            return f"ADAC {zone} Fehlfahrt", rate

        return f"ADAC {zone}", rate

    if is_fehlfahrt:
        return "Fehlfahrt (0 €)", 0.00

    return "Abschleppen / Bereitst.", 25.00


# ============================================================
# PDF
# ============================================================

def generate_pdf_bytes(rows, driver_name, month_str):

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

    normal = ParagraphStyle(
        "CellNormal",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=10.5,
    )

    center = ParagraphStyle(
        "CellCenter",
        parent=normal,
        alignment=1,
    )

    right = ParagraphStyle(
        "CellRight",
        parent=normal,
        alignment=2,
    )

    head = ParagraphStyle(
        "CellHead",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
        alignment=1,
    )

    elements = []

    hdr = Table(
        [[
            Paragraph(
                f"<font size=12><b>Mitarbeiter:</b> "
                f"{html.escape(driver_name)}</font>",
                styles["Normal"],
            ),
            Paragraph(
                f"<font size=12><b>Zeitraum:</b> "
                f"{html.escape(month_str)}</font>",
                styles["Normal"],
            ),
        ]],
        colWidths=[420, 360],
    )

    elements.append(hdr)
    elements.append(Spacer(1, 5))

    headers = [
        Paragraph("<b>DATUM</b>", head),
        Paragraph("<b>AUFTRAGS-<br/>NUMMER</b>", head),
        Paragraph("<b>KENNZEICHEN</b>", head),
        Paragraph("<b>AUFTRAGGEBER</b>", head),
        Paragraph("<b>BEMERKUNG</b>", head),
        Paragraph("<b>BETRAG</b>", head),
    ]

    data = [headers]

    total = 0.0

    for row in rows:

        amount = float(row["betrag"])
        total += amount

        data.append([
            Paragraph(html.escape(str(row["datum"])), center),
            Paragraph(html.escape(str(row["nr"])), center),
            Paragraph(html.escape(str(row["kfz"])), center),
            Paragraph(html.escape(str(row["ag"])), normal),
            Paragraph(html.escape(str(row["bemerkung"])), normal),
            Paragraph(money(amount), right),
        ])

    for _ in range(max(0, 16 - len(rows))):
        data.append(["", "", "", "", "", ""])

    data.append([
        "", "", "", "",
        Paragraph("<b>SUMME:</b>", right),
        Paragraph(f"<b>{money(total)}</b>", right),
    ])

    table = Table(
        data,
        colWidths=[75, 75, 95, 185, 275, 85],
        repeatRows=1,
    )

    table.setStyle(
        TableStyle([
            ("GRID", (0, 0), (-1, -2), 0.7, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("BOX", (4, -1), (5, -1), 0.9, colors.black),
        ])
    )

    elements.append(table)

    doc.build(elements)

    return buf.getvalue()


# ============================================================
# SESSION STATE
# ============================================================

defaults = {
    "orders": {},
    "tour_status": {},
    "detected_drivers": [],
    "file_hash": "",
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


STATUS_OPEN = "offen"
STATUS_DONE = "uebernommen"
STATUS_REMOVED = "entfernt"
STATUS_CANCELLED = "storniert"


def status_of(nr):
    return st.session_state.tour_status.get(
        nr,
        STATUS_OPEN,
    )


def set_status(nr, status):
    st.session_state.tour_status[nr] = status


# ============================================================
# HEADER
# ============================================================

st.title("🚜 Cuvenhaus Provision")

st.markdown(
    '<div class="cv-subtitle">'
    "Bereitschafts- und Provisionsabrechnung"
    "</div>",
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="cv-steps">
<div class="cv-step cv-step-done">1 · CSV</div>
<div class="cv-step">2 · Fahrer</div>
<div class="cv-step">3 · Schicht</div>
<div class="cv-step">4 · Touren</div>
<div class="cv-step">5 · Abrechnung</div>
</div>
""",
    unsafe_allow_html=True,
)


# ============================================================
# 1 CSV
# ============================================================

st.markdown(
    '<div class="cv-section">1 · CSV importieren</div>',
    unsafe_allow_html=True,
)

uploaded_file = st.file_uploader(
    "OnStreet CSV auswählen",
    type=["csv"],
)


if uploaded_file is not None:

    raw_bytes = uploaded_file.getvalue()

    current_hash = hashlib.sha256(
        raw_bytes
    ).hexdigest()

    if st.session_state.file_hash != current_hash:

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
            st.error("Die CSV enthält keine Touren.")
            st.stop()

        delimiter = (
            ";"
            if lines[0].count(";") > lines[0].count(",")
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
                if any(c in header for c in candidates):
                    return i
            return None

        idx_stat = get_idx(["aktueller status", "status"])
        idx_nr = get_idx(["auftrag", "vorgang"])
        idx_fahrer = get_idx(["fahrer", "mitarbeiter"])
        idx_annahme = get_idx(["annahme", "datum"])
        idx_kfz = get_idx(["kennzeichen", "kfz"])
        idx_ag = get_idx(["auftraggeber", "kunde"])
        idx_art = get_idx(["auftragsart", "leistung"])
        idx_ort = get_idx(["einsatzort", "ort", "straße"])

        if idx_nr is None:
            st.error(
                "Die Auftragsnummer konnte in der CSV "
                "nicht gefunden werden."
            )
            st.stop()

        new_orders = {}
        drivers = set()

        for row in rows[1:]:

            if not any(row):
                continue

            def cell(index):
                if index is None or index >= len(row):
                    return ""
                return row[index].strip()

            raw_nr = cell(idx_nr)

            if not raw_nr:
                continue

            nr_match = re.match(
                r"^\\s*(\\d+)",
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

            kfz = re.sub(
                r"\\(.*?\\)",
                "",
                raw_kfz,
            ).strip()

            if not kfz:
                kfz = (
                    "OHNE"
                    if "ohne" in raw_kfz.lower()
                    else "-"
                )

            dt = parse_dt(annahme)

            if dt:
                datum = dt.strftime("%d.%m.%Y")
                zeit = dt.strftime("%H:%M")
            else:
                datum = annahme.split(" ")[0] if annahme else ""
                zeit = ""

            tarif, betrag = match_tariff_rule(
                stat,
                ag,
                art,
                raw_nr,
                ort,
            )

            bemerkung = (
                f"{art} / {tarif}"
                if tarif not in art
                else art
            )

            if fahrer:
                drivers.add(fahrer)

            new_orders[nr] = {
                "nr": nr,
                "fahrer": fahrer,
                "stat": stat,
                "datum": datum,
                "zeit": zeit,
                "kfz": kfz,
                "ag": ag,
                "art": art,
                "tarif": tarif,
                "betrag": float(betrag),
                "bemerkung": bemerkung,
                "route": ort,
            }

        st.session_state.orders = new_orders

        # Neue Datei = neuer Arbeitsstand
        st.session_state.tour_status = {
            nr: STATUS_OPEN
            for nr in new_orders
        }

        st.session_state.detected_drivers = sorted(
            drivers
        )

        st.session_state.file_hash = current_hash

        st.rerun()


if not st.session_state.orders:

    st.info(
        "👆 Lade zuerst die OnStreet-CSV hoch. "
        "Danach erscheinen Fahrer und Touren automatisch."
    )

    st.stop()


st.success(
    f"✓ CSV geladen · "
    f"{len(st.session_state.orders)} Touren · "
    f"{len(st.session_state.detected_drivers)} Fahrer"
)


# ============================================================
# 2 FAHRER
# ============================================================

st.markdown(
    '<div class="cv-section">2 · Fahrer auswählen</div>',
    unsafe_allow_html=True,
)

driver_options = (
    ["Alle Fahrer"]
    + st.session_state.detected_drivers
)

default_driver = 0

for i, driver in enumerate(driver_options):

    d = driver.lower()

    if "ross" in d or "can" in d:
        default_driver = i
        break


active_driver = st.selectbox(
    "Fahrer",
    driver_options,
    index=default_driver,
)


def belongs_to_driver(order):

    if active_driver == "Alle Fahrer":
        return True

    return (
        active_driver.lower()
        in order["fahrer"].lower()
    )


driver_orders = [
    order
    for order in st.session_state.orders.values()
    if belongs_to_driver(order)
]


# ============================================================
# 3 SCHICHT
# ============================================================

st.markdown(
    '<div class="cv-section">3 · Schicht auswählen</div>',
    unsafe_allow_html=True,
)


available_dates = sorted({
    dt.date()
    for order in driver_orders
    if (dt := order_datetime(order))
})


if not available_dates:

    st.warning(
        "Für diesen Fahrer wurden keine gültigen "
        "Datumsangaben gefunden."
    )

    st.stop()


# WICHTIG:
# nicht mehr erster Tag + 2,
# sondern echter Bereich der CSV
min_date = min(available_dates)
max_date = max(available_dates)


selected_range = st.date_input(
    "Zeitraum",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)


if (
    isinstance(selected_range, tuple)
    and len(selected_range) == 2
):

    start_date, end_date = selected_range

else:

    start_date = selected_range
    end_date = selected_range


def in_selected_shift(order):

    dt = order_datetime(order)

    if not dt:
        return False

    return (
        start_date
        <= dt.date()
        <= end_date
    )


visible_orders = [
    order
    for order in driver_orders
    if in_selected_shift(order)
]


st.caption(
    f"{start_date.strftime('%d.%m.%Y')} – "
    f"{end_date.strftime('%d.%m.%Y')} · "
    f"{len(visible_orders)} Touren"
)


# ============================================================
# 4 TOUREN
# ============================================================

st.markdown(
    '<div class="cv-section">4 · Touren</div>',
    unsafe_allow_html=True,
)


search = st.text_input(
    "🔎 Auftrag oder Kennzeichen suchen",
    placeholder="z. B. 26945 oder BN-AB 123",
)


if search:

    q = search.lower().strip()

    visible_orders = [
        o
        for o in visible_orders
        if (
            q in o["nr"].lower()
            or q in o["kfz"].lower()
        )
    ]


open_count = sum(
    1
    for o in visible_orders
    if status_of(o["nr"])
    in [STATUS_OPEN, STATUS_REMOVED]
)


c1, c2 = st.columns([2, 1])

with c1:

    st.write(
        f"**{len(visible_orders)} Touren sichtbar · "
        f"{open_count} noch nicht übernommen**"
    )


with c2:

    if st.button(
        "✓ Alle sichtbaren übernehmen",
        type="primary",
        use_container_width=True,
        disabled=(open_count == 0),
    ):

        for order in visible_orders:

            nr = order["nr"]

            if status_of(nr) in [
                STATUS_OPEN,
                STATUS_REMOVED,
            ]:
                set_status(
                    nr,
                    STATUS_DONE,
                )

        st.rerun()


# ============================================================
# MOBILE TOURENKARTEN
# ============================================================

for order in sorted(
    visible_orders,
    key=lambda x: order_datetime(x) or datetime.min,
):

    nr = order["nr"]
    status = status_of(nr)

    if status == STATUS_DONE:
        label = "✓ ÜBERNOMMEN"
        css = "cv-done"

    elif status == STATUS_CANCELLED:
        label = "✕ STORNIERT"
        css = "cv-storno"

    elif status == STATUS_REMOVED:
        label = "↩ ENTFERNT"
        css = "cv-open"

    else:
        label = "● OFFEN"
        css = "cv-open"

    st.markdown(
        f"""
<div class="cv-card">

<div class="cv-card-top">

<span class="cv-status {css}">
{label}
</span>

<span class="cv-price">
{money(order["betrag"])}
</span>

</div>

<div class="cv-order">
Auftrag #{html.escape(order["nr"])}
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

</div>
""",
        unsafe_allow_html=True,
    )

    if status in [
        STATUS_OPEN,
        STATUS_REMOVED,
    ]:

        if st.button(
            "✓ Übernehmen",
            key=f"take_{nr}",
            type="primary",
            use_container_width=True,
        ):
            set_status(
                nr,
                STATUS_DONE,
            )

            st.rerun()


    elif status == STATUS_DONE:

        b1, b2 = st.columns(2)

        with b1:

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

        with b2:

            if st.button(
                "🚫 Storno",
                key=f"cancel_{nr}",
                use_container_width=True,
            ):

                set_status(
                    nr,
                    STATUS_CANCELLED,
                )

                st.rerun()


    elif status == STATUS_CANCELLED:

        if st.button(
            "↩ Storno zurücknehmen",
            key=f"undo_cancel_{nr}",
            use_container_width=True,
        ):

            set_status(
                nr,
                STATUS_OPEN,
            )

            st.rerun()


# ============================================================
# ABRECHNUNG
# ============================================================

st.markdown(
    '<div class="cv-section">5 · Abrechnung</div>',
    unsafe_allow_html=True,
)


prov_list = [
    order
    for order in driver_orders
    if status_of(order["nr"]) == STATUS_DONE
]


total_brutto = sum(
    float(order["betrag"])
    for order in prov_list
)

total_netto = total_brutto * 0.60


m1, m2, m3 = st.columns(3)

m1.metric(
    "Touren",
    len(prov_list),
)

m2.metric(
    "Brutto",
    money(total_brutto),
)

m3.metric(
    "Ca. Netto (~60 %)",
    money(total_netto),
)


if not prov_list:

    st.info(
        "Noch keine Touren übernommen."
    )

else:

    st.markdown("#### Übernommene Touren")

    df = pd.DataFrame([
        {
            "Datum": format_date(o["datum"]),
            "Auftrag": o["nr"],
            "Kennzeichen": o["kfz"],
            "Auftraggeber": o["ag"],
            "Tarif": o["tarif"],
            "Betrag": money(o["betrag"]),
        }
        for o in prov_list
    ])

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
    )


# ============================================================
# TARIF MANUELL ÄNDERN
# ============================================================

if prov_list:

    with st.expander(
        "✏️ Tarif / Festpreis anpassen"
    ):

        target = st.selectbox(
            "Tour",
            [
                f"{o['nr']} | {o['kfz']} | "
                f"{money(o['betrag'])}"
                for o in prov_list
            ],
        )

        tariff_options = (
            [t[0] for t in TARIFFS]
            + ["Freier Betrag..."]
        )

        tariff_choice = st.selectbox(
            "Neuer Tarif",
            tariff_options,
        )

        custom_amount = None

        if tariff_choice == "Freier Betrag...":

            custom_amount = st.number_input(
                "Betrag in €",
                min_value=0.0,
                max_value=500.0,
                value=25.0,
                step=5.0,
            )


        if st.button(
            "💾 Tarif speichern",
            use_container_width=True,
        ):

            target_nr = target.split(" | ")[0]

            order = st.session_state.orders[
                target_nr
            ]

            if tariff_choice == "Freier Betrag...":

                order["betrag"] = float(
                    custom_amount
                )

                order["tarif"] = (
                    f"Manuell "
                    f"({money(custom_amount)})"
                )

            else:

                for label, short, amount in TARIFFS:

                    if label == tariff_choice:

                        order["betrag"] = amount
                        order["tarif"] = short
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
# WHATSAPP
# ============================================================

st.markdown("#### 📋 WhatsApp")


driver_title = (
    active_driver
    if active_driver != "Alle Fahrer"
    else "Alle Fahrer"
)


wa_lines = [
    f"📋 *Bereitschafts-Abrechnung – {driver_title}*",
    "",
    (
        f"💰 *Gesamt:* "
        f"{len(prov_list)} Touren = "
        f"*{money(total_brutto)}*"
    ),
    "",
]


for order in prov_list:

    wa_lines.append(
        f"• *{order['nr']}* | "
        f"{order['datum']} | "
        f"{order['kfz']} | "
        f"{order['bemerkung']} "
        f"({money(order['betrag'])})"
    )


wa_text = "\n".join(wa_lines)


st.text_area(
    "Text kopieren",
    value=wa_text,
    height=150,
)


# ============================================================
# EXPORT
# ============================================================

st.markdown("#### 📤 Export")


exp1, exp2 = st.columns(2)


with exp1:

    if HAS_REPORTLAB and prov_list:

        pdf_bytes = generate_pdf_bytes(
            prov_list,
            driver_title,
            (
                f"{start_date.strftime('%d.%m.%Y')} – "
                f"{end_date.strftime('%d.%m.%Y')}"
            ),
        )

        st.download_button(
            "📄 PDF herunterladen",
            data=pdf_bytes,
            file_name=(
                "Abrechnung_"
                f"{datetime.now().strftime('%Y-%m-%d')}"
                ".pdf"
            ),
            mime="application/pdf",
            use_container_width=True,
        )

    elif not HAS_REPORTLAB:

        st.warning(
            "PDF-Modul ReportLab ist nicht installiert."
        )


with exp2:

    csv_buffer = io.StringIO()

    writer = csv.writer(
        csv_buffer,
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

    for order in prov_list:

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
        f"{total_brutto:.2f}",
    ])

    st.download_button(
        "💾 CSV exportieren",
        data=csv_buffer.getvalue().encode(
            "utf-8-sig"
        ),
        file_name="Abrechnung.csv",
        mime="text/csv",
        use_container_width=True,
        disabled=(len(prov_list) == 0),
    )


# ============================================================
# DEBUG / INFO
# ============================================================

with st.expander(
    "ℹ️ Hinweise zur Tarifberechnung",
    expanded=False,
):

    st.write(
        """
**ADAC Festpreisgebiete**

🟢 FP1 = 25,00 €

🟡 FP2 = 30,00 €

🟣 FP3 = 35,00 €

Die Zuordnung erfolgt anhand des Einsatzortes bzw.
der Postleitzahl aus der OnStreet-CSV.

Der Tarif kann bei Bedarf bei einer übernommenen
Tour manuell korrigiert werden.
"""
    )

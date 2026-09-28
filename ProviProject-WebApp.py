import csv
from datetime import datetime, date, timedelta
import io
import os
import re
import streamlit as st
import pandas as pd

# Optionales PDF-Modul
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

# Mobile & Desktop Page Config
st.set_page_config(
    page_title="Cuvenhaus Provision",
    page_icon="🚜",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Tarife Cuvenhaus
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
    ("Sonstiges: Werkstatt / Leihwagen (50,00 €)", "Werkstatt/Leihwagen", 50.00),
]

def format_date_with_weekday(date_str):
    for fmt in ["%d.%m.%Y", "%Y-%m-%d"]:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            days = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
            return f"{days[dt.weekday()]}, {dt.strftime('%d.%m.%Y')}"
        except ValueError:
            pass
    return date_str

def detect_adac_zone(einsatzort_str):
    text = einsatzort_str.lower()
    plz_match = re.search(r'\b(5\d{4}|50\d{3}|51\d{3})\b', text)
    plz = plz_match.group(1) if plz_match else ""

    # 1. Lila Zone (FP 3 - 35 €)
    fp3_plz = {
        "53359", "53913", "53919", "50321", "50354", "50374", "51503", "53819", 
        "53804", "53809", "53567", "53577", "53560", "53545", "53424", "53489", 
        "53501", "53474", "50996", "50997", "50999"
    }
    fp3_places = [
        "rheinbach", "swisttal", "heimerzheim", "odendorf", "weilerswist", "brühl", 
        "hürth", "erftstadt", "liblar", "rösrath", "neunkirchen", "seelscheid", "much", 
        "ruppichteroth", "uckerath", "blankenberg", "buchholz", "asbach", 
        "neustadt (wied)", "neustadt wied", "vettelschoß", "linz am rhein", "linz", 
        "remagen", "sinzig", "grafschaft", "neuenahr", "ahrweiler", "rodenkirchen"
    ]
    if plz in fp3_plz or any(re.search(r'\b' + re.escape(p) + r'\b', text) for p in fp3_places):
        return "FP 3", 35.00

    # 2. Gelbe Zone (FP 2 - 30 €)
    fp2_plz = {
        "53111", "53113", "53115", "53117", "53119", "53121", "53123", "53125", "53127", "53129",
        "53173", "53175", "53177", "53332", "53347", "50389", "53721", "53773", "53797", "53340",
        "53343", "53572"
    }
    fp2_places = [
        "siegburg", "hennef", "bornheim", "merten", "roisdorf", "alfter", "oedekoven", 
        "witterschlick", "wesseling", "lohmar", "meckenheim", "wachtberg", "unkel", 
        "oberpleis", "thomasberg", "ittenbach", "aegidienberg",
        "duisdorf", "endenich", "tannenbusch", "röttgen", "venusberg", "godesberg", "hardtberg"
    ]
    if plz in fp2_plz or any(re.search(r'\b' + re.escape(p) + r'\b', text) for p in fp2_places):
        return "FP 2", 30.00
    if "bonn" in text and not any(b in text for b in ["beuel", "geislar", "pützchen", "holzlar", "oberkassel", "vilich", "mehlem", "53225", "53227", "53229", "53179"]):
        return "FP 2", 30.00

    # 3. Grüne Zone (FP 1 - 25 €) inkl. Petersberg & Königswinter Tal
    return "FP 1", 25.00

def match_tariff_rule(stat, ag, art, nr, ort):
    ag_l = ag.lower()
    art_l = art.lower()
    combined = f"{stat.lower()} {art_l} {nr.lower()} {ort.lower()}"

    is_fehlfahrt = any(k in combined for k in ["fehlfahrt", "leerfahrt", "leer"])
    is_storno = any(k in combined for k in ["storno", "storniert", "abgebrochen", "widerrufen", "annulliert", "abgesagt"]) and not is_fehlfahrt

    if is_storno:
        return "Storno (0 €)", 0.00

    if "stadt bonn" in ag_l or ("stadt" in ag_l and "bonn" in ag_l):
        return ("Stadt Bonn Leerfahrt", 30.00) if is_fehlfahrt else ("Stadt Bonn Voll/Vers.", 30.00)

    if "parknotruf" in ag_l or "pnr" in combined:
        return ("Parknotruf Leerfahrt", 10.00) if is_fehlfahrt else ("Parknotruf Voll", 40.00)

    if "leihwagen" in combined or "mietwagen" in combined or "gutachten" in combined or ("werkstatt" in combined and "adac" not in combined):
        return "Werkstatt / Gutachten / Leihwagen", 50.00

    if "polizei bonn" in ag_l:
        return "Polizei Bonn", 30.00
    if "rhein-sieg" in ag_l or "siegburg" in ag_l or "kreispolizeibehörde" in ag_l:
        return "Polizei Siegburg", 30.00

    if "falschparker" in art_l and "stadt" not in ag_l:
        return "Falschparker privat", 30.00
    if "selbstzahler" in combined or "eigener wunsch" in combined:
        return "Selbstzahler", 30.00

    # ADAC Zonen-Tarif (für Schleppen UND Fehlfahrten)
    if "adac" in ag_l or "adac" in combined:
        zone_name, zone_rate = detect_adac_zone(ort)
        return (f"ADAC {zone_name} Fehlfahrt", zone_rate) if is_fehlfahrt else (f"ADAC {zone_name}", zone_rate)

    if is_fehlfahrt:
        return "Fehlfahrt (0 €)", 0.00

    return "Abschleppen / Bereitst.", 25.00

def parse_dt(annahme_str):
    for fmt in ["%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y"]:
        try:
            return datetime.strptime(annahme_str.strip(), fmt)
        except ValueError:
            pass
    return None

def generate_pdf_bytes(rows, driver_name, month_str):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    elements = []

    hdr = Table([[
        Paragraph(f"<font size=13><b>Mitarbeiter:</b> &nbsp; {driver_name}</font>", styles["Normal"]),
        Paragraph(f"<font size=13><b>Monat:</b> &nbsp; {month_str}</font>", styles["Normal"])
    ]], colWidths=[420, 360])
    hdr.setStyle(TableStyle([('BOTTOMPADDING', (0,0), (-1,-1), 8), ('ALIGN', (1,0), (1,0), 'RIGHT')]))
    elements.append(hdr)
    elements.append(Spacer(1, 4))

    table_data = [["DATUM", "AUFTRAGS-\nNUMMER", "KENNZEICHEN", "AUFTRAGGEBER", "BEMERKUNG", "BETRAG"]]
    total = 0.0
    for r in rows:
        b_val = float(r["betrag"])
        total += b_val
        table_data.append([
            r["datum"], r["nr"], r["kfz"], r["ag"], r["bemerkung"],
            f"{b_val:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
        ])
    for _ in range(max(0, 18 - len(rows))):
        table_data.append(["", "", "", "", "", ""])
    table_data.append(["", "", "", "", "SUMME:", f"{total:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")])

    t = Table(table_data, colWidths=[75, 120, 95, 165, 225, 100], repeatRows=1)
    t.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-2), 0.8, colors.black),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('ALIGN', (0,1), (0,-2), 'CENTER'),
        ('ALIGN', (5,1), (5,-1), 'RIGHT'),
        ('BOX', (4,-1), (5,-1), 1.0, colors.black),
        ('INNERGRID', (4,-1), (5,-1), 0.8, colors.black),
        ('FONTNAME', (4,-1), (-1,-1), 'Helvetica-Bold'),
    ]))
    elements.append(t)
    doc.build(elements)
    buf.seek(0)
    return buf.getvalue()

# Session State initialisieren
if "pool_orders" not in st.session_state:
    st.session_state.pool_orders = {}
if "prov_orders" not in st.session_state:
    st.session_state.prov_orders = {}
if "detected_drivers" not in st.session_state:
    st.session_state.detected_drivers = []
if "file_hash" not in st.session_state:
    st.session_state.file_hash = ""

# Header
st.title("🚜 Cuvenhaus Provisions-Manager")

# 1. Datei-Upload immer zuerst anzeigen
uploaded_file = st.file_uploader("📂 1. OnStreet CSV auswählen", type=["csv"])

# CSV verarbeiten
if uploaded_file is not None:
    current_hash = f"{uploaded_file.name}_{uploaded_file.size}"
    if st.session_state.file_hash != current_hash:
        content = uploaded_file.getvalue().decode("utf-8-sig", errors="ignore")
        lines = [l for l in content.splitlines() if l.strip()]
        if len(lines) >= 2:
            delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","
            reader = csv.reader(lines, delimiter=delimiter)
            rows = list(reader)
            headers = [h.strip().lower() for h in rows[0]]

            def get_idx(cands):
                for i, h in enumerate(headers):
                    if any(c in h for c in cands):
                        return i
                return None

            idx_stat = get_idx(["aktueller status", "status"])
            idx_nr = get_idx(["auftrag", "vorgang"])
            idx_fahrer = get_idx(["fahrer", "mitarbeiter"])
            idx_annahme = get_idx(["annahme", "datum"])
            idx_kfz = get_idx(["kennzeichen", "kfz"])
            idx_fahrzeug = get_idx(["fahrzeug", "typ"])
            idx_ag = get_idx(["auftraggeber", "kunde"])
            idx_art = get_idx(["auftragsart", "leistung"])
            idx_ort = get_idx(["einsatzort", "ort", "straße"])

            st.session_state.pool_orders.clear()
            st.session_state.prov_orders.clear()
            found_drivers = set()

            for r in rows[1:]:
                if not any(r): continue
                nr = r[idx_nr].strip() if idx_nr is not None and idx_nr < len(r) else ""
                if not nr: continue
                stat = r[idx_stat].strip() if idx_stat is not None and idx_stat < len(r) else ""
                fahrer = r[idx_fahrer].strip() if idx_fahrer is not None and idx_fahrer < len(r) else ""
                annahme = r[idx_annahme].strip() if idx_annahme is not None and idx_annahme < len(r) else ""
                kfz = r[idx_kfz].strip() if idx_kfz is not None and idx_kfz < len(r) else ""
                fahrzeug = r[idx_fahrzeug].strip() if idx_fahrzeug is not None and idx_fahrzeug < len(r) else ""
                ag = r[idx_ag].strip() if idx_ag is not None and idx_ag < len(r) else ""
                art = r[idx_art].strip() if idx_art is not None and idx_art < len(r) else ""
                ort = r[idx_ort].strip() if idx_ort is not None and idx_ort < len(r) else ""

                datum = annahme
                zeit = ""
                if " " in annahme:
                    parts = annahme.split(" ", 1)
                    datum = parts[0]
                    zeit = parts[1][:5]

                tarif, betrag = match_tariff_rule(stat, ag, art, nr, ort)
                bemerkung = f"{art} / {tarif}" if tarif not in art else art
                kfz_disp = f"{kfz} ({fahrzeug})" if kfz and fahrzeug else (kfz or fahrzeug or "-")

                if fahrer:
                    found_drivers.add(fahrer)

                st.session_state.pool_orders[nr] = {
                    "nr": nr, "fahrer": fahrer, "stat": stat, "datum": datum, "zeit": zeit,
                    "kfz": kfz_disp, "ag": ag, "art": art, "tarif": tarif, "betrag": betrag,
                    "bemerkung": bemerkung, "route": ort
                }

            st.session_state.detected_drivers = sorted(list(found_drivers))
            st.session_state.file_hash = current_hash
            st.rerun()

# Hinweis wenn noch keine Datei da ist
if not st.session_state.pool_orders and not st.session_state.prov_orders:
    st.info("👆 Bitte wähle oben deine OnStreet-CSV aus. Anschließend erscheinen automatisch die Touren und Fahrer.")
    st.stop()

# 2. Obere Leiste: Fahrer-Wahl & Schnellsuche nach Auftragsnummer oder Kennzeichen
top_c1, top_c2, top_c3 = st.columns([1.5, 2.5, 1])

with top_c1:
    driver_options = ["Alle Fahrer"] + st.session_state.detected_drivers
    default_idx = 0
    for idx, d in enumerate(driver_options):
        if "ross" in d.lower() or "can" in d.lower():
            default_idx = idx
            break
    active_driver = st.selectbox("👤 Fahrer filtern", driver_options, index=default_idx)

with top_c2:
    search_input = st.text_input("🔍 Auftrag nach Nummer oder Kennzeichen suchen:", placeholder="z. B. 26905 oder BN-QS77")

with top_c3:
    st.write("")
    st.write("")
    if st.button("➕ Übernehmen", use_container_width=True) and search_input:
        q = search_input.strip().lower()
        matched_nr = None
        for nr, o in st.session_state.pool_orders.items():
            if q in nr.lower() or q in o["kfz"].lower():
                matched_nr = nr
                break
        if matched_nr:
            st.session_state.prov_orders[matched_nr] = st.session_state.pool_orders.pop(matched_nr)
            st.success(f"Tour {matched_nr} übernommen!")
            st.rerun()
        elif any(q in k.lower() or q in v["kfz"].lower() for k, v in st.session_state.prov_orders.items()):
            st.info("Auftrag ist bereits in deiner Abrechnung.")
        else:
            st.warning("Kein passender Auftrag im Pool gefunden.")

# Schicht-Filter Leiste
st.markdown("---")
c_date, c_act1, c_act2 = st.columns([2, 1, 1])

with c_date:
    default_d = date.today()
    for o in list(st.session_state.pool_orders.values()) + list(st.session_state.prov_orders.values()):
        dt = parse_dt(o["datum"])
        if dt:
            default_d = dt.date()
            break

    selected_range = st.date_input(
        "📅 Schicht-Zeitraum auswählen",
        value=(default_d, default_d + timedelta(days=2))
    )

with c_act1:
    if st.button("⏰ Schicht übernehmen", use_container_width=True):
        if isinstance(selected_range, tuple) and len(selected_range) == 2:
            start_d, end_d = selected_range
            f_filter = active_driver.lower() if active_driver != "Alle Fahrer" else ""
            moved = 0
            for nr in list(st.session_state.pool_orders.keys()):
                o = st.session_state.pool_orders[nr]
                if f_filter and f_filter not in o["fahrer"].lower():
                    continue
                if o["betrag"] == 0.0:
                    continue
                dt = parse_dt(f"{o['datum']} {o['zeit']}")
                if dt and (start_d <= dt.date() <= end_d):
                    w = dt.weekday()
                    if w == 4 and dt.hour < 21:
                        continue
                    if w == 6 and (dt.hour > 21 or (dt.hour == 21 and dt.minute > 0)):
                        continue
                    st.session_state.prov_orders[nr] = st.session_state.pool_orders.pop(nr)
                    moved += 1
            st.rerun()

with c_act2:
    if st.button("⚡ Alle Touren rüberholen", use_container_width=True):
        f_filter = active_driver.lower() if active_driver != "Alle Fahrer" else ""
        for nr in list(st.session_state.pool_orders.keys()):
            o = st.session_state.pool_orders[nr]
            if f_filter and f_filter not in o["fahrer"].lower():
                continue
            if o["betrag"] > 0:
                st.session_state.prov_orders[nr] = st.session_state.pool_orders.pop(nr)
        st.rerun()

# Kennzahlen
f_name = active_driver.lower() if active_driver != "Alle Fahrer" else ""
prov_list = [o for o in st.session_state.prov_orders.values() if not f_name or f_name in o["fahrer"].lower()]
pool_list = [o for o in st.session_state.pool_orders.values() if not f_name or f_name in o["fahrer"].lower()]

total_brutto = sum(float(o["betrag"]) for o in prov_list)
total_netto = total_brutto * 0.60

m1, m2, m3 = st.columns(3)
m1.metric("📋 Touren auf Zettel", f"{len(prov_list)}")
m2.metric("💰 Brutto-Provision", f"{total_brutto:,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."))
m3.metric("💵 Ca. Netto (~60%)", f"{total_netto:,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."))

st.markdown("---")

# ==========================================
# 2-SPALTEN-LAYOUT
# ==========================================
col_pool, col_zettel = st.columns([1, 1], gap="medium")

# LINKE SPALTE: ONSTREET POOL
with col_pool:
    st.subheader("📥 1. OnStreet Pool (Offene Touren)")
    
    if pool_list:
        quick_add = st.selectbox(
            "➕ Tour in Abrechnung schieben:",
            ["- Wählen -"] + [f"{o['nr']} | {o['kfz']} | {o['ag']} ({o['datum']})" for o in pool_list],
            key="sb_add_pool"
        )
        if quick_add != "- Wählen -":
            target_nr = quick_add.split(" | ")[0]
            st.session_state.prov_orders[target_nr] = st.session_state.pool_orders.pop(target_nr)
            st.rerun()

        df_pool = pd.DataFrame([{
            "Auftrag": o["nr"],
            "Datum": format_date_with_weekday(o["datum"]),
            "Zeit": o["zeit"],
            "Kennzeichen": o["kfz"],
            "Kunde": o["ag"],
            "Status": o["stat"]
        } for o in pool_list])
        st.dataframe(df_pool, use_container_width=True, hide_index=True, height=450)
    else:
        st.info("Alle offenen Fahrten übernommen oder Pool ist leer.")

# RECHTE SPALTE: ABRECHNUNGSZETTEL
with col_zettel:
    st.subheader("💰 2. Deine Abrechnung (Cuvenhaus-Zettel)")
    
    if prov_list:
        act_c1, act_c2 = st.columns(2)
        with act_c1:
            quick_rem = st.selectbox(
                "↩️ Zurück in den Pool:",
                ["- Wählen -"] + [f"{o['nr']} | {o['kfz']} ({float(o['betrag']):.2f} €)" for o in prov_list],
                key="sb_rem_prov"
            )
            if quick_rem != "- Wählen -":
                target_nr = quick_rem.split(" | ")[0]
                st.session_state.pool_orders[target_nr] = st.session_state.prov_orders.pop(target_nr)
                st.rerun()

        with act_c2:
            storno_sel = st.selectbox(
                "🚫 Als Storno markieren (0 €):",
                ["- Wählen -"] + [f"{o['nr']} | {o['kfz']}" for o in prov_list if o["betrag"] > 0],
                key="sb_storno"
            )
            if storno_sel != "- Wählen -":
                target_nr = storno_sel.split(" | ")[0]
                st.session_state.prov_orders[target_nr]["betrag"] = 0.0
                st.session_state.prov_orders[target_nr]["bemerkung"] = "Storno (0 €)"
                st.rerun()

        # Tarif / Festpreis manuell ändern
        with st.expander("✏️ Tarif / Festpreis anpassen (z. B. ADAC FP 1 / 2 / 3)", expanded=False):
            ed_c1, ed_c2 = st.columns([1.2, 1.5])
            with ed_c1:
                edit_target = st.selectbox(
                    "Auftrag wählen:",
                    ["- Wählen -"] + [f"{o['nr']} | {o['kfz']} (aktuell {float(o['betrag']):.2f} €)" for o in prov_list],
                    key="sb_edit_target"
                )
            with ed_c2:
                tariff_names = [t[0] for t in TARIFFS] + ["Freier Betrag..."]
                selected_tariff_opt = st.selectbox("Neuer Tarif:", tariff_names, key="sb_edit_tariff")
            
            custom_amount = 0.0
            if selected_tariff_opt == "Freier Betrag...":
                custom_amount = st.number_input("Betrag in €:", min_value=0.0, max_value=500.0, value=25.0, step=5.0)

            if st.button("💾 Tarif aktualisieren", use_container_width=True, key="btn_apply_tariff"):
                if edit_target != "- Wählen -":
                    target_nr = edit_target.split(" | ")[0]
                    if target_nr in st.session_state.prov_orders:
                        cur_art = st.session_state.prov_orders[target_nr].get("art", "Abschleppen")
                        if selected_tariff_opt == "Freier Betrag...":
                            st.session_state.prov_orders[target_nr]["betrag"] = float(custom_amount)
                            st.session_state.prov_orders[target_nr]["tarif"] = f"Manuell ({custom_amount:.2f} €)"
                            st.session_state.prov_orders[target_nr]["bemerkung"] = f"{cur_art} / Manuell"
                        else:
                            for t_label, t_short, t_val in TARIFFS:
                                if t_label == selected_tariff_opt:
                                    st.session_state.prov_orders[target_nr]["betrag"] = t_val
                                    st.session_state.prov_orders[target_nr]["tarif"] = t_short
                                    st.session_state.prov_orders[target_nr]["bemerkung"] = f"{cur_art} / {t_short}"
                                    break
                        st.success(f"Tarif für Auftrag {target_nr} erfolgreich angepasst!")
                        st.rerun()
                else:
                    st.warning("Bitte wähle zuerst einen Auftrag aus.")

        df_zettel = pd.DataFrame([{
            "Datum": format_date_with_weekday(o["datum"]),
            "Auftrag": o["nr"],
            "Kennzeichen": o["kfz"],
            "Auftraggeber": o["ag"],
            "Bemerkung": o["bemerkung"],
            "Betrag": f"{float(o['betrag']):.2f} €"
        } for o in prov_list])
        st.dataframe(df_zettel, use_container_width=True, hide_index=True, height=420)
    else:
        st.info("Noch keine Touren auf dem Abrechnungszettel.")

# Export-Bereich
st.markdown("---")
st.subheader("📤 Export & WhatsApp")

drv_title = f" – {active_driver}" if active_driver != "Alle Fahrer" else ""
wa_lines = [
    f"📋 *Bereitschafts-Abrechnung{drv_title}*",
    f"💰 *Gesamt:* {len(prov_list)} Touren = *{total_brutto:,.2f} €*\n".replace(",", "X").replace(".", ",").replace("X", ".")
]
for o in prov_list:
    wa_lines.append(f"• *{o['nr']}* | {o['datum']} | {o['kfz']} | {o['bemerkung']} ({float(o['betrag']):.2f} €)")
wa_text = "\n".join(wa_lines)

exp1, exp2 = st.columns(2)

with exp1:
    st.text_area("📋 Text für WhatsApp (markieren & kopieren)", value=wa_text, height=140)

with exp2:
    if HAS_REPORTLAB and prov_list:
        pdf_name = active_driver if active_driver != "Alle Fahrer" else "Can-Erik Ross"
        pdf_bytes = generate_pdf_bytes(prov_list, pdf_name, datetime.now().strftime("%B %Y"))
        st.download_button(
            label="📄 Cuvenhaus PDF herunterladen",
            data=pdf_bytes,
            file_name=f"Abrechnung_{datetime.now().strftime('%Y-%m-%d')}.pdf",
            mime="application/pdf",
            use_container_width=True
        )

    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf, delimiter=";")
    writer.writerow(["DATUM", "AUFTRAGS-NUMMER", "KENNZEICHEN", "AUFTRAGGEBER", "BEMERKUNG", "BETRAG"])
    for o in prov_list:
        writer.writerow([o["datum"], o["nr"], o["kfz"], o["ag"], o["bemerkung"], f"{float(o['betrag']):.2f}"])
    writer.writerow(["", "", "", "", "SUMME:", f"{total_brutto:.2f}"])
    st.download_button(
        label="💾 CSV exportieren",
        data=csv_buf.getvalue().encode("utf-8-sig"),
        file_name="Abrechnung.csv",
        mime="text/csv",
        use_container_width=True
    )

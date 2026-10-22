"""Regelbasierte Erstellung einer Provisionsliste aus natürlichsprachlichen Datumsangaben.

Keine KI-Anfrage nötig: Datumsangaben und Auftragssuche bleiben lokal.
"""
import csv
import io
import re
from datetime import date, datetime, timedelta

import streamlit as st


DATE_RE = re.compile(r"(?<!\d)(\d{1,2})[.]\s*(\d{1,2})[.]\s*(\d{4})(?!\d)")


def parse_weekends(text):
    """Liest konkrete deutsche Datumsangaben; niemals ein Datum erraten."""
    matches = DATE_RE.findall(text)
    if not matches:
        raise ValueError(
            "Bitte konkrete Daten angeben, z. B. "
            "'Erstelle meine Provisionsliste für 16.10.2026 und 23.10.2026'."
        )
    if len(matches) > 12:
        raise ValueError("Bitte maximal 12 Datumsangaben auf einmal verwenden.")
    fridays = set()
    for day, month, year in matches:
        try:
            supplied = date(int(year), int(month), int(day))
        except ValueError:
            raise ValueError("Ein angegebenes Datum ist ungültig.") from None
        friday = supplied - timedelta(days=(supplied.weekday() - 4) % 7)
        fridays.add(friday)
    return sorted(fridays)


def _belongs(order, driver):
    if driver == "Alle Fahrer":
        return True
    norm = lambda x: " ".join(str(x or "").lower().replace("-", " ").split())
    return norm(driver) in norm(order.get("fahrer"))


def _csv(orders):
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["DATUM", "ZEIT", "AUFTRAGS-NUMMER", "KENNZEICHEN",
                     "FAHRER", "AUFTRAGGEBER", "EINSATZORT", "ZIELORT",
                     "ZONE", "BEMERKUNG", "BETRAG"])
    for o in orders:
        writer.writerow([
            o.get("datum", ""), o.get("zeit", ""), o.get("nr", ""),
            o.get("kfz", ""), o.get("fahrer", ""), o.get("ag", ""),
            o.get("start", ""), o.get("ziel", ""), o.get("zone_text", ""),
            o.get("bemerkung", ""),
            f"{float(o.get('betrag') or 0):.2f}",
        ])
    writer.writerow(["", "", "", "", "", "", "", "", "", "SUMME",
                     f"{sum(float(o.get('betrag') or 0) for o in orders):.2f}"])
    return buf.getvalue().encode("utf-8-sig")


def render_command_panel(all_orders, active_driver, driver_options,
                         is_in_standby, is_storno_order,
                         calculate_adac_order, is_adac_order):
    with st.expander("🗣️ Provisionsliste per Text erstellen", expanded=False):
        st.caption(
            "Beispiel: 'Erstelle meine Provisionsliste für die Wochenenden "
            "16.10.2026 und 23.10.2026'. Die App sucht die Aufträge "
            "in der bereits importierten CSV. Keine Daten gehen an eine KI."
        )
        command = st.text_area("Dein Auftrag", height=82, key="provi_command")
        driver = st.selectbox(
            "Fahrer für die neue Liste",
            [d for d in driver_options if d != "Alle Fahrer"],
            index=max(0, [d for d in driver_options if d != "Alle Fahrer"].index(active_driver))
            if active_driver in driver_options and active_driver != "Alle Fahrer" else 0,
            key="provi_command_driver",
        ) if len(driver_options) > 1 else None
        if not driver:
            st.info("Kein Fahrer in der importierten CSV vorhanden.")
            return
        if st.button("🔎 Liste vorbereiten", key="provi_command_prepare"):
            try:
                fridays = parse_weekends(command)
            except ValueError as exc:
                st.error(str(exc))
                return
            selected = []
            for order in all_orders:
                if not _belongs(order, driver):
                    continue
                if not any(is_in_standby(order, fri) for fri in fridays):
                    continue
                if is_storno_order(order.get("stat", ""),
                                   order.get("art", ""), order.get("raw_nr", ""),
                                   order.get("ag", "")):
                    continue
                selected.append(order)
            st.session_state.provi_command_result = {
                "fridays": [f.isoformat() for f in fridays],
                "driver": driver,
                "numbers": [o["nr"] for o in selected],
                "file_hash": st.session_state.file_hash,
            }
        result = st.session_state.get("provi_command_result")
        if not result or result["file_hash"] != st.session_state.file_hash:
            return
        orders_by_number = {o["nr"]: o for o in all_orders}
        selected = [orders_by_number[n] for n in result["numbers"]
                    if n in orders_by_number]
        st.write(
            f"**{result['driver']}** · "
            f"{len(result['fridays'])} Wochenende(n) · "
            f"{len(selected)} passende Aufträge"
        )
        st.caption("Freitag 21:00 bis Sonntag 21:00, Zeitbasis CSV-Annahme. "
                   "Stornos werden ausgeschlossen. Vor Abrechnung manuell kontrollieren.")
        if not selected:
            st.warning("Keine passenden Aufträge im importierten CSV gefunden.")
            return
        if st.button("✅ Vorschau berechnen", key="provi_command_calculate"):
            # Bestehende Tarif- und Geofence-Logik verwenden; dabei
            # dieselben Datensätze wie in der regulären Ansicht.
            for order in selected:
                if is_adac_order(order.get("ag", ""), order.get("art", ""),
                                 order.get("raw_nr", ""), order.get("stat", "")):
                    calculate_adac_order(order)
            st.session_state.provi_command_computed = (
                result["file_hash"], tuple(result["numbers"])
            )
        if st.session_state.get("provi_command_computed") != (
            result["file_hash"], tuple(result["numbers"])
        ):
            st.info("Bitte erst die Vorschau berechnen, dann exportieren.")
            return
        total = sum(float(o.get("betrag") or 0) for o in selected)
        st.metric("Gesamt laut CSV/Tariflogik", f"{total:.2f} €")
        st.dataframe(
            [{"Datum": o.get("datum"), "Zeit": o.get("zeit"),
              "Auftrag": o["nr"], "Fahrer": o.get("fahrer"),
              "Zone": o.get("zone_text"), "Betrag": o.get("betrag")}
             for o in selected],
            hide_index=True, use_container_width=True,
        )
        st.download_button(
            "💾 Provisionsliste als CSV herunterladen",
            data=_csv(selected), mime="text/csv",
            file_name="Provisionsliste_" + result["driver"].replace(" ", "_")
                      + "_" + result["fridays"][0] + ".csv",
            key="provi_command_download",
        )

"""Interaktive Karte der OnStreet-Festpreisgebiete für die Auftragsprüfung."""
import math
import streamlit as st
import pydeck as pdk


def render_fp_map(order, fp1, fp2, fp3):
    def polygon(points):
        return [[float(lon), float(lat)] for lat, lon in points]

    zones = [
        {"name": "FP1 · 25 €", "coordinates": polygon(fp1), "fill": [68, 247, 0, 45], "line": [60, 175, 0, 220]},
        {"name": "FP2 · 30 €", "coordinates": polygon(fp2), "fill": [245, 249, 1, 32], "line": [180, 180, 0, 210]},
        {"name": "FP3 · 35 €", "coordinates": polygon(fp3), "fill": [249, 5, 249, 22], "line": [170, 0, 170, 205]},
    ]
    markers = []
    for label, lat_key, lon_key, color in [
        ("Einsatzort", "start_lat", "start_lon", [0, 125, 240, 240]),
        ("Zielort", "target_lat", "target_lon", [230, 65, 40, 240]),
    ]:
        lat, lon = order.get(lat_key), order.get(lon_key)
        if lat is not None and lon is not None:
            markers.append({"name": label, "lat": float(lat), "lon": float(lon), "color": color})
    if not markers:
        st.warning("Keine verwertbaren Koordinaten. Bitte zuerst die Adresse neu prüfen.")
        return
    lat = sum(m["lat"] for m in markers) / len(markers)
    lon = sum(m["lon"] for m in markers) / len(markers)
    if len(markers) > 1:
        span = max(
            abs(markers[0]["lat"] - markers[1]["lat"]) * 111,
            abs(markers[0]["lon"] - markers[1]["lon"]) * 71,
        )
        zoom = max(8.1, min(14.2, 12.5 - math.log2(max(span, 0.25))))
    else:
        zoom = 12.8
    deck = pdk.Deck(
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom, pitch=0),
        layers=[
            pdk.Layer(
                "PolygonLayer", data=zones, get_polygon="coordinates",
                get_fill_color="fill", get_line_color="line",
                stroked=True, filled=True, get_line_width=3,
                line_width_min_pixels=2, pickable=True,
            ),
            pdk.Layer(
                "ScatterplotLayer", data=markers, get_position="[lon, lat]",
                get_fill_color="color", get_radius=75, radius_min_pixels=7,
                radius_max_pixels=15, pickable=True,
            ),
        ],
        tooltip={"text": "{name}"},
    )
    st.pydeck_chart(deck, use_container_width=True)
    st.caption("FP1 grün · FP2 gelb · FP3 lila | Blau = Einsatzort · Rot = Zielort. "
               "OSM/CARTO-Kartenhintergrund benötigt Internet; Geofences stammen aus dem Code. "
               "Bei überlappenden Flächen gilt FP1 vor FP2 vor FP3.")

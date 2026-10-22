"""Cuvenhaus Betriebs-Dashboard: datensparsame Historie, Prüfungen, Kalender und CSV-Vergleich.

Datenspeicherung: SQLite lokal (nicht restartfest auf Community Cloud),
Für Streamlit Community Cloud sind regelmäßige Backups nötig. Keine Kundendaten
in der Historie; Auftragskennungen nur als Hash mit privatem Secret.
"""
import hashlib
import hmac
import json
import os
import sqlite3
import autosicherung
from collections import Counter
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

import pandas as pd
import streamlit as st


def setting(name, default=""):
    try:
        return st.secrets.get(name, default) or os.environ.get(name, default)
    except (FileNotFoundError, OSError):
        return os.environ.get(name, default)


DB_PATH = os.environ.get("CUVENHAUS_SQLITE_PATH", "cuvenhaus_local_v2.sqlite3")


class Storage:
    """Gemeinsame lokale SQLite-Datei, kostenlos, ohne externen Dienst.

    Achtung: Streamlit Community Cloud stellt keine dauerhaften Dateien bereit.
    """
    def __init__(self):
        # Beim App-Neustart fehlende lokale DB automatisch aus privatem GitHub laden.
        self.auto_restored = autosicherung.restore_if_missing(DB_PATH)
        self._dirty = False
        self.conn = sqlite3.connect(DB_PATH, timeout=30)
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.init()

    def execute(self, sql, args=()):
        with self.conn:
            cur = self.conn.execute(sql, args)
            result = cur.fetchall() if sql.lstrip().upper().startswith("SELECT") else []
            if sql.lstrip().split(maxsplit=1)[0].upper() in ("INSERT", "UPDATE", "DELETE", "REPLACE") and cur.rowcount > 0:
                self._dirty = True
            return result

    def init(self):
        self.execute("""CREATE TABLE IF NOT EXISTS shift_calendar (
            user_id TEXT NOT NULL, friday TEXT NOT NULL,
            PRIMARY KEY(user_id, friday))""")
        self.execute("""CREATE TABLE IF NOT EXISTS billing_history (
            user_id TEXT NOT NULL, source_hash TEXT NOT NULL,
            driver TEXT NOT NULL, period TEXT NOT NULL,
            count INTEGER NOT NULL, total REAL NOT NULL,
            saved_at TEXT NOT NULL,
            PRIMARY KEY(user_id, source_hash, driver, period))""")
        self.execute("""CREATE TABLE IF NOT EXISTS import_snapshots (
            user_id TEXT NOT NULL, source_hash TEXT NOT NULL,
            saved_at TEXT NOT NULL, fingerprint_json TEXT NOT NULL,
            PRIMARY KEY(user_id, source_hash))""")

    def close(self):
        try:
            if self._dirty:
                autosicherung.save(self.conn)
        finally:
            self.conn.close()


def prune_history(db, today=None):
    """90 Tage alte Historie und vergangene Bereitschaften entfernen."""
    today = today or date.today()
    cutoff = (today - timedelta(days=90)).isoformat()
    db.execute("DELETE FROM billing_history WHERE saved_at < ?", (cutoff,))
    db.execute("DELETE FROM import_snapshots WHERE saved_at < ?", (cutoff,))
    db.execute("DELETE FROM shift_calendar WHERE friday < ?", (cutoff,))


def driver_key(driver):
    """CSV-Fahrername als Zuordnung, ohne Login."""
    return "fahrer:" + " ".join(str(driver).strip().casefold().split())


def fingerprint(order, secret):
    # Kein Kennzeichen oder Name speichern, ausschließlich HMAC einer Auftragskennung.
    nr = str(order.get("nr", "")).strip()
    if not nr:
        return None
    return hmac.new(secret.encode(), nr.encode(), hashlib.sha256).hexdigest()


def signatures(orders):
    secret = setting("HISTORY_HMAC_SECRET")
    if not secret or len(secret) < 24:
        return None
    result = {}
    for o in orders:
        key = fingerprint(o, secret)
        if key:
            payload = {
                "status": str(o.get("stat", "")),
                "amount": round(float(o.get("betrag") or 0), 2),
                "date": str(o.get("datum", "")),
            }
            # Keine Roh-Auftragsdaten persistieren.
            result[key] = payload
    return result


def review(orders, manual_tariffs=None):
    issues = []
    seen = set()
    for o in orders:
        nr = str(o.get("nr", ""))
        problems = []
        if nr in seen:
            problems.append("Doppelte Auftragsnummer in der Auswahl")
        seen.add(nr)
        if o.get("zone_warning"):
            problems.append("FP-Zone / Adresse prüfen")
        amount = float(o.get("betrag") or 0)
        if amount < 0:
            problems.append("Negativer Provisionsbetrag")
        if amount == 0 and "storno" not in str(o.get("stat", "")).lower():
            problems.append("0 € ohne eindeutigen Storno-Status")
        if amount > 300:
            problems.append("Ungewöhnlich hoher Einzelbetrag: Tarif prüfen")
        if problems:
            issues.append({"Auftrag": nr, "Hinweise": "; ".join(problems)})
    return issues


def friday_for(day):
    return day - timedelta(days=(day.weekday() - 4) % 7)


def dashboard(orders, db, user):
    st.subheader("📊 Verdienst-Dashboard")
    if orders:
        df = pd.DataFrame([
            {"Tag": str(o.get("datum", "")), "Betrag": float(o.get("betrag") or 0)}
            for o in orders
        ])
        a, b, c = st.columns(3)
        a.metric("Touren der Auswahl", len(df))
        b.metric("Provision gesamt", f"{df['Betrag'].sum():.2f} €")
        c.metric("Ø pro Tour", f"{df['Betrag'].mean():.2f} €")
        st.bar_chart(df.groupby("Tag", as_index=True)["Betrag"].sum())
    rows = db.execute(
        "SELECT period, SUM(total), SUM(count) FROM billing_history WHERE user_id=? GROUP BY period ORDER BY period DESC LIMIT 20",
        (user,),
    )
    if rows:
        st.caption("Gespeicherte Abrechnungen")
        st.dataframe(pd.DataFrame(rows, columns=["Zeitraum", "Provision €", "Touren"]), hide_index=True)


def calendar_panel(db, user):
    st.subheader('🗓️ Bereitschaftskalender')
    month = st.date_input('Monat auswählen', value=date.today().replace(day=1), key='suite_calendar_month')
    first = month.replace(day=1)
    next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    fridays = []
    cursor = friday_for(first)
    while cursor < next_month:
        if cursor.month == first.month:
            fridays.append(cursor)
        cursor += timedelta(days=7)
    old_rows = db.execute('SELECT friday FROM shift_calendar WHERE user_id=?', (user,))
    old = {x[0] for x in old_rows}
    st.caption('Alle Wochenenden eines Monats auf einmal markieren und speichern.')
    picked = []
    for fri in fridays:
        label = f"Fr {fri.strftime('%d.%m.')} bis So {(fri + timedelta(days=2)).strftime('%d.%m.')}"
        if st.checkbox(label, value=fri.isoformat() in old, key='shift_' + user + fri.isoformat()):
            picked.append(fri.isoformat())
    if st.button('💾 Monatsbereitschaften speichern', key='suite_save_month'):
        for fri in fridays:
            db.execute('DELETE FROM shift_calendar WHERE user_id=? AND friday=?', (user, fri.isoformat()))
        for fri in picked:
            db.execute('INSERT INTO shift_calendar(user_id,friday) VALUES(?,?) ON CONFLICT(user_id,friday) DO NOTHING', (user, fri))
        st.success(f'{len(picked)} Bereitschaftswochenenden gespeichert.')
    st.caption('Gespeichert für: ' + user.replace('fahrer:', ''))


def versions_panel(all_orders, source_hash, db, user):
    st.subheader("🔄 CSV-Versionsvergleich")
    current = signatures(all_orders)
    if current is None:
        st.warning("Bitte HISTORY_HMAC_SECRET (mindestens 24 Zeichen) in Streamlit Secrets setzen.")
        return
    rows = db.execute(
        "SELECT source_hash, saved_at, fingerprint_json FROM import_snapshots WHERE user_id=? ORDER BY saved_at DESC LIMIT 15",
        (user,),
    )
    previous = [(h, ts, json.loads(blob)) for h, ts, blob in rows if h != source_hash]
    if previous:
        labels = [f"{ts} · {h[:10]}" for h, ts, _ in previous]
        index = st.selectbox("Mit importierter Version vergleichen", range(len(labels)),
                             format_func=lambda i: labels[i], key="suite_version_choice")
        old = previous[index][2]
        fresh = set(current) - set(old)
        removed = set(old) - set(current)
        changed = [k for k in set(current) & set(old) if current[k] != old[k]]
        a, b, c = st.columns(3)
        a.metric("Neue Aufträge", len(fresh))
        b.metric("Entfallene Aufträge", len(removed))
        c.metric("Status-/Betragsänderungen", len(changed))
        st.caption("Vergleich auf Basis gehashter Auftragsnummern. "
                   "Keine personenbezogenen Details der Altversion gespeichert.")
    else:
        st.info("Noch keine frühere CSV-Version gespeichert.")
    if st.button("Aktuelle CSV-Version speichern", key="suite_save_version"):
        db.execute(
            "INSERT INTO import_snapshots(user_id,source_hash,saved_at,fingerprint_json) "
            "VALUES(?,?,?,?) ON CONFLICT(user_id,source_hash) DO UPDATE SET "
            "saved_at=excluded.saved_at, fingerprint_json=excluded.fingerprint_json",
            (user, source_hash, datetime.now().isoformat(timespec="seconds"),
             json.dumps(current, ensure_ascii=False)),
        )
        st.success("Versionsstand gespeichert.")


def render_suite(all_orders, selected_orders, source_hash, driver, period):
    with st.expander("🧰 Cuvenhaus Manager 2.0 · Kontrolle & Historie", expanded=False):
        st.caption("Sichere Erweiterung: keine Änderung an bestehenden Tarifberechnungen.")
        if driver == "Alle Fahrer":
            st.info("Bitte einen Fahrer aus dem CSV-Export auswählen.")
            return
        user = driver_key(driver)
        st.caption(f"Fahrer aus CSV: {driver} · Keine Anmeldung erforderlich.")
        try:
            backup_ready = autosicherung.config() is not None
        except autosicherung.BackupError as exc:
            st.error(str(exc))
            return
        if backup_ready:
            st.caption("SQLite lokal · GitHub-Auto-Backup aktiviert (privat, komprimiert, NICHT verschlüsselt).")
        else:
            st.warning("⚠️ Nur lokale SQLite-Datei: Auf Streamlit Community Cloud können "
                       "Daten verloren gehen. Für automatische Wiederherstellung "
                       "GITHUB_BACKUP_REPO und GITHUB_BACKUP_TOKEN in Secrets einrichten.")

        try:
            db = Storage()
            prune_history(db)
        except Exception:
            st.error("Lokale Datenbank konnte nicht geöffnet werden.")
            return
        try:
            tabs = st.tabs(["🔎 Provisionsprüfung", "📊 Dashboard", "🔄 CSV-Vergleich", "🗓️ Kalender"])
            with tabs[0]:
                issues = review(selected_orders)
                st.metric("Auffällige Aufträge", len(issues))
                if issues:
                    st.dataframe(pd.DataFrame(issues), hide_index=True, use_container_width=True)
                else:
                    st.success("Keine Auffälligkeiten nach den vorhandenen Plausibilitätsregeln.")
                if st.button("Aktuelle Abrechnung archivieren", key="suite_save_bill"):
                    db.execute(
                        "INSERT INTO billing_history(user_id,source_hash,driver,period,count,total,saved_at) "
                        "VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,source_hash,driver,period) "
                        "DO UPDATE SET count=excluded.count,total=excluded.total,saved_at=excluded.saved_at",
                        (user, source_hash, driver, period, len(selected_orders),
                         sum(float(o.get("betrag") or 0) for o in selected_orders),
                         datetime.now().isoformat(timespec="seconds")),
                    )
                    st.success("Abrechnungssumme archiviert.")
            with tabs[1]:
                dashboard(selected_orders, db, user)
            with tabs[2]:
                versions_panel(all_orders, source_hash, db, user)
            with tabs[3]:
                calendar_panel(db, user)
        finally:
            try:
                db.close()
            except autosicherung.BackupError as exc:
                st.error("⚠️ Automatische Datensicherung fehlgeschlagen: " + str(exc))

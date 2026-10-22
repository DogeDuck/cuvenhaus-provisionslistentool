"""Simple shared access gate, configured only through Streamlit Secrets.

This is an access barrier, not user identity, auditing or rate-limited authentication.
"""
import hashlib
import hmac
import os
import streamlit as st


def _configured_pin():
    try:
        return str(st.secrets.get("INTERNAL_ACCESS_PIN", "")).strip()
    except Exception:
        return os.environ.get("INTERNAL_ACCESS_PIN", "").strip()


def require_access():
    pin = _configured_pin()
    if not pin:
        st.error("Interner Zugang nicht eingerichtet. INTERNAL_ACCESS_PIN in Streamlit Secrets setzen.")
        st.stop()
    fingerprint = hashlib.sha256(pin.encode("utf-8")).hexdigest()
    if st.session_state.get("access_fingerprint") == fingerprint:
        return
    st.title("🔐 Cuvenhaus · Interner Zugang")
    st.caption("Hinweis: Onstreet Login Firmen-Nummer")
    with st.form("internal_access"):
        candidate = st.text_input("Passwort", type="password")
        submitted = st.form_submit_button("Anmelden", use_container_width=True)
    if submitted:
        if hmac.compare_digest(candidate.encode("utf-8"), pin.encode("utf-8")):
            st.session_state.access_fingerprint = fingerprint
            st.rerun()
        else:
            st.error("Passwort nicht korrekt.")
    st.stop()

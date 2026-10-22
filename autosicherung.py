"""Optional encrypted auto-backup of SQLite to a PRIVATE GitHub repository.

Only encrypted bytes ever leave the app. A private repository and narrowly
scoped fine-grained PAT with Contents read/write are required. A local SQLite
file alone is NOT durable on Streamlit Community Cloud.
"""
import base64
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zlib

from cryptography.fernet import Fernet, InvalidToken

BACKUP_PATH = "cuvenhaus/monthly-state.fernet"
MAX_BACKUP = 12 * 1024 * 1024
MAX_RAW = 65 * 1024 * 1024


class BackupError(RuntimeError):
    pass


def config():
    def value(name):
        environment = os.environ.get(name, "")
        try:
            import streamlit as st
            return str(st.secrets.get(name, environment) or "").strip()
        except Exception:
            # Beim lokalen Aufruf / Test fehlt secrets.toml möglicherweise.
            return str(environment).strip()
    repo = value("GITHUB_BACKUP_REPO")
    token = value("GITHUB_BACKUP_TOKEN")
    key = value("BACKUP_ENCRYPTION_KEY")
    if not any((repo, token, key)):
        return None
    if not all((repo, token, key)):
        raise BackupError("Automatische Sicherung unvollständig: GITHUB_BACKUP_REPO, GITHUB_BACKUP_TOKEN und BACKUP_ENCRYPTION_KEY erforderlich.")
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+", repo):
        raise BackupError("Ungültiger GitHub-Repositoryname.")
    try:
        Fernet(key.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise BackupError("BACKUP_ENCRYPTION_KEY muss ein gültiger Fernet-Schlüssel sein.") from exc
    return repo, token, key


def _request(repo, token, endpoint, method="GET", payload=None):
    url = "https://api.github.com/repos/" + repo + endpoint
    headers = {"Authorization": "Bearer " + token,
               "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "Cuvenhaus-Manager-Backup"}
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        if exc.code in (409, 422):
            raise BackupError("GitHub-Sicherungskonflikt. Bitte Seite neu laden und erneut speichern.") from exc
        raise BackupError("GitHub-Sicherung fehlgeschlagen (HTTP " + str(exc.code) + ").") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise BackupError("GitHub ist für die automatische Sicherung nicht erreichbar.") from exc


def _repo_info(repo, token):
    info = _request(repo, token, "")
    if not info:
        raise BackupError("Privates GitHub-Backup-Repository nicht gefunden oder Token ohne Zugriff.")
    if not info.get("private"):
        raise BackupError("Backup abgelehnt: GitHub-Repository muss PRIVAT sein.")


def _remote_file(repo, token):
    path = "/contents/" + urllib.parse.quote(BACKUP_PATH, safe="/")
    obj = _request(repo, token, path)
    if not obj:
        return None, None
    sha = obj.get("sha")
    encoded = obj.get("content")
    if not encoded or obj.get("encoding") != "base64":
        blob = _request(repo, token, "/git/blobs/" + urllib.parse.quote(sha, safe=""))
        if not blob or blob.get("encoding") != "base64":
            raise BackupError("GitHub-Backup kann nicht gelesen werden.")
        encoded = blob["content"]
    encrypted = base64.b64decode(encoded)
    if len(encrypted) > MAX_BACKUP:
        raise BackupError("Sicherung ist größer als das erlaubte Limit.")
    return encrypted, sha


def _decode(encrypted, key):
    try:
        packed = Fernet(key.encode("ascii")).decrypt(encrypted)
        inflater = zlib.decompressobj()
        plain = inflater.decompress(packed, MAX_RAW + 1)
        if len(plain) > MAX_RAW or not inflater.eof:
            raise BackupError("Entpacktes Backup ist zu groß oder unvollständig.")
        return plain
    except (InvalidToken, zlib.error) as exc:
        raise BackupError("Backup kann nicht entschlüsselt werden. Encryption-Key prüfen.") from exc


def restore_if_missing(path):
    """Nur auf einem tatsächlich fehlenden SQLite-DB-Pfad wiederherstellen."""
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return False
    cfg = config()
    if cfg is None:
        return False
    repo, token, key = cfg
    _repo_info(repo, token)
    encrypted, _ = _remote_file(repo, token)
    if encrypted is None:
        return False
    plain = _decode(encrypted, key)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".cuvenhaus-restore-", suffix=".sqlite3", dir=directory)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(plain)
        with sqlite3.connect(temp_path) as check:
            valid = check.execute("PRAGMA quick_check").fetchone()
            tables = {row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if valid != ("ok",) or not {"monthly_orders", "shift_calendar", "billing_history"}.issubset(tables):
            raise BackupError("Backup enthält keine gültige Cuvenhaus-Datenbank.")
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return True


def save(db_connection):
    """Vollständige SQLite Momentaufnahme verschlüsselt ablegen."""
    cfg = config()
    if cfg is None:
        return False
    repo, token, key = cfg
    # Aus einer konsistenten Snapshot-Verbindung serialisieren, kein WAL-Problem.
    with sqlite3.connect(":memory:") as snapshot:
        db_connection.backup(snapshot)
        data = snapshot.serialize()
    if len(data) > MAX_RAW:
        raise BackupError("Datenbank zu groß für GitHub-Backup.")
    encrypted = Fernet(key.encode("ascii")).encrypt(zlib.compress(data, level=6))
    if len(encrypted) > MAX_BACKUP:
        raise BackupError("Verschlüsseltes Backup größer als 12 MB.")
    _repo_info(repo, token)
    _, sha = _remote_file(repo, token)
    payload = {"message": "Update encrypted Cuvenhaus backup",
               "content": base64.b64encode(encrypted).decode("ascii")}
    if sha:
        payload["sha"] = sha
    result = _request(repo, token, "/contents/" + urllib.parse.quote(BACKUP_PATH, safe="/"),
                      method="PUT", payload=payload)
    if not result:
        raise BackupError("Automatisches Backup konnte nicht gespeichert werden.")
    return True

def show_setup():
    """Bequeme einmalige Einrichtung, ohne Code ausführen zu müssen."""
    import streamlit as st
    try:
        ready = config() is not None
    except BackupError as exc:
        st.warning("Automatisches Backup noch nicht vollständig eingerichtet: " + str(exc))
        ready = False
    if ready:
        st.session_state.pop("_backup_key_setup", None)
        st.caption("🔐 Automatische verschlüsselte Sicherung ist konfiguriert.")
        return
    with st.expander("☁️ Kostenlose automatische Datensicherung einrichten"):
        st.info("Auf Streamlit Community Cloud ist die lokale SQLite-Datei nicht dauerhaft. "
                "Für automatische Wiederherstellung ein **privates GitHub-Repository** "
                "und drei Secrets hinterlegen. Danach sind keine Downloads nötig.")
        st.markdown("1. Unter [GitHub: Neues Repository](https://github.com/new) ein "
                    "**privates** Backup-Repository erstellen.\n"
                    "2. Einen [Fine-grained GitHub-Token]"
                    "(https://github.com/settings/personal-access-tokens/new) "
                    "nur für dieses Repository mit **Contents: Read and write** erstellen.\n"
                    "3. In Streamlit unter **Settings → Secrets** die Werte eintragen.")
        if st.button("🔑 Sicheren Verschlüsselungsschlüssel erzeugen",
                     key="create_backup_secret"):
            st.session_state["_backup_key_setup"] = Fernet.generate_key().decode("ascii")
        if st.session_state.get("_backup_key_setup"):
            st.code("BACKUP_ENCRYPTION_KEY = \"" +
                    st.session_state["_backup_key_setup"] + "\"", language="toml")
            st.caption("Einmal in Streamlit Secrets kopieren und zusätzlich sicher verwahren. "
                       "Dieser Schlüssel darf nicht in GitHub veröffentlicht werden.")
        st.code('GITHUB_BACKUP_REPO = "DEIN_GITHUBNAME/DEIN_PRIVATES_REPO"\n'
                'GITHUB_BACKUP_TOKEN = "DEIN_TOKEN"', language="toml")
        st.caption("Wichtig: Die Sicherung funktioniert erst, wenn alle drei "
                   "Einträge in Streamlit Secrets gespeichert wurden.")

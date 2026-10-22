"""Automatische SQLite-Sicherung ohne zusätzlichen Verschlüsselungsschlüssel.

Die Datenbank wird KOMPRESSIERT, NICHT VERSCHLÜSSELT in einem PRIVATE GitHub
Repository abgelegt. Jeder mit Repository-Zugriff kann die Daten lesen.
Nie in einem öffentlichen Repository speichern.
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

BACKUP_PATH = "cuvenhaus/monthly-state.sqlite3.zlib"
MAX_BACKUP = 12 * 1024 * 1024
MAX_RAW = 65 * 1024 * 1024
MAGIC = b"CUVENHAUS_SQLITE_BACKUP_V1\n"


class BackupError(RuntimeError):
    pass


def config():
    """Zwei Secrets genügen: privates Repository und berechtigter Token."""
    def value(name):
        environment = os.environ.get(name, "")
        try:
            import streamlit as st
            return str(st.secrets.get(name, environment) or "").strip()
        except Exception:
            # Ohne Streamlit-Secrets im lokalen Entwicklungs-/Testbetrieb.
            return environment.strip()

    repo = value("GITHUB_BACKUP_REPO")
    token = value("GITHUB_BACKUP_TOKEN")
    if not repo and not token:
        return None
    if not repo or not token:
        raise BackupError(
            "Für die automatische Sicherung GITHUB_BACKUP_REPO und "
            "GITHUB_BACKUP_TOKEN in Streamlit Secrets setzen."
        )
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise BackupError("Ungültiger Name des GitHub-Backup-Repositories.")
    return repo, token


def _request(repo, token, endpoint, method="GET", payload=None):
    url = "https://api.github.com/repos/" + repo + endpoint
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Cuvenhaus-Manager-Backup",
    }
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and method == "GET":
            return None
        if exc.code in (409, 422):
            raise BackupError(
                "GitHub-Sicherungskonflikt. Die lokale Datenbank bleibt erhalten; "
                "nicht gleichzeitig mit mehreren App-Instanzen sichern."
            ) from exc
        raise BackupError("GitHub-Backup fehlgeschlagen (HTTP %d)." % exc.code) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise BackupError("GitHub für automatische Sicherung nicht erreichbar.") from exc


def _repo_info(repo, token):
    info = _request(repo, token, "")
    if not info:
        raise BackupError("Backup-Repository nicht gefunden oder Token ohne Zugriff.")
    if info.get("private") is not True:
        raise BackupError(
            "Sicherung abgelehnt: Das GitHub-Backup-Repository muss PRIVAT sein."
        )


def _remote_file(repo, token):
    endpoint = "/contents/" + urllib.parse.quote(BACKUP_PATH, safe="/")
    obj = _request(repo, token, endpoint)
    if obj is None:
        return None, None
    sha = obj.get("sha")
    encoded = obj.get("content")
    if not encoded or obj.get("encoding") != "base64":
        if not sha:
            raise BackupError("GitHub-Backup hat keine gültige Dateikennung.")
        blob = _request(repo, token, "/git/blobs/" + urllib.parse.quote(sha, safe=""))
        if not blob or blob.get("encoding") != "base64":
            raise BackupError("GitHub-Backup kann nicht gelesen werden.")
        encoded = blob["content"]
    try:
        packed = base64.b64decode(encoded, validate=False)
    except (ValueError, TypeError) as exc:
        raise BackupError("GitHub-Backup enthält ungültige Dateidaten.") from exc
    if len(packed) > MAX_BACKUP:
        raise BackupError("Backup überschreitet das Größenlimit.")
    return packed, sha


def _encode(sqlite_bytes):
    """Komprimierung und Prüfsumme, ausdrücklich KEINE Verschlüsselung."""
    if len(sqlite_bytes) > MAX_RAW:
        raise BackupError("Datenbank zu groß für GitHub-Backup.")
    result = MAGIC + hashlib.sha256(sqlite_bytes).digest() + zlib.compress(sqlite_bytes, 6)
    if len(result) > MAX_BACKUP:
        raise BackupError("Komprimiertes Backup überschreitet 12 MB.")
    return result


def _decode(packed):
    if not packed.startswith(MAGIC) or len(packed) < len(MAGIC) + 32:
        raise BackupError("Unbekanntes Backupformat. Ein altes Fernet-Backup wird nicht gelesen.")
    digest = packed[len(MAGIC):len(MAGIC) + 32]
    compressed = packed[len(MAGIC) + 32:]
    try:
        decoder = zlib.decompressobj()
        plain = decoder.decompress(compressed, MAX_RAW + 1)
        if len(plain) > MAX_RAW or not decoder.eof or decoder.unused_data:
            raise BackupError("Backup zu groß, beschädigt oder unvollständig.")
    except zlib.error as exc:
        raise BackupError("Backup konnte nicht entpackt werden.") from exc
    if hashlib.sha256(plain).digest() != digest:
        raise BackupError("Backup-Prüfsumme stimmt nicht. Wiederherstellung abgebrochen.")
    return plain


def restore_if_missing(path):
    """Vor dem Öffnen einer fehlenden SQLite-Datei aus GitHub wiederherstellen."""
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return False
    cfg = config()
    if cfg is None:
        return False
    repo, token = cfg
    _repo_info(repo, token)
    packed, _ = _remote_file(repo, token)
    if packed is None:
        return False
    plain = _decode(packed)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        prefix=".cuvenhaus-restore-", suffix=".sqlite3", dir=directory
    )
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(plain)
        with sqlite3.connect(temp_path) as check:
            integrity = check.execute("PRAGMA quick_check").fetchone()
            tables = {
                row[0] for row in check.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        expected = {"monthly_orders", "shift_calendar", "billing_history"}
        if integrity != ("ok",) or not expected.issubset(tables):
            raise BackupError("Backup ist keine gültige Cuvenhaus-SQLite-Datenbank.")
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return True


def save(connection):
    """Konsistenten SQLite-Snapshot automatisch in privates GitHub übertragen."""
    cfg = config()
    if cfg is None:
        return False
    repo, token = cfg
    with sqlite3.connect(":memory:") as snapshot:
        connection.backup(snapshot)
        plain = snapshot.serialize()
    packed = _encode(plain)
    # Vor JEDER Übertragung das private Repository erneut prüfen.
    _repo_info(repo, token)
    _, sha = _remote_file(repo, token)
    payload = {
        "message": "Update Cuvenhaus SQLite backup (private repo only)",
        "content": base64.b64encode(packed).decode("ascii"),
    }
    if sha:
        payload["sha"] = sha
    result = _request(
        repo, token, "/contents/" + urllib.parse.quote(BACKUP_PATH, safe="/"),
        method="PUT", payload=payload
    )
    if not result:
        raise BackupError("Automatisches Backup konnte nicht gespeichert werden.")
    return True


def show_setup():
    """Hinweise für die Einrichtung innerhalb der Passwort-geschützten App."""
    import streamlit as st

    try:
        ready = config() is not None
    except BackupError as exc:
        st.warning(str(exc))
        ready = False

    if ready:
        st.caption("☁️ GitHub-Auto-Backup konfiguriert (privat, komprimiert, nicht verschlüsselt).")
        return

    with st.expander("☁️ Automatische Datensicherung einrichten"):
        st.info(
            "Die SQLite-Datei in Streamlit Community Cloud ist nicht dauerhaft. "
            "Für automatisches Backup ein PRIVATES GitHub-Repository und zwei Secrets einrichten."
        )
        st.warning(
            "Ohne Backup-Schlüssel gibt es keine Verschlüsselung. "
            "Personen mit Zugriff auf das private Backup-Repository können "
            "Kundenadressen, Kennzeichen und andere gespeicherte Daten auslesen."
        )
        st.markdown(
            "1. Ein [privates GitHub-Repository](https://github.com/new) anlegen.\n"
            "2. Einen [Fine-grained GitHub-Token]"
            "(https://github.com/settings/personal-access-tokens/new) "
            "nur für dieses Repository mit **Contents: Read and write** anlegen.\n"
            "3. Unter **Streamlit → Settings → Secrets** nur diese zwei Werte setzen."
        )
        st.code(
            'GITHUB_BACKUP_REPO = "DogeDuck/cuvenhaus-private-backup"\n'
            'GITHUB_BACKUP_TOKEN = "DEIN_NEUER_GITHUB_TOKEN"',
            language="toml",
        )
        st.caption(
            "Kein BACKUP_ENCRYPTION_KEY nötig. Bereits im Chat geteilte Token "
            "müssen widerrufen und ersetzt werden."
        )

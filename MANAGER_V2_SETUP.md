# Cuvenhaus Manager 2.0: kostenlos, lokal und automatisch gesichert

## Was passiert bei einem Monatsimport?
1. Einmal OnStreet-CSV mit den Aufträgen eines Monats in der App hochladen.
2. Aufträge werden in einer **lokalen SQLite-Datenbank** gespeichert, gemeinsam für die gerade laufende Streamlit-Instanz.
3. Gleiche Auftragsnummern werden abgeglichen; neue Versionen aktualisieren die Einträge.
4. Fahrer auswählen und die Bereitschaftsfreitage im einfachen Monatskalender markieren.
5. Provisionslisten prüfen, bei Bedarf Überstunden manuell übernehmen, Abrechnung archivieren.
6. Jede **Änderung an SQLite** löst beim Schließen der Datenbankverbindung ein automatisches, **verschlüsseltes GitHub-Backup** aus. Nach einem Neustart wird die lokale Datenbank aus diesem Backup restauriert, sofern sie fehlt.

**Keine PostgreSQL-Datenbank erforderlich.** Das SQLite-Backup ist nur automatisch und neustartfest, wenn ein privates GitHub-Backup-Repository und alle drei Backup-Secrets eingerichtet sind. Ohne diese Einrichtung arbeitet die App vorübergehend lokal; die Daten können bei Neustart/Neu-Deployment verloren gehen. Beim Backup-Fehler wird ein Fehler angezeigt.

## Einmalige Einrichtung des kostenlosen automatischen Backups

1. Auf GitHub ein **neues privates Repository** anlegen, zum Beispiel `DogeDuck/cuvenhaus-private-backup`. **Nicht das öffentliche App-Repository verwenden**.
2. Unter GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens einen Token erstellen, der **nur dieses private Repository** mit Berechtigung **Contents: Read and write** öffnen darf.
3. Im Streamlit Community Cloud Dashboard → deine App → **Settings → Secrets** diese Werte eintragen:

```toml
INTERNAL_ACCESS_PIN = "DEINE_FIRMENNUMMER"
GITHUB_BACKUP_REPO = "DEIN_GITHUBNAME/DEIN_PRIVATES_BACKUP_REPO"
GITHUB_BACKUP_TOKEN = "DEIN_FEINGRANULARER_GITHUB_TOKEN"
BACKUP_ENCRYPTION_KEY = "FERNET_URLSAFE_BASE64_KEY"
```

Der Encryption-Key ist ein **eigenständiger 32-Byte-Fernet-Schlüssel**, nicht die OnStreet-Nummer und nicht der GitHub-Token. Zum Erstellen (einmalig auf einem vertrauenswürdigen Rechner):

```sh
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**GitHub-Token und Encryption-Key niemals in GitHub-Code oder Chat veröffentlichen.** Den Encryption-Key sicher aufbewahren; bei Verlust kann die Sicherung nicht mehr entschlüsselt werden. Änderungen der Secrets im Streamlit-Dashboard können einen Neustart auslösen.

## Datenschutz, Laufzeit und Löschfristen

- Die App nutzt lokal SQLite, aber für **zuverlässige automatische Wiederherstellung einen externen, kostenlosen GitHub-Backup-Speicher**. Vollständig innerhalb des flüchtigen Community-Cloud-Dateisystems ist das technisch nicht möglich.
- GitHub akzeptiert für die Sicherung **nur ein privates Repository**. Die Datenbank wird **vor dem Upload mit Fernet verschlüsselt**. Die Schlüssel stehen ausschließlich in Streamlit Secrets.
- Die aktiven Auftragsdatensätze werden **90 Tage nach dem letzten Import** beim nächsten Datenbankzugriff gelöscht; ebenfalls werden ältere Summenhistorien und alte Snapshot-Einträge bereinigt.
- **Wichtige Einschränkung:** GitHub ist Versionsverwaltung. Ältere **verschlüsselte** Backup-Versionen können in der Commit-Historie länger als 90 Tage bestehen bleiben. Diese Lösung erfüllt daher **keine garantierte Löschung aller Backup-Versionen nach 90 Tagen**. Für strikte Löschfristen braucht es einen Backupspeicher mit eigener Retention-/Löschregel.
- Gemeinsame fünfstellige Firmen-PIN ist kein vollwertiger Login. Der Zugriff auf echte personenbezogene Auftragsdaten muss betrieblich abgesichert werden; die Streamlit-App sollte nicht öffentlich erreichbar sein.
- Automatische Sicherung erfolgt bei Änderungen an den SQLite-Tabellen (Monatsimporte, Bereitschaftskalender, historisierte Abrechnungen und Versionsstände). Laufende **manuelle Auswahlzustände** im Streamlit-Session-State sind noch nicht Teil des Backups.
- Bei parallelen Nutzern können GitHub-Änderungskonflikte auftreten. Dann wird der Fehler angezeigt; eine bedingungslose Überschreibung der Sicherung wird vermieden.
- GitHub Backupgröße: max. 12 MB verschlüsseltes Komprimat, SQLite unkomprimiert max. 65 MB. Bei Überschreitung erfolgt eine Fehlermeldung.

## Provisionsregeln
- Fr **21:00** bis So **21:00**: Bereitschaft, nicht stornierte Aufträge automatisch vorwählen.
- Unter der Woche: nur **Gutachten, Leihwagen und Reparatur** automatisch übernehmen.
- Überstunden und Ausnahmen lassen sich weiterhin **manuell** per Auftragssuche hinzufügen.
- Ein Auftrag kann nicht doppelt provisioniert werden; deutliche Rückmeldung beim Hinzufügen.
- **Zeitbasis**: Importdaten verwenden bisher den Annahmezeitpunkt, solange kein Abschlusszeitpunkt verfügbar ist.

## Tests
`python -m unittest discover -p "test_*.py" -v` und GitHub Actions prüfen SQLite, Duplikate, Fristen sowie verschlüsseltes Backup/Restore (mit simulierten GitHub-Antworten). Produktiver Streamlit-Test mit anonymisierten CSV-Daten ist vor Merge noch nötig.

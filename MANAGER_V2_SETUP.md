# Cuvenhaus Manager 2.0: Speicherung ohne Backup-Schlüssel

## Automatische Monatsablage

Die App speichert OnStreet-Aufträge lokal in SQLite, erkennt beim Import doppelte Aufträge und aktualisiert Änderungen. Die automatische Auswahl greift ausschließlich innerhalb der Bereitschaft (Freitag 21 Uhr bis Sonntag 21 Uhr). Außerhalb dieses Fensters werden Gutachten, Leihwagen, Werkstatt/Reparatur, Überstunden und zusätzliche Schleppaufträge nur manuell provisioniert. Der Monatskalender und die Auftragsuche bleiben erhalten.

Auftragsdaten und alte Abrechnungen werden nach 90 Tagen beim nächsten Datenbankzugriff bereinigt. Das entfernt aber **keine alten GitHub-Versionen**.

## Kostenlose automatische Sicherung ohne Verschlüsselung

Ein zusätzlicher Verschlüsselungsschlüssel ist **nicht mehr erforderlich**. Die Sicherung wird komprimiert in einem **privaten** GitHub-Repository gespeichert. Diese Komprimierung schützt die Daten **nicht** vor fremden Zugriffen. Personen mit Zugang zum privaten Repo oder GitHub-Token können Kundendaten, Einsatzadressen und Kennzeichen auslesen.

Auf Streamlit Community Cloud ist der lokale Speicher flüchtig. Ohne externes Backup können Monatsaufträge beim Neustart verloren gehen.

## Einmalige Einrichtung

1. Ein **privates** GitHub-Repository anlegen, etwa DogeDuck/cuvenhaus-private-backup.
2. Einen NEUEN GitHub Fine-grained Token erzeugen, mit Zugriff nur auf dieses Repository und **Contents: Read and write**.
3. In Streamlit Community Cloud unter Settings → Secrets diese Einstellungen ergänzen:

    INTERNAL_ACCESS_PIN = "DEINE_INTERNE_FIRMENNUMMER"
    GITHUB_BACKUP_REPO = "DogeDuck/cuvenhaus-private-backup"
    GITHUB_BACKUP_TOKEN = "DEIN_NEUER_TOKEN"

Der frühere, im Chat öffentlich eingegebene GitHub-Token muss auf GitHub **widerrufen** werden. Niemals Token im Chat oder Repository veröffentlichen. Ein eventuell alter BACKUP_ENCRYPTION_KEY-Eintrag wird ignoriert und kann aus Secrets entfernt werden.

Das vorhandene OPENAI_API_KEY-Secret unverändert lassen.

## Technische Eigenschaften

- Kein PostgreSQL, kein Encryption-Key und keine zusätzliche Backup-App.
- Nach SQLite-Änderungen wird der Datenbank-Snapshot automatisch komprimiert und nach GitHub geschrieben.
- Vor JEDEM Upload wird geprüft, ob das Repository wirklich privat ist. Öffentliche Repositories werden abgelehnt.
- Wenn die lokale Datei nach einem Neustart fehlt, stellt die App sie automatisch aus dem Backup wieder her.
- Die Backup-Datei heißt cuvenhaus/monthly-state.sqlite3.zlib.
- Der Wiederherstellungsprozess prüft Dateigröße, Prüfsumme und SQLite-Integrität.
- Maximalgröße: 12 MB komprimiert und 65 MB unkomprimiert.
- Ältere verschlüsselte .fernet-Backups sind mit dieser Version nicht kompatibel.
- Bei einem GitHub-Konflikt oder Netzwerkfehler kann eine Sicherung fehlschlagen; ein Fehler wird angezeigt.
- GitHub bewahrt alte Commit-Versionen auch nach 90 Tagen auf. Eine garantierte Datenlöschung ist damit NICHT umgesetzt.
- Der gemeinsame fünfstellige Firmen-PIN ist kein ausreichender Schutz für sensible Personendaten.
- Manuelle Provisionsauswahlen und Anpassungen im Streamlit-Session-State sind nicht vollständig Teil der DB.

## Inbetriebnahme

Vor Übernahme in main muss ein Test mit anonymisierten OnStreet-Aufträgen und echter automatischer Wiederherstellung auf Streamlit Community Cloud erfolgreich sein. Automatisierte Unit-Tests simulieren die GitHub-Übertragung ohne Kundendaten.

Testbefehl: python -m unittest discover -p "test_*.py" -v

## Sicherheitskopie der bisherigen App

Die vorherige main-Version wurde in GitHub unter dem Branch `backup/main-vor-manager-v2-2026-10-22` unverändert gesichert. Bei Problemen lässt sich der Hauptbranch auf diese Version zurückstellen, ohne die alte Anwendung zu verlieren.

## Prüfung mit OnStreet-Datei (22.10.2026)

Beim lokalen Strukturcheck des vom Anwender bereitgestellten Exports wurden 258 Datensätze mit 258 unterschiedlichen Auftragsnummern erfasst. Der Export enthält Datensätze vom 15.10.2026 bis 22.10.2026, also nicht den vollständigen Monat. Die Datei wurde **nicht** nach GitHub hochgeladen. Die kontinuierlichen GitHub-Tests verwenden nur künstliche CSV-Daten und simulierte GitHub-Backups; ein durchgehender Cloud-Test auf der Nutzerinstanz ist weiterhin notwendig.

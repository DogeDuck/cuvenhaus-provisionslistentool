# Cuvenhaus Manager 2.0 – Einrichtung

## Fahrer statt Mitarbeiter-Logins

Es gibt **keine Anmeldepflicht** und keine Mitarbeiterkonten. Fahrernamen werden wie bisher direkt aus der importierten OnStreet-CSV ermittelt. Über die vorhandene Fahrerauswahl kann jeder die Aufträge und Provisionssummen der Fahrer einsehen.

Die Auswahl **Alle Fahrer** bleibt für die vorhandene Auftragsansicht bestehen. Für die Speicherung von Historie und Bereitschaftskalender wird jeweils ein konkreter Fahrer ausgewählt.

**Datenschutz:** Ohne Login gibt es keine technische Zugriffsbeschränkung. Die App sollte deshalb ausschließlich intern bereitgestellt werden; eine öffentliche Streamlit-Adresse mit echten Auftraggebern, Kennzeichen und Adressen ist nicht empfehlenswert.

## Datenbank

Für dauerhaft gespeicherte Historie und Kalender muss `DATABASE_URL` in Streamlit Secrets auf eine externe PostgreSQL-Datenbank verweisen. Lokale SQLite-Dateien auf Streamlit Community Cloud sind nicht dauerhaft.

```toml
DATABASE_URL = "postgresql://BENUTZER:PASSWORT@HOST:5432/DATENBANK?sslmode=require"
HISTORY_HMAC_SECRET = "LANGER_ZUFAELLIGER_WERT_MIT_MINDESTENS_24_ZEICHEN"
```

Es werden Abrechnungssummen, ausgewählte Fahrer, Bereitschaftsfreitage und HMAC-basierte CSV-Fingerprints gespeichert. Keine vollständigen historischen Auftragslisten.

## Grenzen

- Provisionsprüfung ist nur eine Plausibilitätsprüfung.
- CSV-Diff zeigt Mengenänderungen, keine alten Einzelauftragsdetails.
- Bereitschaftskalender merkt Termine und importiert OnStreet nicht automatisch.
- Handyansicht verbessert die bestehenden Bedienflächen.
- Ohne Zugangskontrolle kann jeder Besucher der App die aktuell geladenen Auftragsdaten sehen.
- Vor Produktivbetrieb die Anwendung mit Beispiel-CSV und PostgreSQL testen.

## Tests

`python -m unittest discover -p "test_*.py" -v`; GitHub Actions führt zudem eine Syntaxprüfung aus.


## Monats-Workflow (neu)

1. Ein Disponent importiert den vollständigen OnStreet-Monatsexport einmal.
2. Mit externer PostgreSQL-Datenbank werden die Aufträge automatisch in einer gemeinsamen Tabelle `monthly_orders` gespeichert.
3. Gleiche Auftragsnummer und unveränderter Inhalt werden als **Duplikat** erkannt; eine neue Version einer vorhandenen Auftragsnummer **aktualisiert** den Datensatz.
4. Bei neuem Laden der App werden die gespeicherten Aufträge wiederhergestellt; Fahrer erscheinen automatisch aus dem Export.
5. Der Bereitschaftskalender zeigt alle Freitage eines ausgewählten Monats als Checkboxen; Fahrer können mehrere Wochenenden auf einmal markieren.
6. Auftragsdatensätze werden **90 Tage nach dem letzten Import** gelöscht, sobald die App wieder auf die Datenbank zugreift. Das ist kein zeitgenau laufender Hintergrund-Job. Abrechnungssummen und bereits bestehende Versionsfingerprints folgen noch keiner automatischen Löschregel.

### Grenzen und Schutzmaßnahmen

- Auftragsinhalte inklusive Kennzeichen, Einsatzadressen und Kundendaten landen in der **externen** Datenbank. Zugriff, Auftragsverarbeitung, Aufbewahrung und Löschfristen müssen vor produktivem Betrieb datenschutzrechtlich geprüft werden.
- Ohne `DATABASE_URL` arbeitet die App wie bisher nur mit dem gerade hochgeladenen CSV; das Monatsarchiv ist **nicht** dauerhaft aktiv.
- Die bestehende CSV-Importlogik verwendet als Zeitbasis die **Annahme**, soweit kein Abschlusszeitpunkt vorhanden ist.
- Die neue Monatsablage ist eine zusätzliche Funktion und sollte vor `main` mit realistischen, anonymisierten CSV-Mustern End-to-End geprüft werden.
- Das Löschen nach 90 Tagen gilt für Einzeldatensätze und wird beim nächsten Zugriff ausgelöst. Datenbank-Backups haben eigene Fristen.
- Eingangsdateien werden nicht dauerhaft als komplette Dateien gespeichert, sondern als normalisierte Auftragsdatensätze.

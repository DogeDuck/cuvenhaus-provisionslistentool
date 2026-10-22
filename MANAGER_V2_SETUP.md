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

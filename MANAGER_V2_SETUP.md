# Cuvenhaus Manager 2.0 – Einrichtung

Der neue Bereich ist in der bestehenden App unter **Cuvenhaus Manager 2.0** erreichbar.

## Sicherheit / Mitarbeiter-Logins
Für die Anmeldung wird Streamlit OIDC (st.login) verwendet. Im Streamlit-Dashboard unter **Settings → Secrets** konfigurieren:

```toml
ALLOWED_EMAILS = "person1@firma.de,person2@firma.de"
HISTORY_HMAC_SECRET = "LANGER_ZUFAELLIG_GENERIERTER_GEHEIMER_WERT"
DATABASE_URL = "postgresql://BENUTZER:PASSWORT@HOST:5432/DATENBANK?sslmode=require"

[auth]
redirect_uri = "https://DEINE-APP.streamlit.app/oauth2callback"
cookie_secret = "WEITERER_LANGER_GEHEIMER_WERT"
client_id = "OIDC_CLIENT_ID"
client_secret = "OIDC_CLIENT_SECRET"
server_metadata_url = "https://OIDC-ANBIETER/.well-known/openid-configuration"
```

Bei OIDC müssen Client-ID, Client-Secret, Redirect URI und Provider-Metadaten vom eigenen Identitätsanbieter stammen. Die oben gezeigten Werte sind **Platzhalter**.

**Wichtig:** Sobald `ALLOWED_EMAILS` gesetzt ist, schützt die App ihre gesamte Oberfläche mit OIDC und lässt nur diese E-Mail-Adressen zu. Vorher bleiben bisherige App-Bereiche offen: keinesfalls sensible Produktionsdateien in einer ungesicherten öffentlichen Instanz verarbeiten.

## Dauerhafte Datenbank
Ohne `DATABASE_URL` verwendet die App SQLite auf dem lokalen Streamlit-Dateisystem, das auf Community Cloud **nicht dauerhaft** ist. Für echte Persistenz muss eine externe PostgreSQL-Datenbank mit TLS eingerichtet werden.

Es werden nur Abrechnungssummen, Bereitschaftsdaten und HMAC-basierte Versionsfingerprints gespeichert, **keine vollständigen Auftragsdaten**. Das ist bewusst eine eingeschränkte Archivfunktion und kein vollständiger wiederherstellbarer Auftragsbestand.

## Funktionsgrenzen
- Provisionsprüfung ist eine regelbasierte Plausibilitätskontrolle, keine verbindliche Prüfung.
- Verdienst-Dashboard verwendet die aktuelle Abrechnung plus gespeicherte Aggregatwerte.
- CSV-Vergleich zeigt neue/entfallene/geänderte Aufträge als **Anzahl**, keine alten Einzelauftragsdetails.
- Bereitschaftskalender speichert markierte Freitage. Er importiert keine OnStreet-Daten automatisch.
- Mobilansicht verbessert Abstände und Bedienelemente, ohne die bestehende Tabellenansicht vollständig zu ersetzen.
- Login schützt den Zugriff, bietet aber noch **keine rollenbasierte Verwaltung** oder fein granularen Mitarbeiter-Datenzugriff. Im normalen App-Teil können erlaubte Personen weiterhin die hochgeladenen Fahrer auswählen.

## Tests
`python -m unittest discover -p "test_*.py" -v` und Syntaxprüfung laufen in GitHub Actions. Vor Produktiveinsatz: mit Test-CSV und OIDC/PostgreSQL-Zugangsdaten End-to-End testen.

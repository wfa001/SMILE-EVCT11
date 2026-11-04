# Paket 5: Gerätefehler und Diagnoseübersicht

Die neue, nur lesbare Entität **Wallbox-Diagnose** (`diagnosis`) trennt drei
Fragen: Ist die Portal-Verbindung nutzbar? Liegt eine aktuelle, auswertbare
Statusrückmeldung vor? Meldet dieser Status eine Wallboxstörung?

## Darstellung

Unter **Einstellungen → Gerät und Diagnose** stehen Portal-Verbindung und
Wallbox-Diagnose als getrennte Kacheln. Die Diagnosekachel öffnet die Details:
Statusquelle, Alter des übernommenen Statusstands, Kommunikationsbewertung,
Fehlerstatus, Rohcode und gegebenenfalls eine kurze Bedeutung. Weitere Erklärung
bleibt eingeklappt. In der Hauptansicht erscheinen nur situationsabhängige,
kurze Hinweise; die vorhandenen Verbindungswarnungen bleiben erhalten.

Die neue Entität bleibt auch bei Verbindungsproblemen sichtbar. Fehlende,
veraltete, unbekannte oder nicht auswertbare Daten erzeugen keine Entwarnung.
`Fault`/`Error` in einer aktuellen, bekannten Statusantwort kennzeichnen eine
gemeldete Störung. Ein Fehlercode allein bei normalem Status wird nicht als
Beweis einer aktiven Störung verwendet. Ebenso bedeutet 0 W keine Störung.

Eine erfolgreiche Live-Antwort ohne Statusangabe wird als **Keine
Statusrückmeldung** dargestellt. Daraus wird kein bestimmter RS485-Defekt
abgeleitet. Ein System-Fallback ohne Status wird nicht mit dieser Live-Meldung
gleichgesetzt. Systemdaten und separater Live-Status bleiben unterscheidbar.

Status-Antworten erhalten einen eigenen Zeitpunkt, unabhängig von der
Einstellungsabfrage. Erfolgreiche Status-Teilantworten bei fehlgeschlagenem
Konfigurationsabruf gelten als eingeschränkte Portal-Verbindung und nicht als
vollständiger Portalausfall. Statusalter und Auswertbarkeit beziehen sich auf
den zuletzt übernommenen Portalstand, nicht auf den Messzeitpunkt der Wallbox;
der bestehende kurze API-Cache bleibt unverändert.

## Fehlernamen und Zuordnungsgrenzen

Für die bekannten Modelle SMILE-EVCT11, SMILE-G3-EVCT11 und SMILE-G3-EVCT11/S
werden ausschließlich eindeutig dokumentierte Hersteller-Fehlernamen kurz
übersetzt, etwa `OverTemp` als Übertemperatur. Weitere Kategorien betreffen
Spannung, Strom, Frequenz, Fehlerstrom und Anschlussfehler. Widersprüchliche
Details zu Verdrahtung oder Reparaturen werden nicht aus den Handbüchern
übernommen.

Das ist eine lexikalische Erklärung, **keine bestätigte numerische API-Tabelle**
und keine Zusage, dass die API diese Namen tatsächlich liefert. Übersetzt wird
nur, wenn sie genau einen bekannten Namen zurückgibt. Dokumentierte
Schreibweisen mit Leerzeichen werden explizit berücksichtigt; unbekannte
Modelle oder Werte erhalten keine erratene Bedeutung.

Numerische Codes einschließlich 0 bleiben unzugeordnet. Insbesondere werden
LED-Blinkzahlen nicht auf `faultCode` übertragen. Rohangaben bleiben lokal
erhalten; die neue Diagnose begrenzt lange Zeichenketten. Die bestehende
Statusentität bleibt für die ursprüngliche Rohangabe verfügbar. Weitere
API-Zuordnungen benötigen eine gegengeprüfte Antwort samt App-Meldung, Modell
und Firmware.

Quellen: [SMILE-EVCT11 V2.0, S. 11–12](https://www.q3-energie.de/download/AlphaESS-Benutzerhandbuch-Wallbox-SMILE-EVCT11-V20.pdf)
und [G3-Handbuch V04, S. 21–22](https://partnershop.alphaess.de/wp-content/uploads/2025/06/Installationshandbuch_DE_SMILE-G3-EVCT11_V04.07082024.pdf).

## Diagnose-Download

Schema 3 ergänzt `health_summary` mit begrenztem Vokabular, Statusalter,
Fehlercode-Format und gegebenenfalls erkanntem Hersteller-Fehlernamen sowie den
Status der letzten Einstellungsübertragung. Unbekannte Rohcodes, freie
Statuswerte, Modelltexte, Kalenderzeitpunkte und Ladewerte werden dadurch nicht
in den normalen Export übernommen. Die bisherigen Felder bleiben erhalten.

Die erweiterte Diagnose bleibt eine einmalige, fünf Minuten gültige Freigabe.
Sie verwendet weiterhin die vorhandene Schwärzung und den Hinweis zur Prüfung
vor dem Teilen. Es gibt keine zusätzlichen Portalabfragen, automatischen
Reparatur-/Resetbefehle oder Änderungen an Ladeeinstellungen.

## Prüfung

- `python3 -m unittest discover -s tests`: 182 Tests erfolgreich.
- Zusätzliche Fälle: erreichbares Portal ohne Gerätestatus, System-Fallback,
  veraltete Störung, 0 W und Wartezustände, bekannte Fehlernamen und Modelle,
  numerische/unbekannte Codes, fehlerhafte Daten, Trennung der Antwortzeiten,
  Diagnoseentität bei Ausfällen, Polling-Stopp während einer Abfrage und normaler
  Export ohne unbekannte Rohwerte.
- Zehn zusätzliche lokale Jinja-Renderfälle für bedingte Diagnosehinweise;
  keine neue Integrations- oder CI-Abhängigkeit.
- Noch offen: reale G1T/G2T-Tests bei Portal-/Gerätekommunikationsfehlern,
  tatsächlichen Fehlerantworten und Desktop-/Mobilansicht sowie Standard- und
  freigegebenem erweitertem Download.

Dieses Paket baut auf Paket 4 (#40) auf. PR-Basis ist
`feature/dashboard-history`, damit der Diff nur Paket 5 enthält. Die Pakete
1–5 bleiben Vorschläge; evcc und externe Ladeautomationen gehören nicht dazu.

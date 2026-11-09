# Paket 3: Datenalter und nachvollziehbare Rückmeldung

Das Dashboard zeigt unter der Verbindung eine kompakte Zeile mit dem Alter der
Live- und Einstellungsabfragen. Die Uhrzeit beschreibt eine Portal-Abfrage, nicht
den Messzeitpunkt der Wallbox. Bei G1T ohne separaten Live-Endpunkt wird nur das
Alter der Einstellungsabfrage angezeigt. Eine fehlgeschlagene Konfigurationsabfrage
wird nicht durch erfolgreiche System-/Live-Antworten als frisch ausgewiesen.

## Einstellungsänderungen

Die bereits vorhandene Rücklesung nach einem akzeptierten PATCH bleibt bestehen.
Neu ist der Vergleich der tatsächlich angeforderten Felder mit einer danach
gestarteten Konfigurationsabfrage:

| Rückmeldung | Bedeutung |
| --- | --- |
| Wird gesendet | Die letzte Einstellungsübertragung läuft. |
| Bestätigung ausstehend | Das Portal hat den PATCH akzeptiert; passende zurückgelesene Werte fehlen noch. |
| Im Portal bestätigt | Alle angeforderten Felder stimmen in einer später gestarteten Konfigurationsabfrage überein. |
| Nicht bestätigt | Nach zwei Minuten fehlt die Bestätigung; das ist keine Ablehnung. Ein späterer passender Abruf kann noch bestätigen. |
| Vom Portal abgelehnt | Der PATCH erhielt eine ablehnende HTTP-4xx-Antwort. |
| Übertragung unklar | Keine verlässliche Annahmebestätigung, beispielsweise bei Zeitüberschreitung, Abbruch oder Serverfehler. |

Die Anzeige bezieht sich ausdrücklich auf die **letzte tatsächlich gestartete
Einstellungsübertragung**, nicht auf alle bisherigen Änderungen und nicht auf
Start/Stopp-Befehle. Eine erfolgreiche Portalbestätigung belegt keine physische
Leistungs- oder Phasenänderung. Bereits vorher oder während des PATCH gestartete
GETs dürfen nicht bestätigen; Antworten älterer Änderungsversuche ebenfalls nicht.
Eine Live-Antwort oder ein System-Fallback bestätigt keine Einstellungen.

Unveränderte Werte ohne PATCH sowie vorab abgewiesene Eingaben erzeugen keinen
neuen Übertragungsstatus. Es gibt keine automatischen Wiederholungen von
Schreibbefehlen und keine zusätzlichen API-Abrufe gegenüber dem bisherigen
Poll-/Readback-Verhalten. Der bestehende Schreib-Lock und das Zusammenfassen
wartender Ladestromänderungen bleiben erhalten.

Die kompakte Bestätigung wird nach fünf Minuten ausgeblendet. Einzelheiten
stehen weiterhin an der Verbindungsentität: betroffene Einstellungsnamen und
Zeitpunkte, ohne Zugangsdaten oder vollständige Anforderungs-/Portal-Dokumente.
Die Daten liegen nur im Arbeitsspeicher und werden nach einem Neustart nicht
als bestätigte Vorgeschichte rekonstruiert. Zeitüberschreitungen in der Anzeige
werden lokal per Template berücksichtigt, auch ohne weitere Portalantwort.

## Fehlende Bedienmöglichkeiten

Start-/Stopp-Entitäten erhalten kurze Gründe aus den vorhandenen Prüfungen,
beispielsweise fehlender Portalstatus, kein angeschlossenes Fahrzeug oder die
Manuell-Voraussetzung bei G2T. Das Dashboard zeigt den Hinweis nur, wenn alle
vorhandenen Start-/Stopp-Tasten nicht verfügbar sind. Der bereits vorhandene
Zeitsteuerungshinweis wird dabei nicht nochmals ausgegeben. Aus einem
Leistungswert von 0 W wird keine Ursache abgeleitet.

## Prüfung

- Standardbibliothek-Tests: `python3 -m unittest discover -s tests`.
- Zusätzliche Szenarien: PATCH-Annahme ohne Bestätigung, No-op, HTTP-Ablehnung,
  Server-/Transportfehler, Abbruch, veraltete und konkurrierende GETs,
  Zeitüberschreitung mit späterer Bestätigung, boolesche Werte, Zeitfenster,
  Teilantworten, Unload und begründete Bedienhinweise.
- Elf zusätzliche lokale Jinja-Renderfälle für Abfragealter, Ablauf der
  Bestätigungsanzeige, fehlende/ungültige Zeitstempel und bedingte Hinweise.
  Keine zusätzliche Jinja-Abhängigkeit für Integration oder CI-Tests.
- Noch offen: Live-Test in Home Assistant mit G1T/G2T, realer Portalverzögerung,
  Verbindungsunterbrechung, schneller Änderung mehrerer Einstellungen sowie
  Desktop-/Mobilansicht und Vorlagenexport.

Dieses Paket baut auf Paket 2 (#38) auf. PR-Basis ist
`feature/dashboard-device-capabilities`; nach dessen Übernahme kann die Basis
auf `main` umgestellt werden.

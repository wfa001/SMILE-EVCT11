# G2T-Kommunikationsverlust: Versuch vom 23.10.2026

## Beobachtung

Modell: SMILE-G3-EVCT11/S, Wallbox-Software 1.6.610, Hardware 1.0.02.
Manueller Versuch durch den Anlagenbetreiber, Auswertung der Antworten im
Webbrowser. Alle Uhrzeiten beziehen sich auf Europe/Berlin.

- 20:46 Uhr: RS485-Kommunikationsstecker getrennt.
- 20:47:20 Uhr: Portal neu geladen; zunächst noch keine Wallbox-Fehlermeldung gemeldet.
- Spätestens gegen 20:54 Uhr: Wallbox zeigt „Keine Kommunikation zwischen der Wallbox und dem Energiespeichersystem“. Der genaue erste Anzeigezeitpunkt wurde nicht erfasst.
- Während der Unterbrechung enthielt `GET /api/internal/v1/ev-charger/{sn}/real-status` weiterhin `gunIsLock`, `chargingAmount` und `lastChargingAmount`, aber weder `status` noch `power`.
- 21:12:20 Uhr: RS485 wieder verbunden. In der nächsten beobachteten Live-Antwort waren `status: NotInsertedGun` und `power: 0.0` wieder vorhanden; die Energiezähler blieben erhalten. Keine zusätzliche genaue Latenzmessung.
- Ein zweiter Versuch zeigte erneut die Kommunikationsmeldung an der Wallbox. Der allgemeine Wechselrichterstatus kehrte nach einer kurzen Störungsanzeige auf Normal zurück.

## Abgleich mit dem Webseiten-Code

Die im Browser geladene Funktion aus `useEvChargerStatus-…js` ruft den
`real-status`-Endpunkt ab. Bei einer vorhandenen Antwort mit fehlendem/leerem
`status` verwendet sie den Übersetzungsschlüssel
`no_com_battery_ess_ev_charger`. Dieselbe Meldung wird dort auch bei fehlenden
Daten nach dem Laden verwendet; diese UI-Regel wird nicht als Beweis für
einen physischen RS485-Defekt bei jedem Netzwerkfehler übernommen.

Die zugehörige Statustabelle aus `account-ahqHus31.js` kennt:
`Charging`, `ChargingStopped`, `Error`, `Fault`, `InsufficientPower`,
`NotInsertedGun`, `PendingStart`, `Upgrading`, `WaitingForChargingPile` und
`Disconnected`. `Error`/`Fault` sind allgemeine Kategorien ohne Detailursache.

## Ungeeignete oder bisher unbestätigte Quellen

- `GET /api/internal/v1/sites/{siteId}/devices` lieferte bei getrennter Verbindung weiterhin `status: Normal` und unter `others` den Wert `chargeState: Unknown`. Kein belastbarer Ersatz für den Live-Status.
- Die Wallbox-Konfiguration (`ess/{sn}?components=evCharger`) blieb abrufbar und enthielt kein ausdrückliches Kommunikationsfehlerfeld.
- Die geprüfte Nachrichtencenter-Antwort enthielt keine Störungsbenachrichtigung. Ein separater Detailfehlercode wurde bei diesem Versuch nicht ermittelt.
- `EVChargerLost` und mögliche Temperatur-Fehlerkennungen wurden nicht durch eine passende Cloud-Antwort bestätigt und werden nicht als neue numerische Fehlerzuordnung implementiert.

## Umsetzung und Grenzen

Erfolgreiche G1T-/G2T-Live-Antworten mit fehlendem, `null` oder leerem Status
erzeugen den Kommunikationshinweis. Der Webseiten-Code prüft dies unabhängig
vom `isG1T`-Parameter. Die Übernahme für G1T beruht auf diesem gemeinsamen
Codepfad; ein G1T-Hardwareversuch steht aus. System-Fallbacks und fehlgeschlagene
HTTP-Aufrufe erzeugen den Hinweis nicht. HTTP 404/409 beim G1T-Live-Endpunkt
behalten den bestehenden Rückfall auf den regulären Abruf. Nicht-Objekt-Antworten
sind Lesefehler mit Backoff.

Eine Zähler-/Verriegelungsantwort darf das Polling nicht dauerhaft deaktivieren.
Die jeweils neue Live-Antwort ersetzt die alte vollständig, damit z. B. eine
alte Ladeleistung nicht stehen bleibt. Nicht gemeldete Werte werden nicht als
0 rekonstruiert. Vorhandene, tatsächlich zurückgelieferte Energiezähler bleiben
sichtbar. Bei Transportfehlern werden keine fehlenden Statusfelder erfunden;
die API-Verbindungsdiagnose meldet den Lese-/Cloud-Fehler getrennt.

Keine zusätzlichen Abrufe, keine Änderungen an Ladestrategien oder
START/STOP-Freigaben. Sensor-Unique-IDs bleiben erhalten. Die Auswertung des
Versuchs ist bestätigt; der Praxistest der geänderten HA-Integration steht aus.

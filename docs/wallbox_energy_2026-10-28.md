# G2T-Energieanzeigen – Beobachtungen vom 28.10.2026

Quelle: vom Betreiber bereitgestellte App-Screenshots, HA-Verläufe
`history(95).csv` und `history(96).csv` sowie seine Beobachtungen.
Alle Zeiten hier in Europe/Berlin; die CSV-Zeitstempel wurden aus UTC umgerechnet.
Keine Zugangsdaten, Seriennummern oder Rohverläufe werden veröffentlicht.

## Zwei Ladesitzungen am selben Tag

| HA-Zeit am 28.10. | chargingAmount / Heute geladen | lastChargingAmount / Sitzung |
| --- | ---: | ---: |
| 13:35 | 3,73 kWh | 3,73 kWh |
| 15:10 | 4,00 kWh | 0,27 kWh |
| 15:15 | 4,29 kWh | 0,56 kWh |
| 15:20 | 4,49 kWh | 0,76 kWh |

Die App zeigte um 15:17 unter „In dieser Sitzung geladen“ 4,29 kWh.
Dieser Wert stimmt mit dem Tageszähler überein, nicht mit der zweiten Sitzung.
3,73 + 0,76 = 4,49 kWh: der Tageszähler summiert im beobachteten G2T-Fall
beide Sitzungen, während der Sitzungszähler nach erneutem Anschließen neu beginnt.
Der Betreiber bestätigte, dass der letzte Sitzungswert nach Abstecken erhalten blieb.
Pausen und ECO-Moduswechsel setzten den Zähler im ersten beobachteten Anschlusszeitraum
nicht zurück. Die Energiezähler aktualisierten sich ungefähr alle fünf Minuten;
ein Screenshot muss daher nicht die seitdem bereits geladene Energie enthalten.

## Fehlendes Feld statt Nullwert

Bereits am 24.10. war nach Mitternacht ohne neue Ladung eine normale
real-status-Antwort ohne beide Energiefelder dokumentiert; die App zeigte 0.
Der Betreiber bestätigt dieses Auslassen bei Nullwerten. Der zusätzliche
Sitzungsverlauf zeigt Übergänge nach unknown am 20.10. 00:00:02,
21.10. 00:00:10, 22.10. 00:00:20, 24.10. 00:00:06,
25.10. 00:00:04 und 27.10. 00:00:04 (auf volle Sekunden gekürzt).
Weitere unknown-Ereignisse liegen außerhalb des Tageswechsels; sie werden
nicht allein wegen ihres Auftretens als Null interpretiert.

CSV-Verläufe sind keine vollständigen API-Rohantworten. Sie zeigen das
Wiederholungsmuster, beweisen aber nicht den Inhalt jeder einzelnen Antwort.
Eine mitten über Mitternacht laufende Ladung wurde hier nicht separat geprüft.
Auf Wunsch des Betreibers wird die gleiche Nullwert-Regel auch für G1T aktiviert. Die Messbelege stammen weiterhin von G2T; der G1T-Tageswechsel ist noch praktisch zu bestätigen.

## Verhalten der Bridge

Beide Energiefelder erhalten bei Abwesenheit denselben Nullwert-Ersatz nur wenn:

- Profil g1T oder g2T, Quelle real_status und Antwort ein Objekt;
- normaler bekannter Status;
- erfolgreiche Coordinator-Aktualisierung und keine erkannten Live-/Vollabfragefehler.

Vorhandene Zahlen werden unverändert übernommen. Explizites null/ungültige Werte,
fehlender oder fehlerhafter Status, System-Fallback und unbekannte Profile erhalten keine neue Null.
Die Bridge führt keine eigene Mitternachtsuhr und speichert keinen Tagesübergreifenden
letzten Sitzungswert. Nach Tageswechsel kann der Sitzungswert deshalb ebenfalls 0 sein.
Nur chargingAmount bleibt TOTAL_INCREASING; Sitzungsenergie erhält keine solche
Statistikklasse. Datenquellen und Unique-IDs bleiben erhalten.

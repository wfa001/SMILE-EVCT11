# Paket 1: Kurze Dashboard-Hilfen

Allgemeine Erklärungen stehen zunächst eingeklappt direkt bei der passenden
Einstellung. Ein Antippen oder Anklicken öffnet sie; zusätzliche Helfer-Entitäten
oder Custom Cards sind nicht erforderlich. Die Umsetzung nutzt `<details>` und
`<summary>` in eingebauten Markdown-Karten.

## Platzierung

| Stelle | Darstellung |
| --- | --- |
| Globale und zeitfensterbezogene Moduswahl | Identische, aufklappbare Kurztexte zu allen vier Modi |
| Kundenspezifischer Ladestrom | Aufklappbare Erklärung zum maximalen Strom je Phase |
| OBC-Phasenwahl | Aufklappbare Erklärung: Fahrzeugauswahl, kein Messwert |
| Smart Mode | Aufklappbare Erklärung zur automatischen Ein-/Dreiphasenumschaltung bei Langsamladung mit OBC-Auswahl 3-phasig |
| Hausstrom-Einstellung | Aufklappbare Abgrenzung zum Ladestrom |
| Zeitfenster | Kurze, zustandsabhängige Anleitung zur Auswahl der Zeitsteuerung; allgemeine Erklärung eingeklappt |
| Verlauf | Interpretation und Voraussetzungen der Statistiken eingeklappt |
| Vorlagenexport | Download direkt erreichbar; Anleitung eingeklappt |

Verbindungswarnungen bleiben im Fehlerfall sichtbar. Der Zeitfenster-Status ist
eine aktuelle Portal-Rückmeldung und bleibt direkt sichtbar. Hilfen an
Bedienelementen folgen deren Verfügbarkeit (`unknown`/`unavailable`). G1T erhält
keine Hinweise zu nicht unterstützten G2T-Bedienelementen.

## Grundlage der Moduserklärungen

- [AlphaESS SMILE-EVCT11 Benutzerhandbuch V2.0, S. 7–10](https://www.q3-energie.de/download/AlphaESS-Benutzerhandbuch-Wallbox-SMILE-EVCT11-V20.pdf)
- [AlphaESS SMILE-G3-EVCT11 Handbuch V04, S. 12–19](https://partnershop.alphaess.de/wp-content/uploads/2025/06/Installationshandbuch_DE_SMILE-G3-EVCT11_V04.07082024.pdf)

Die explizite Ergänzung aus dem Netz wird beim kundenspezifischen Laden erklärt.
ECO-Schnellladung bezeichnet die Priorität des Autos bei PV-/Speichernutzung;
daraus wird keine Garantie für jederzeit exakt null Netzbezug abgeleitet.

## Prüfung

Lokal: `python3 -m unittest discover -s tests` (131 Tests erfolgreich).
Zusätzliche Szenarien prüfen Hilfen an globaler und zeitfensterbezogener Moduswahl,
Verfügbarkeit, G1T-Abgrenzung, bedingte Hinweise und Mehrgeräte-Navigation.

Noch in einer laufenden Home-Assistant-Instanz prüfen:

- Auf- und Zuklappen per Maus, Tastatur und am Handy; Kartenhöhe nach dem Öffnen.
- Wechsel zwischen Manuell, Zeitsteuerung und Plug and Play.
- Ausblenden von Bedienelement und Hilfe bei fehlender Verfügbarkeit.
- Anzeige mit G1T/G2T sowie Export und Import einer eigenen Dashboard-Kopie.

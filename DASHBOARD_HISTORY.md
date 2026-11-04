# Paket 4: Energiekacheln und Ladeverlauf

Die Grunddiagramme waren bereits vorhanden. Dieses Paket verbessert ihre
Darstellung und die Prüfung der lokalen Voraussetzungen, ohne zusätzliche
Cloud-Abfragen, Sensoren, Ladeautomationen oder nachträglich berechnete Zähler.

## Änderungen

- Die gleich hohen Energiekacheln zeigen **Heute geladen** und **Ladesitzung**
  mit unterschiedlichen Symbolen. Ist nur eine vorhanden, nutzt sie die volle
  Breite. Eine kurze, eingeklappte Hilfe erklärt: Der Sitzungswert kann zur
  laufenden oder letzten Sitzung gehören und ist kein dauerhaft archivierter
  letzter Ladevorgang. Sensor-IDs, Messwerte und Zählerlogik bleiben erhalten.
- Die große Leistungskurve steht weiterhin oben im Verlauf und zeigt zwölf
  Stunden über die volle Breite. Die Achse beginnt bei null und darf sich bei
  abweichenden Daten erweitern; Einheiten werden vom Sensor übernommen.
- Darunter stehen Ladeeinstellung, globaler Modus und verfügbare Zeitfenster-Modi
  gemeinsam als Zeitbalken. Sie verschwinden nicht mehr, nur weil aktuell eine
  andere Ladestrategie ausgewählt ist. Der vorhandene, nur lesbare Modussensor
  wird bevorzugt; die Modusauswahl dient als Ersatz, wenn dieser deaktiviert ist.
- Phasenwahl und Smart Mode werden gemeinsam als Einstellungen dargestellt.
  Freigaben der Zeitfenster bleiben als eigene Zeitbalken erhalten. Keiner dieser
  Balken behauptet tatsächlich aktive Phasen oder ausgeführte Ladezeiten.
- Die Höhe der Zeitbalken passt sich dem Inhalt an, statt eine feste Anzahl
  Rasterzeilen zu erzwingen. Die Leistungskurve bleibt groß.

## Tagesenergie

Die Sieben-Tage-Balken verwenden weiterhin ausschließlich den Tageszähler mit
`period: day` und `stat_types: [change]`. Der Sitzungszähler wird nicht für
Tagesstatistiken verwendet.

Geprüft werden nun `device_class: energy`, `state_class: total_increasing`, eine
gültige Energieeinheit, ein aktiver Recorder und dessen Entity-Filter. Fehlt eine
Voraussetzung, erklärt eine eingeklappte Hilfe den konkreten Grund. Ein momentan
nicht verfügbarer Sensor verhindert die Anzeige älterer Statistikwerte nicht,
solange seine Metadaten und Recorder-Zuordnung weiterhin passen.

Das ist eine Prüfung der **Statistikfähigkeit und Aufzeichnung**, keine
Datenbankabfrage auf schon vorhandene Zeilen. Die native Statistik-Karte zeigt
die tatsächlich vorhandenen Daten. Nach neuer Einrichtung muss Recorder erst
Daten sammeln. Es werden weder fehlende Tage mit Null gefüllt noch frühere
Ladevorgänge rekonstruiert. Recorder-Konfiguration und Aufbewahrung bleiben
unverändert. Exportierte Dashboard-Kopien enthalten die beim Export ermittelten
Voraussetzungen; bei späteren Änderungen gegebenenfalls erneut exportieren.

Änderungen an Statistikvoraussetzungen oder Leistungseinheit aktualisieren das
verwaltete Layout über vorhandene Coordinator-Benachrichtigungen. Normale
Zähleränderungen erzeugen keinen vollständigen Dashboard-Neuaufbau.

## Prüfung

- `python3 -m unittest discover -s tests`: 168 Tests erfolgreich.
- Zusätzliche Fälle: Historie bei allen drei Strategien, bevorzugter Modussensor,
  Kachelhöhe/-breite, reine Einstellungshistorie, korrekter Statistikzähler,
  Energieeinheiten, unbekannte aktuelle Werte, Recorder-Ausnahme und spätere
  Änderung der Statistikvoraussetzungen.
- Noch offen: reale Darstellung am PC/Handy, aufgezeichneter Strategiewechsel,
  Tageswechsel mit vorhandenen Statistiken und Prüfung einer exportierten Kopie.

Quellen und geprüfte HA-Schnittstellen:

- [History graph](https://www.home-assistant.io/dashboards/history-graph/)
- [Statistics graph](https://www.home-assistant.io/dashboards/statistics-graph/)
- [Langzeitstatistiken](https://www.home-assistant.io/docs/configuration/long-term-statistics/)
- Recorder-Helfer und Entity-Filter gegen HA Core `2026.10.4` geprüft;
  keine SQL-Abfragen oder Schreibzugriffe auf Recorder.

Dieses Paket baut auf Paket 3 (#39) auf. PR-Basis ist
`feature/dashboard-feedback`, damit der Diff nur Paket 4 enthält.

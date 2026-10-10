# Changelog

## Noch nicht veröffentlicht – minutengenaue G2T-Zeitschreibung

- G2T-Zeitfenster können jetzt minutengenau (HH:MM, 00:00–23:59)
  über die Portal-API geändert werden; keine Rundung auf Viertelstunden.
- Praxisbestätigung vom 10.10.2026: PATCH 08:07–09:23 → HTTP 204;
  gespeicherte Zeiten anschließend in AlphaESS-App und Home Assistant
  korrekt angezeigt (ohne Fahrzeug; Ladeausführung nicht geprüft).
- Time-Entitäten und Validierungstests auf Minuteneingabe umgestellt.
- AlphaESS-Hinweis zu überlappenden Zeitfenstern ergänzt; keine Änderung
  an Prioritäten, Ladeprogrammen oder nativer PV-/Smart-Mode-Regelung.
- Keine Änderung der Integrations-/Release-Version; Maintainer entscheidet.

## Noch nicht veröffentlicht – Testerfeedback

- Anzeige der gewählten Ladeeinstellung und der laut Portal-Modus ausgewählten
  Zeitfenster klargestellt. Gespeicherte Zeiträume bleiben unangetastet.
- Der benutzerdefinierte Ladestrom wird ausdrücklich als Portal-Sollwert
  und nicht als physisch bestätigter Istwert beschrieben.
- Deaktivierte, ausgewählte und lediglich gespeicherte Timer nun
  explizit anhand der Portal-Flags beschrieben; fehlende Aktivierungsflags
  werden als unbekannt ausgewiesen.
- G2T-Zeitfenster: Bereits gespeicherte Minuteneinstellungen aus der
  AlphaESS-App werden ohne Rundung angezeigt. Schreibvorgänge bleiben
  bis zu einem erfolgreichen API-Praxistest auf Viertelstunden begrenzt,
  entsprechend der Weboberfläche.
- Automatisierte Regressionstests für die Hinweise und minutengenaue
  Zeitvalidierung ergänzt.


## 0.5.7

- Ersetzt die Auswahl des Abfrageintervalls durch ein Zahlenfeld (30–300 Sekunden in 30-Sekunden-Schritten); die G1T-/G2T-Standardwerte bleiben 120 beziehungsweise 30 Sekunden.

## 0.5.6

- Behebt einen Fehler im Optionsfluss: Das ungültige Auswahlmodus-Enum `RADIO` wird durch `LIST` ersetzt.

## 0.5.5

- Stellt die Integration in die Standardstruktur `custom_components/alphaess_portal_bridge/` um.
- Ergänzt HACS- und Home-Assistant-Metadaten im Manifest.
- Richtet die Profilbild-Pfade an den kleingeschriebenen Dateinamen aus.

## 0.5.4

- Zeigt beim Portal-Profil-Sensor das passende G1T- oder G2T-Bild.
- Ergänzt englische Übersetzungen für Einrichtungs- und Optionsdialoge sowie den Profil-Sensor.

## 0.5.3

- Setzt das Standardintervall abhängig vom Portal-Profil: G1T 120 Sekunden, G2T 30 Sekunden.
- Zeigt das gespeicherte Intervall im Optionsdialog mit einer Radio-Auswahl zuverlässig an.

## 0.5.2

- Entwicklungsstand 0.5.2 als öffentliche Beta paketiert.
- START/STOP bei G2T auf Ladeeinstellung **Manuell** begrenzt – UI und API-Schutz.
- `WaitingForChargingPile` als **„Warten auf Antwort des E-Autos“** übersetzt.
- Smart-Mode-Schutz für Zeitsteuerung, OBC-Phasenwahl und Lademodus ergänzt.
- OBC-Auswahl 1/2/3 beibehalten; 2-phasig ausdrücklich als Sollwahl dokumentiert.
- `chargingAmount` als **„In dieser Sitzung geladen“** und `lastChargingAmount` als **„Letzter Ladeabschnitt“** getrennt geführt.
- separater Sensor **„Heute laut Ladebericht“**.
- unnötige `null`-Attribute im Status reduziert.
- Installateursteuerung und Kabel-Selbstverriegelung schreibbar.
- öffentliche Beta-Dokumentation und bekannte Einschränkungen ergänzt.

### 0.5.11
- Installateursteuerung und Kabel-Selbstverriegelung als schreibbare Schalter ergänzt und praktisch bestätigt.

### 0.5.9
- G2T-Schutz- und Validierungsfehler vereinheitlicht und auf Deutsch ausgegeben.

### 0.5.8
- Zeitrahmen auf das 15-Minuten-Raster des AlphaESS-Portals begrenzt.

### 0.5.7
- Hardware-Phasen als 1/2/3 dargestellt; nicht unterstützte Power-Share-Diagnosewerte ausgeblendet.

### 0.5.4–0.5.6
- Hausstrom-Einstellung schreibbar gemacht und G2T-Konfiguration weiter vervollständigt.

### 0.5.1–0.5.3
- grundlegende G2T-Erkennung, Status-, Lade-, OBC-, Zeitrahmen- und Energieentitäten aufgebaut.

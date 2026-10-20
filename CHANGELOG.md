# Changelog

## 0.5.92 – Unveröffentlicht

### Wallbox-Steuerung

- Erlaubt STOP im Zustand `WaitingForChargingPile` sowohl über den Stopp-Button als auch über die API. Der Anlagenbetreiber konnte in diesem Zustand über die AlphaESS-App bereits durch Stopp und anschließenden Start die Ladung beginnen.
- Bestehende START-Freigaben, die G2T-Bedingung Ladeeinstellung Manuell und die Live-Statusprüfung bleiben erhalten. Kein automatischer Stopp-/Startablauf ergänzt.
- Die lokale Änderung wurde gespeichert und zurückgelesen; die HA-Konfigurationsprüfung war erfolgreich. Der Funktionstest über die angepasste Bridge steht noch aus.

## 0.5.91 – Beta

### API-Diagnose und Grafiken

- Ergänzt einen Diagnose-Sensor für den Verbindungsstatus zur AlphaESS-Portal-API und verbessert die Fehlerdiagnose für G1T und G2T.
- Über eine Schaltfläche lässt sich vorübergehend eine einmalige erweiterte Diagnoseausgabe bereits zwischengespeicherter API-Daten freigeben. Dafür erfolgen keine zusätzlichen API-Abfragen oder Änderungen an Wallbox-Einstellungen.
- Vertrauliche Daten werden nach bestem Bemühen gefiltert; Diagnoseberichte vor einer Weitergabe prüfen.
- G1T- und G2T-Wallboxbilder sowie das Integrationssymbol durch transparente Grafiken ersetzt.

## 0.5.9 – Beta

### G1T-Zeitfenster

- Die beiden vom Portal gemeldeten G1T-Zeitfenster lassen sich in Home Assistant aktivieren und mit Start- und Endzeit bearbeiten.
- Das Portal liefert für G1T keine Lademodi oder Stromwerte pro Zeitfenster. Dafür werden daher keine Bedienelemente angeboten und beim Speichern keine zusätzlichen API-Felder angelegt.
- Der lokale Praxistest bestätigte, dass eine über Home Assistant geänderte Zeit im AlphaESS-Portal gespeichert wird. Die tatsächliche Ladeausführung nach Zeitplan wurde nicht geprüft.
- Der G2T-Pfad bleibt erhalten.

## 0.5.72b – Beta

### G2T-Zeitfenster mit Minutengenauigkeit

- G2T-Zeitfenster können jetzt minutengenau im Format `HH:MM` (00:00–23:59) über die Portal-API geändert werden. Die Werte werden nicht mehr auf Viertelstunden gerundet.
- Praxistest vom 10.10.2026: PATCH von 08:07 bis 09:23 lieferte HTTP 204. AlphaESS-App und Home Assistant zeigten anschließend die gespeicherten Zeiten korrekt an. Der Test erfolgte ohne Fahrzeug; die tatsächliche Ladeausführung zu diesen Zeiten wurde nicht geprüft.
- Time-Entitäten und Validierung unterstützen die Minuteneingabe.
- Bereits in der AlphaESS-App gespeicherte G2T-Minutenwerte werden in Home Assistant ohne Rundung angezeigt. Die zuvor am 15-Minuten-Raster orientierte Schreibbegrenzung wurde mit dem erfolgreichen API-Test aufgehoben.
- Ein Hinweis zu überlappenden Zeitfenstern wurde ergänzt. Prioritäten, Ladeprogramme und die native PV-/Smart-Mode-Regelung wurden nicht geändert.

### Rückmeldungen und Anzeige

- Die Anzeige der gewählten Ladeeinstellung und der Zeitfenster, die laut Portal-Modus ausgewählt sind, wurde klargestellt. Gespeicherte Zeiträume bleiben dabei unangetastet.
- Der benutzerdefinierte Ladestrom wird ausdrücklich als Portal-Sollwert bezeichnet, nicht als physisch bestätigter Istwert.
- Deaktivierte, ausgewählte und lediglich gespeicherte Timer werden anhand der Portal-Flags unterschieden. Fehlen Aktivierungsflags, wird ihr Status als unbekannt ausgewiesen.

### Schnellere G2T-Livewerte

- Für G2T wird der schreibgeschützte Portal-Endpunkt für Live-Status ungefähr alle 5 Sekunden abgefragt. Der normale Abruf von Konfiguration und Ladebericht bleibt davon getrennt und unverändert.
- Eine gemeinsam genutzte Kurzzeit-Cache verhindert überlappende doppelte Live-Abfragen.
- Bei Fehlern wird die Abfrage verzögert; nach HTTP 429 und Authentifizierungsfehlern beträgt die Wartezeit 120 Sekunden.
- G1T, bestehende Bedienelemente und der native AlphaESS PV Smart Mode bleiben unbeeinflusst.
- Mock-basierte Regressionstests wurden ergänzt. Ein vollständiger Praxistest in Home Assistant sowie die Maintainer-Prüfung stehen noch aus.

### Tests

- Automatisierte Regressionstests für Timer-Hinweise, minutengenaue Zeitvalidierung und Live-Abfrage ergänzt.

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
- Separater Sensor **„Heute laut Ladebericht“**.
- Unnötige `null`-Attribute im Status reduziert.
- Installateursteuerung und Kabel-Selbstverriegelung schreibbar.
- Öffentliche Beta-Dokumentation und bekannte Einschränkungen ergänzt.

### Ältere Entwicklungsstände

#### 0.5.11

- Installateursteuerung und Kabel-Selbstverriegelung als schreibbare Schalter ergänzt und praktisch bestätigt.

#### 0.5.9

- G2T-Schutz- und Validierungsfehler vereinheitlicht und auf Deutsch ausgegeben.

#### 0.5.8

- Zeitrahmen auf das 15-Minuten-Raster des AlphaESS-Portals begrenzt.

#### 0.5.7

- Hardware-Phasen als 1/2/3 dargestellt.
- Nicht unterstützte Power-Share-Diagnosewerte ausgeblendet.

#### 0.5.4–0.5.6

- Hausstrom-Einstellung schreibbar gemacht.
- G2T-Konfiguration weiter vervollständigt.

#### 0.5.1–0.5.3

- Grundlegende G2T-Erkennung sowie Status-, Lade-, OBC-, Zeitrahmen- und Energieentitäten aufgebaut.

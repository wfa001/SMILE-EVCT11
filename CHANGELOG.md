# Changelog

## 0.5.72b – Beta

- G2T-Zeitfenster lassen sich über die Portal-API minutengenau im Format `HH:MM` (00:00–23:59) einstellen und werden auch bei bereits in der AlphaESS-App gespeicherten Minutenwerten ohne Rundung angezeigt. Ein Praxistest bestätigte PATCH 08:07–09:23 mit HTTP 204 sowie die korrekte Anzeige in AlphaESS-App und Home Assistant; das tatsächliche Laden zu diesen Zeiten wurde nicht geprüft.
- Anzeige der gewählten Ladeeinstellung und der anhand des Portal-Modus ausgewählten Zeitfenster präzisiert. Deaktivierte, ausgewählte und nur gespeicherte Timer werden anhand der Portal-Flags unterschieden; fehlen diese Flags, wird der Status als unbekannt ausgewiesen.
- Der benutzerdefinierte Ladestrom wird als Portal-Sollwert bezeichnet, nicht als physisch bestätigter Istwert.
- G2T-Livewerte werden unabhängig vom regulären Konfigurationsabruf etwa alle 5 Sekunden schreibgeschützt aktualisiert. Die Abfrage lädt weder erneut die Konfiguration noch den Ladebericht; ein kurzer gemeinsamer Cache vermeidet doppelte Anfragen. Bei Fehlern greift eine Wartezeit, bei Authentifizierungsfehlern und HTTP 429 bis zu 120 Sekunden. G1T-Abfrage, Bedienelemente und AlphaESS Smart Mode bleiben davon unberührt.
- Hinweise zu überlappenden G2T-Zeitfenstern sowie automatisierte Regressionstests für Zeitvalidierung, Timer-Rückmeldungen und Live-Abfrage ergänzt.

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

- **0.5.11:** Installateursteuerung und Kabel-Selbstverriegelung als schreibbare Schalter ergänzt und praktisch bestätigt.
- **0.5.9:** G2T-Schutz- und Validierungsfehler vereinheitlicht und auf Deutsch ausgegeben.
- **0.5.8:** Zeitrahmen auf das 15-Minuten-Raster des AlphaESS-Portals begrenzt.
- **0.5.7:** Hardware-Phasen als 1/2/3 dargestellt; nicht unterstützte Power-Share-Diagnosewerte ausgeblendet.
- **0.5.4–0.5.6:** Hausstrom-Einstellung schreibbar gemacht und G2T-Konfiguration weiter vervollständigt.
- **0.5.1–0.5.3:** Grundlegende G2T-Erkennung, Status-, Lade-, OBC-, Zeitrahmen- und Energieentitäten aufgebaut.

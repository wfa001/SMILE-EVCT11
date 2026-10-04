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

# Changelog

## 0.5.2 – Community Build

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

## Entwicklungsstände vor der öffentlichen Beta

### 0.5.11
- Installateursteuerung und Kabel-Selbstverriegelung als schreibbare Schalter ergänzt und praktisch bestätigt.

### 0.5.10
- Storion4you-/Kavino-Kennzeichnung und `NOTICE.md` ergänzt.

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

# AlphaESS Wallbox Bridge

> **Beta 0.5.7**  
> Entwickelt u.a. für die Community von **https://www.storion4you.de/**  
> G2T-Erweiterung für **AlphaESS SMILE-G3-EVCT11/S**: **Kavino**  

Diese Home-Assistant-Custom-Integration bindet AlphaESS-Wallboxen über das AlphaESS-Kundenportal an Home Assistant an. 
G1T-Unterstützung und ergänzend eine neuere G2T-Konfiguration der SMILE-G3-EVCT11/S (Kavino).

Dies ist ein Community-Projekt und keine offizielle AlphaESS-Integration. Die G2T-Funktionen und die G1T-Hardwarekompatibilität wurden praktisch getestet; einzelne Sonderfälle benötigen weitere Rückmeldungen.

## Unterstützter Stand

### G2T

- automatische Erkennung des Portal-Profils `g2T`
- Live-Status und Ladeleistung
- Fahrzeug angeschlossen und Ladestecker verriegelt als Ja/Nein
- Ladeeinstellung: **Manuell / Zeitgesteuertes Aufladen / Plug and Play**
- Lademodus: **Langsamladung / Schonladung / Schnellladung / Kundenspezifische Ladeleistung**
- kundenspezifischer Ladestrom **6–16 A**
- OBC-Phasenwahl **1 / 2 / 3**
- Smart Mode mit Schutzprüfungen
- drei Zeitrahmen mit Aktivierung, Start, Ende, Lademodus und Maximalstrom
- Zeitwerte im vom Portal verwendeten **15-Minuten-Raster**
- Hausstrom-Einstellung **25–1000 A**
- Installateursteuerung und Kabel-Selbstverriegelung
- Hardware-, Software-, Modell- und Profildiagnose
- Energie- und Ladeberichtswerte

Der Diagnose-Sensor **Portal-Profil** zeigt das erkannte Profil und das dazugehörige Bild `g1t.png` oder `g2t.png`.

### G1T

Die bestehende G1T-Erkennung und -Konfiguration bleibt erhalten. Die G2T-spezifischen Schutzregeln greifen nicht in den G1T-Pfad ein.

## G2T-Schutzlogik

### Laden starten und stoppen

**Laden starten** und **Laden stoppen** sind bei G2T ausschließlich mit der Ladeeinstellung **Manuell** verfügbar. Das wurde mit angeschlossenem Fahrzeug unter Last bestätigt. Bei **Zeitgesteuertem Aufladen** und **Plug and Play** deaktiviert die Integration die Schaltflächen und blockiert direkte Start-/Stopp-Aufrufe zusätzlich in der API-Schicht.

Die Beta sendet absichtlich **keinen automatischen zweiten STOP-Befehl**. In einem Test musste STOP einmal erneut gesendet werden; die Ursache ist noch nicht reproduzierbar geklärt.

### Smart Mode

Smart Mode wird nur für G2T angeboten. Beim Aktivieren prüft die Integration:

- Zeitgesteuertes Aufladen darf nicht aktiv sein.
- Die OBC-Phasenwahl muss auf **3-phasig** stehen.
- Der Lademodus muss **Langsamladung, Schonladung oder Schnellladung** sein.

Ein Wechsel auf Zeitgesteuertes Aufladen bei aktivem Smart Mode wird blockiert. Vor einem manuellen Wechsel auf 1- oder 2-phasig muss Smart Mode deaktiviert werden.

## Bekannte Einschränkungen und offene Prüfungen

1. **Smart-Mode-Phasenautomatik:** Smart Mode wurde erfolgreich aktiviert. Die automatische 1↔3-Phasenumschaltung bei geeignetem PV-Überschuss ist noch nicht abschließend live bestätigt.
2. **OBC „2-phasig“:** AlphaESS-App und Portal speichern den Wert. Bei einem Test mit einem Peugeot e-208 wurde trotz der Auswahl „2-phasig“ extern auf allen drei Phasen Leistung gemessen. Die Entität zeigt deshalb eine **Sollwahl**, nicht die tatsächlich stromführenden Phasen.
3. **`chargingAmount`:** Wird wie in der AlphaESS-App als **„In dieser Sitzung geladen“** angezeigt. Der Wert blieb im Test nach erneutem Anstecken erhalten; seine genaue Definition und sein Reset-Zeitpunkt sind offen.
4. **`lastChargingAmount`:** Wird als **„Letzter Ladeabschnitt“** angezeigt. Der Wert kann zeitweise `null` sein und erhält keinen künstlichen Fallback.
5. **„Heute laut Ladebericht“:** Summe abgeschlossener Berichtseinträge des aktuellen Tages. Der Wert war in einem Test während einer Live-Ladung noch 0,00 kWh und ist daher vorerst als experimentell zu betrachten.

Besonders erwünscht sind Tests mit weiteren G2T-Fahrzeugmodellen und Firmwareständen, eine G1T-Regressionsprüfung, die Smart-Mode-Phasenautomatik, zweiphasig ladenden Fahrzeugen sowie das Resetverhalten von `chargingAmount` und die Plausibilität des Tagesberichts.

Bei unerwartetem Verhalten zuerst die AlphaESS-App oder das Portal prüfen. Die Wallbox nicht durch schnelle wiederholte Schreibbefehle belasten.

## Polling

- Wallbox- und Konfigurationsdaten: Eingabefeld **30–300 Sekunden** in **30-Sekunden-Schritten**
- Standard: **G1T 120 Sekunden**, **G2T 30 Sekunden**
- Energiebericht: gecacht und höchstens etwa alle **5 Minuten** neu abgefragt

Kurze Übergangszustände der Wallbox können zwischen zwei Abfragen liegen und in Home Assistant unsichtbar bleiben.

## Installation über HACS

1. HACS öffnen und **Integrationen → ⋮ → Benutzerdefinierte Repositories** wählen.
2. `https://github.com/wfa001/SMILE-EVCT11` als Repository mit Typ **Integration** hinzufügen.
3. Die **AlphaESS Wallbox Bridge** installieren und Home Assistant neu starten.
4. Eine bereits eingerichtete Integration nicht löschen. Zugangsdaten und Wallbox-Seriennummer bleiben im vorhandenen Config Entry erhalten.
5. Auf der Geräteseite unter Diagnose prüfen, welches Portal-Profil (`g1T` oder `g2T`) erkannt wurde.

## Manuelle Installation

1. Den bestehenden Ordner `config/custom_components/alphaess_portal_bridge` sichern.
2. Den Ordner `custom_components/alphaess_portal_bridge` aus diesem Repository nach `config/custom_components/` kopieren und vorhandene Dateien ersetzen.
3. Home Assistant vollständig neu starten.
4. Eine bereits eingerichtete Integration nicht löschen. Zugangsdaten und Wallbox-Seriennummer bleiben im vorhandenen Config Entry erhalten.

Bei einer Neuinstallation die Integration über **Einstellungen → Geräte & Dienste → Integration hinzufügen** einrichten.

## G2T-Portal-Zuordnungen

| Portal-Feld | Bedeutung |
|---|---|
| `chargeStrategy` | `0` Manuell, `1` Zeitgesteuert, `2` Plug and Play |
| `chargeMode` | `1` Langsam, `2` Schon, `3` Schnell, `4` Kundenspezifisch |
| `chargeCurrent` | kundenspezifischer Ladestrom, 6–16 A |
| `obcPhase` | OBC-Sollwahl 1 / 2 / 3 |
| `smartMode` | Smart Mode |
| `timePeriods` | bis zu drei Zeitrahmen |
| `houseHoldCurrent` | Hausstrom-Einstellung |
| `allowInstallersControl` | Installateursteuerung erlaubt |
| `gunLineSelfLockEnable` | Kabel-Selbstverriegelung |

## Projekt-Herkunft und Attribution

Die Unterstützung der **AlphaESS SMILE-G3-EVCT11/S (G2T)** wurde durch **Kavino** aus der Storion4you-Community initiiert, anhand realer Portal- und Wallbox-Daten ermittelt und praktisch getestet. Dazu gehören insbesondere die G2T-Zuordnungen und die Home-Assistant-Unterstützung für Ladestrategie, Lademodus, Ladestrom, OBC-Phasenwahl, Smart Mode, Zeitfenster, Live-Status und Energiebericht.

## Beta-Feedback

Für einen Fehlerbericht helfen besonders:

- Home-Assistant-Version
- Wallbox-Modell sowie Hardware- und Software-Version
- erkanntes Portal-Profil `g1T` oder `g2T`
- Fahrzeugmodell, wenn der Fehler während einer Ladung auftritt
- Ausgangseinstellung und ausgeführte Aktion
- Status und Leistung vor und nach der Aktion
- relevante Home-Assistant-Logs

Zugangsdaten, Tokens und persönliche Daten aus Logs entfernen. Seriennummern für öffentliche Beiträge ebenfalls schwärzen.

Änderungen früherer Entwicklungsstände stehen im `CHANGELOG.md`.

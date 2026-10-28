# AlphaESS Wallbox Bridge

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="custom_components/alphaess_portal_bridge/brand/dark_logo@2x.png">
  <img src="custom_components/alphaess_portal_bridge/brand/logo@2x.png" alt="Wallbox Bridge for AlphaESS" width="640">
</picture>

> **Beta 0.5.9**  
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
- **Zeitfenster:** Minutengenaue `HH:MM`-Werte können über die
  Portal-API gelesen und geschrieben werden, obwohl die AlphaESS-Weboberfläche
  nur ein 15-Minuten-Raster anbietet. Bestätigt durch einen G2T-Praxistest
  vom 10.10.2026 mit 08:07–09:23 (PATCH HTTP 204, Werte in App und
  Home Assistant zurückgelesen). Die tatsächliche zeitgesteuerte
  Ladeausführung mit angeschlossenem Fahrzeug wurde dabei nicht geprüft
- Hausstrom-Einstellung **25–1000 A**
- Installateursteuerung und Kabel-Selbstverriegelung
- Hardware-, Software-, Modell- und Profildiagnose
- Energie- und Ladeberichtswerte

Der Diagnose-Sensor **Portal-Profil** zeigt das erkannte Profil und das dazugehörige Bild `g1t.png` oder `g2t.png`.

### G1T

- Zwei vom Portal gemeldete Zeitfenster mit Aktivierung, Beginn und Ende können in Home Assistant gelesen und bearbeitet werden. Der lokale G1T-Test vom 15.10.2026 bestätigte, dass eine über Home Assistant geänderte Zeit im Portal ankommt. Das bestätigt die Speicherung, nicht die tatsächliche Ladeausführung.
- Die G1T-Antwort enthält keine globale Ladeeinstellung und keine Lademodi oder Stromwerte pro Zeitfenster. Diese Bedienelemente bleiben deshalb unavailable; die Integration ergänzt keine nicht gemeldeten API-Felder.
- Die G2T-spezifischen Schutzregeln greifen nicht in den G1T-Pfad ein.

## Hinweise aus dem Testerfeedback

- **Unterschied Webportal / App:** Die App erlaubt minutengenaue
  Eingaben, die Weboberfläche zeigt nur Viertelstunden-Schritte.
  Der tatsächliche PATCH-Endpunkt akzeptierte am 10.10.2026
  08:07–09:23 (HTTP 204); beide Werte wurden in der App und in
  Home Assistant korrekt zurückgelesen. Die Integration akzeptiert
  deshalb jetzt Minutenwerte von 00 bis 59; Sekunden bleiben unzulässig.
  Der Test bestätigt das Speichern, nicht die physische Ausführung.
- **Überlappende Zeitfenster:** AlphaESS beschreibt das Verhalten so:
  „Wenn die Lademodi zur gleichen Zeit kollidieren, führt das System
  den aktuellen Lademodus weiter aus.“ Die Integration legt keine
  zusätzliche Prioritätsregel fest. Verhalten beim Ende eines
  überlappenden Zeitfensters ist für G2T nicht praktisch bestätigt.
- **Zeitfenster und Plug and Play:** Der im Portal gespeicherte Zeitplan
  bleibt beim Wechsel zwischen Manuell, Zeitgesteuertem Aufladen und Plug and
  Play erhalten. Die Entitäten unterscheiden jetzt zwischen
  **deaktiviertem Zeitfenster**, **im Zeitplan aktiviertem Zeitfenster** und
  **gespeichert, aber nicht ausgewählt**. Die gespeicherten Uhrzeiten bleiben
  auch bei `isEnable: false` sichtbar. Die tatsächliche Wirksamkeit muss
  weiterhin an der Wallbox geprüft werden. Die Integration schaltet beim
  Wechsel zu Plug and Play **keine** Zeitrahmen ungefragt aus.
- **API-Sollwert und tatsächlicher Ladestrom:** Die Entität
  `Ladestrom (kundenspezifisch)` meldet den im Portal gespeicherten Sollwert,
  keine physisch bestätigte Umsetzung. Die Ladereaktion kann verzögert sein;
  für den tatsächlichen Betrieb die Live-Leistung und ggf. ein externes
  Messgerät beobachten.
- **Änderungen aus App/Portal:** Sie werden durch die normalen
  Integrationsabfragen erkannt. Die zusätzliche 3-Sekunden-Rücklesung nach
  einem **von Home Assistant gesendeten** Schreibbefehl gilt nicht für
  Änderungen, die ausschließlich aus der AlphaESS-App kommen.

### Häufige Fragen zum Testerfeedback

**Woran erkenne ich deaktivierte Zeitfenster?** Die Entität
`Zeitrahmen N Aktiv` zeigt den gespeicherten Portal-Schalter `isEnable`.
Das Statusattribut **Zeitfenster-Status** unterscheidet ausdrücklich zwischen
deaktiviert, im Zeitplan aktiviert und lediglich gespeichert. Wenn die
Portal-Antwort keinen verlässlichen Aktivierungswert enthält, steht dort
`Unbekannt`. Alte Uhrzeiten allein beweisen keine aktive Zeitsteuerung.

**Warum werden Änderungen aus der App nicht sofort in Home Assistant sichtbar?**
Änderungen direkt in der App werden durch das normale Polling eingelesen
(G2T standardmäßig 30 s; in den Optionen einstellbar). Cloud-Verzögerungen
sind zusätzlich möglich. Die 3-Sekunden-Rücklesung wird nur bei einem
**Home-Assistant-Schreibbefehl** ausgelöst und bestätigt keinen physisch
abgeschlossenen Ladevorgang.

**Was geschieht bei Cloud- oder Internetausfall?** Diese Integration verwendet
die AlphaESS-Portal-API, keinen lokalen Steuerkanal. Sie kann bei Ausfall
der Cloud **nicht** verlässlich von Manuell zu Plug and Play wechseln und
keine lokale Abschaltsicherheit oder SoC-Abschaltung garantieren. Eine
Stromunterbrechung ist kein dokumentierter Reset auf Plug and Play.
Für sicherheitskritische Ladebedingungen ist eine unabhängige, entsprechend
geprüfte Lösung erforderlich.

**Wie installiere ich Updates?** Über HACS das benutzerdefinierte Repository
hinzufügen und veröffentlichte Releases aktualisieren; nach einem Update
Home Assistant neu starten. Bei manueller Installation nur den
Integrationsordner `custom_components/alphaess_portal_bridge/` kopieren,
nicht das gesamte Git-Repository. Das aktuell ausgewählte Release kann
von neuesten Änderungen auf `main` abweichen.

**Installateursteuerung und Kabelverriegelung:** Die verfügbaren
Konfigurationsfelder werden aus dem Portal übernommen. Der genaue Umfang
der Installateursteuerung ist nicht vollständig dokumentiert.
`gunLineSelfLockEnable` bezeichnet die Selbstverriegelungs-Einstellung
**an der Wallbox**; eine automatische Verriegelung im Fahrzeug ist damit
nicht bestätigt.

## Aufbau der Home-Assistant-Geräteseite

Häufige Ladebedienung erscheint unter **Steuerung**: Start/Stopp, Ladeeinstellung,
Lademodus, kundenspezifischer Ladestrom, OBC-Phasenwahl und Smart Mode.
Die Mess- und Statuswerte bleiben unter **Sensoren**. Zeitfenster,
automatische Kabelverriegelung, Hausstrom-Einstellung und Installateurfreigabe
bleiben unter **Konfiguration**; technische Informationen und API-Diagnose
unter **Diagnose**.

Innerhalb dieser HA-Bereiche bleibt die alphabetische Reihenfolge bestehen.
Es werden keine Nummern an Namen angehängt und keine eigenen Unterbereiche
angelegt. Die vorhandenen Zeitfensternamen halten die Felder pro Zeitfenster
zusammen. G1T bietet weiterhin nur die unterstützten Felder der zwei Zeitfenster.

Die Geräteinformationen verwenden das vom Portal gemeldete Modell sowie,
falls vorhanden, Software- und Hardwareversion. Bei G2T wird dadurch die alte
feste Modellbezeichnung SMILE-EVCT11 durch z. B. SMILE-G3-EVCT11/S ersetzt;
ein tatsächlich so gemeldetes G1T-Modell bleibt korrekt erhalten. Ohne
Modellangabe wird neutral „AlphaESS Wallbox“ verwendet.
Nach Installation der Änderung die Integration neu laden oder HA neu starten,
damit vorhandene Registry-Einträge aktualisiert werden. Eigene Anzeigenamen,
Gerätekennung, Entity-Unique-IDs und bestehende Automationen bleiben erhalten.

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
3. **`chargingAmount`:** **„Heute geladen“** summiert bei der getesteten G2T mehrere Ladesitzungen am selben Tag. Die App beschriftete diesen Tageswert im Test irreführend mit „In dieser Sitzung geladen“.
4. **`lastChargingAmount`:** **„Aktuelle / letzte Ladesitzung“** zählt bei der getesteten G2T die aktuelle Sitzung und bleibt nach dem Abstecken zunächst erhalten. Beim erneuten Anstecken beginnt der Wert erneut; auch nach Tageswechsel kann das Portal das Feld weglassen. Der Wert ist kein dauerhaftes Archiv der letzten Ladung. Fehlende Felder erhalten nur unter den unten beschriebenen Bedingungen 0; explizites `null` bleibt unbekannt.
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

## Passwortwechsel und abgelehnte Anmeldung

Wird eine Anmeldung abgelehnt, stoppt die Bridge weitere automatische Anmeldeversuche und fordert über Home Assistant eine erneute Authentifizierung an. Diese Pause bleibt auch beim Neuladen und nach einem Neustart erhalten. Ein Login mit HTTP 409 oder 429 wird vorsichtshalber ebenfalls pausiert; Status 409 allein beweist keine Kontosperre.

Eine von AlphaESS angezeigte Sperrfrist zunächst abwarten. Danach unter **Einstellungen → Geräte & Dienste** beim betroffenen Integrationseintrag die erneute Authentifizierung öffnen und die aktuellen Zugangsdaten absenden. Das Öffnen des Formulars sendet kein Passwort. Nur das Absenden startet einen neuen Versuch. Nach erfolgreicher Prüfung wird derselbe Integrationseintrag aktualisiert; Geräte, Entitäten und Zuordnungen bleiben erhalten. Die Integration muss dafür nicht gelöscht werden.

Normale Verbindungsfehler bleiben wiederholbar. HTTP 409 an anderen Endpunkten, etwa dem G1T-Live-Status, wird weiterhin getrennt behandelt. Bereits laufende HTTP-Anfragen können beim Auftreten des Fehlers noch abschließen.

## Wallbox-Kommunikation und Fehleranzeigen

Der bestehende **Status**-Sensor zeigt für G1T und G2T **„Keine Kommunikation zwischen Wallbox und Energiespeichersystem“**, wenn die Cloud eine `real-status`-Antwort als Objekt liefert, in der `status` fehlt, `null` oder leer ist. Diese Anzeige entspricht der gemeinsamen G1T-/G2T-Logik des AlphaESS-Webportals. Praktisch wurde sie beim Trennen/Wiederverbinden der RS485-Verbindung an G2T beobachtet; der entsprechende G1T-Praxistest steht aus. Sie beschreibt die fehlende Statusmeldung, keine Diagnose der konkreten elektrischen Ursache.

Die Cloud kann dabei weiterhin Energiezähler und den Verriegelungswert liefern. Das bestätigt keine aktive Kommunikation zur Wallbox. Fehlende Leistungswerte werden als unbekannt behandelt. Die Live-Abfrage läuft weiter und zeigt wieder den normalen Status, sobald dieser zurückkommt.

Der Diagnose-Sensor **Wallbox Bridge Verbindung** beurteilt separat den Zugriff auf die Cloud-API. Ein HTTP-/Netzwerkfehler erzeugt keine neue RS485-Störungsmeldung; bei fehlgeschlagenen Live-Abfragen können die letzten erfolgreich empfangenen Werte bis zur nächsten Aktualisierung stehen bleiben. Schlägt auch die reguläre Coordinator-Aktualisierung fehl, greift die bestehende Nichtverfügbarkeit der Entitäten.

| API-Status | Anzeige |
|---|---|
| `Disconnected` | Verbindung getrennt |
| `Error` | Allgemeiner Fehler |
| `Fault` | Störung |
| `Upgrading` | Softwareaktualisierung läuft |

Diese allgemeinen Statuswerte enthalten keine genaue Fehlerursache. Insbesondere wird `Disconnected` nicht pauschal mit einem RS485-Ausfall gleichgesetzt. Detaillierte Fehler wie Übertemperatur sind ohne passende API-Antwort weiterhin nicht zugeordnet. System-Fallbackdaten und fehlgeschlagene HTTP-Aufrufe lösen die neue Kommunikationsmeldung nicht aus. Meldet der G1T-Live-Endpunkt HTTP 404/409, bleibt der bisherige Rückfall auf den regulären Abruf erhalten.

Versuch und Quellen: [RS485-Kommunikationstest vom 23.10.2026](docs/wallbox_communication_2026-10-23.md).

### Energieanzeigen und fehlende Nullwerte

Bei G2T wurde beobachtet: Nach Mitternacht ohne neue Ladung zeigt das Portal
0 kWh; die erfolgreiche `real-status`-Antwort enthält einen normalen Status,
aber kein `chargingAmount`. Auch `lastChargingAmount` wird bei einem Nullwert
weggelassen, beispielsweise nach Tageswechsel oder zu Beginn einer neuen Sitzung.
Bei einer erfolgreichen G1T-/G2T-Live-Antwort mit normalem Status zeigt die Bridge
für das jeweils fehlende Energiefeld ebenfalls 0 kWh. Vorhandene Zahlenwerte
werden unabhängig voneinander übernommen und nach Abstecken nicht pauschal gelöscht.
Bei fehlendem Status, Fehlerzuständen, erkannten Abfragefehlern, System-Fallbacks,
explizitem `null` oder ungültigen Werten wird keine 0 ergänzt. Für G1T fehlt
noch ein entsprechender Praxistest des Tageswechsels; die gleiche Nullwert-Regel ist auf Wunsch auch dort aktiviert. Es gibt keine lokale Rücksetzung um Mitternacht.
Die bisherigen Geräte-/Entitäts-Unique-IDs bleiben erhalten.

Beim G2T-Test vom 28.10.2026 ergaben die erste Sitzung mit 3,73 kWh und die
zweite mit 0,76 kWh zusammen 4,49 kWh Tagesenergie. Zwischenzeitlich zeigte
die App 4,29 kWh, passend zu 3,73 + 0,56 kWh, während der Sitzungssensor
0,56 kWh lieferte. Die Energieanzeigen wurden ungefähr alle fünf Minuten aktualisiert.
Details: [G2T-Energieauswertung vom 28.10.2026](docs/wallbox_energy_2026-10-28.md).

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


### Faster G2T live values (development branch)

G2T wallboxes refresh the read-only portal `real-status` endpoint approximately every **5 seconds**, independently of the normal system/configuration refresh (30 seconds by default). This updates charging power, status, plug/lock state and the live energy fields without repeatedly loading settings and report history. A 3-second shared response cache also avoids duplicate status requests close to normal refreshes. G1T polling stays unchanged.

The five-second interval is based on short read-only portal tests; it is **not** an official AlphaESS rate-limit guarantee. On connection errors the live reader backs off; HTTP 429 on live-status reads uses a longer 120-second pause. Authentication failures stop polling and require explicit reauthentication, including after a restart. HTTP 409/429 during login is also paused rather than automatically retried. No charge-control, schedules or Smart Mode logic was changed. AlphaESS has been observed to refresh cloud power values about every ten seconds, so five-second polling primarily lowers Home Assistant's additional detection delay.

# Automatisches Dashboard – Entwicklungsentwurf

Nach einem Update auf diesen Zweig und dem Neustart von Home Assistant legt die
Bridge automatisch den Seitenleisteneintrag **Wallbox Bridge** mit `mdi:ev-station`
an. Es ist kein YAML-Import und keine manuelle Entitätszuordnung erforderlich.
Der Entwurf ist noch kein veröffentlichtes Release.

## Bedienung

- **Wallbox:** Zeigertacho oben links, kompakte Tages-/Sitzungsenergie,
  Gerätestatus, Verbindungswarnungen, Zeitfensterübersicht und Bedienung.
- **Verlauf:** zwölf Stunden Leistung, Moduseinstellungen, Gerätestatus,
  Bridge-Verbindung, Zeitfenster-Freigaben und G2T-Phasensollwahl;
  zusätzlich Tagesenergie für sieben Tage, wenn der Energiesensor
  `state_class: total_increasing` meldet. Recorder-Aufzeichnung ist erforderlich;
  alte Daten werden nicht nachträglich erzeugt. Es werden keine Nullwerte ergänzt.
- **Zeitfenster:** G1T zeigt die zwei bestätigten Fenster und seinen globalen
  Lademodus; G2T bis zu drei Fenster mit den verfügbaren Modi/Stromwerten.
  Nicht vom Portal bestätigte Felder werden nicht hergestellt.
- **Einstellungen:** Geräteinformationen und Bridge-Diagnose sowie Download
  der persönlichen Dashboard-Vorlage.

Es gibt ausschließlich eingebaute HA-Karten. Shelly, Wakeup, zusätzliche HACS-
Karten und private Automationen sind keine Voraussetzung. OBC-Phasen sind eine
Sollwahl; Zeitfenster-Freigaben sind Konfiguration, kein Nachweis einer Ladung.
G2T-Start/Stopp erscheint nur unter **Manuell**; G1T folgt der Verfügbarkeit der
Bridge-Tasten. Eine Taste im Zustand `unknown` kann noch nie gedrückt worden sein
und wird deshalb nicht pauschal versteckt.

Bei mehreren geladenen Bridge-Einträgen öffnet sich eine gemeinsame
Wallboxauswahl. Jede Wallbox hat eigene Ansichten und ausschließlich ihre eigenen
Entitätsreferenzen. Die bestehende Bridge verwaltet ein Gerät je Konfiguration;
der Entwurf erweitert nicht die Erkennung mehrerer Ladegeräte am selben ESS.

## Automatisches Dashboard abschalten

Unter **Einstellungen → Geräte & Dienste → AlphaESS Wallbox Bridge → Optionen**
lässt sich **Wallbox-Bridge-Dashboard anzeigen** pro Integrationseintrag
abschalten und wieder einschalten. Nach dem Speichern lädt Home Assistant den
Eintrag neu. Der Seitenleisteneintrag verschwindet, wenn das Dashboard für alle
Wallboxen abgeschaltet ist. Die Entitäten können weiter in eigenen Dashboards
und Automationen verwendet werden.

## Eigenes Dashboard

1. Unter **Einstellungen → Eigenes Dashboard** die Vorlage herunterladen.
2. Ein eigenes leeres Dashboard erstellen und dessen Raw-Konfiguration öffnen.
3. Den vollständigen Dateiinhalt einfügen, speichern und anschließend bearbeiten.

Der Export enthält die aktuellen Entitätsnamen genau dieser Wallbox. Er enthält
keine Zugangsdaten, Tokens, Rohantworten oder zeitlich begrenzten Downloadlinks.
Der authentifizierte Downloadlink läuft nach zehn Minuten ab; für einen neuen
Link die Dashboard-Seite neu laden. Die eigene Kopie gehört dem Benutzer und
wird nie von der Bridge überschrieben. Nach späterer Umbenennung einer Entität
muss eine eigene Kopie angepasst oder erneut exportiert werden.

Das verwaltete Dashboard bleibt schreibgeschützt und erhält Änderungen durch
Bridge-Updates. Vorhandene Benutzer-Dashboards, die bisherige manuelle Test-YAML,
Sidebar-Voreinstellungen und Default-Dashboard-Einstellungen bleiben erhalten.
Ist der URL-Pfad bereits belegt, wählt die Bridge einen freien Suffix. Beim
Entladen des letzten Bridge-Eintrags entfernt sie nur ihr eigenes Panel.

## Technischer Stand und Prüfung

- Entitätsauflösung über Plattform, stabile `unique_id` **und** Config-Entry-ID.
  Benutzerdefinierte Namen und deaktivierte Registry-Einträge werden berücksichtigt.
- Konfiguration wird beim Laden neu generiert. Registry-Änderungen lösen eine
  Aktualisierung aus; Layout-Capability-Änderungen werden vom Coordinator verfolgt.
  Normale Live-Leistungsänderungen lösen keinen kompletten Dashboard-Neuaufbau aus.
- Kein Schreiben in fremde Lovelace-Dateien oder `.storage` und keine zusätzlichen
  Cloud-Abfragen oder Ladebefehle durch Dashboardaufbau/Export.
- Die Lovelace-Registrierung verwendet derzeit interne HA-Schnittstellen. Diese
  kleine Kompatibilitätsschicht ist in `dashboard.py` gekapselt. Schnittstellen
  gegen HA-Core 2026.10.4 geprüft; reale HA- und G1T-Laufzeittests stehen noch aus.
  Dashboardfehler werden protokolliert und sollen den Bridge-Betrieb nicht stoppen.
- Bestehende Integrationstests plus Tests für umbenannte/fremde/deaktivierte
  Entitäten, G1T/G2T-Fähigkeiten, Mehrgeräte-Navigation, kW-Anzeige,
  Sidebar-Kollisionen, Unload und einen bereinigten Export.

Vor Veröffentlichung in HA testen: Update/Neustart ohne vorhandenes Dashboard,
Umbenennung/Deaktivierung, Export und Import der Kopie, normaler Benutzer,
G1T-Hardware, zwei Bridge-Einträge sowie Entladen/erneutes Laden. Noch kein
Versionssprung, Merge oder Release durch diesen Entwurf.

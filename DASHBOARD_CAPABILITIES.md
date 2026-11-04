# Paket 2: Dashboard nach bestätigten Gerätefähigkeiten

Die Anzeige folgt dem Portalprofil und gültigen, tatsächlich gelieferten Feldern.
Ein Modellname allein schaltet keine Funktion frei. G1T/G2T bezeichnen hier
Portal-Datenstrukturen, nicht automatisch eine Hardwaregeneration.

## Verhalten

- G1T: genau zwei vollständig bestätigte Zeitfenster; keine aus ähnlich benannten
  Feldern abgeleitete Phasenwahl oder Smart-Mode-Steuerung. Eine globale
  Ladeeinstellung erscheint nur bei bekanntem Wert und bestätigtem Zeitschema.
- G2T: maximal drei Zeitfenster. Die vorhandene API benötigt mindestens drei
  Einträge für Zeitfenster-Schreibzugriffe; kürzere Listen werden daher nicht
  als bedienbare Zeitfenster dargestellt. Ein beschädigter Eintrag blendet nur
  dieses Fenster aus, gültige Nachbarfenster bleiben sichtbar.
- Optionale Modi und Stromwerte je Zeitfenster erscheinen nur bei gültigen
  zurückgelieferten Feldern. Die Prüfung ergänzt niemals fehlende Portalwerte.
- Phasenwahl benötigt eine gültige Phasenangabe, Smart Mode einen booleschen
  Zustand. Kabel-Selbstverriegelung benötigt zusätzlich die ausdrückliche
  Unterstützungsangabe. `false` ist ein gültiger Zustand, kein fehlendes Feld.
- Unbekannte Profile behalten Messwerte und Diagnose, erhalten aber keine
  Lade-Bedienelemente. Bei fehlenden oder ungültigen Einstellungsfeldern werden
  die zugehörigen Bedienelemente ausgeblendet.
- Der globale G1T-Lademodus bleibt auch bei ausgewählter Zeitsteuerung erreichbar.
  Wenn keine zeitfensterbezogenen Modi vorliegen, erscheint er zusätzlich im
  Zeitfenster-Tab als Modus für beide Fenster. G2T behält die bisherige Trennung.

## Smart Mode

Ein kurzer Hinweis erscheint bei nicht passenden oder nicht prüfbaren
Voraussetzungen. Er folgt den aktuellen Entitätszuständen auch in exportierten
Dashboard-Kopien. Sind die Voraussetzungen erfüllt, bleibt die Hinweiskarte leer
und wird durch `show_empty: false` verborgen. Es werden keine zusätzlichen
Helfer-Entitäten angelegt.

Das G3-Handbuch V04 beschreibt den automatischen Phasenwechsel für Langsamladung
mit dreiphasiger OBC-Auswahl. Die bisherige API-Prüfung erlaubt dagegen alle drei
ECO-Modi. Deshalb wird dieser Unterschied erläutert, ohne neue Schreibsperren
einzuführen. Die vorhandenen API-Prüfungen bleiben bestehen; insbesondere muss
Smart Mode auch bei widersprüchlichen gespeicherten Einstellungen ausschaltbar
bleiben. Es gibt keine automatischen Änderungen an Modus oder Phasenwahl.

Quelle: [AlphaESS G3-Handbuch, gedruckte Seite 19](https://partnershop.alphaess.de/wp-content/uploads/2025/06/Installationshandbuch_DE_SMILE-G3-EVCT11_V04.07082024.pdf).

## Prüfung

- `python3 -m unittest discover -s tests`: 141 Tests erfolgreich auf dem Stand
  dieses Pakets, einschließlich Regressionen für abgeschnittene/fehlerhafte
  Zeitfenster, ungültige Typen, unbekannte Profile, G1T-Modusauswahl und
  Aktualisierung bei geänderten Fähigkeiten.
- Zusätzlich 12 lokale Jinja-Renderfälle für Smart-Mode-Hinweise geprüft:
  passende Voraussetzungen, Zeitsteuerung, Ein-/Zweiphasigkeit, kundenspezifischer
  Modus, Schnellladung sowie fehlende Zustände. Jinja wird nicht als zusätzliche
  Abhängigkeit der Integration oder ihrer Standardbibliothek-Tests eingeführt.
- Noch offen: Sichtprüfung in einer laufenden Home-Assistant-Instanz mit G1T
  und G2T, wechselnden Einstellungen, Verfügbarkeit sowie Vorlagenexport/-import.

Dieses Paket baut auf Paket 1 (#37) auf. Die PR-Basis ist dessen Branch
`feature/dashboard-contextual-help`, damit der neue Diff nur die zusätzlichen
Geräteanpassungen enthält. Nach Übernahme von #37 kann die Basis auf `main`
umgestellt werden.

"""Generate native Lovelace cards from resolved entity IDs, never entity names.

This module deliberately has no HA imports so capability/layout behavior can be
verified independently of a running Home Assistant instance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from html import escape
from typing import Any


@dataclass
class WallboxDashboard:
    """Only presentation inputs; no credentials or raw API payloads."""

    entry_id: str
    title: str
    profile: str | None
    entities: dict[str, str]
    settings: dict[str, Any] = field(default_factory=dict)
    power_unit: str = "W"
    energy_statistics: bool = False
    export_url: str | None = None
    diagnostics_path: str | None = None


def _heading(text: str, icon: str = "mdi:ev-station") -> dict:
    return {"type": "heading", "heading": text, "icon": icon,
            "heading_style": "title"}


def _note(text: str) -> dict:
    return {"type": "markdown", "content": text,
            "grid_options": {"columns": "full", "rows": "auto"}}


def _help(title: str, text: str) -> dict:
    """Native, initially collapsed help; no helper entities or custom cards."""
    return {**_note(f"<details>\n<summary>{escape(title)}</summary>\n\n{text}\n\n</details>"),
            "text_only": True}


def _mode_help() -> dict:
    """Use the same concise explanation at global and per-period selectors."""
    return _help("Lademodi erklärt",
        "- **Langsamladung:** PV-Überschuss nach Haus und Speicher. "
        "Der Speicher liefert keinen Strom fürs Auto.\n"
        "- **Schonladung / Standardleistung:** PV und Speicher versorgen das Auto. "
        "Der Hausverbrauch hat Vorrang.\n"
        "- **Schnellladung:** PV und Speicher versorgen das Auto mit Vorrang "
        "vor Hausverbrauch und Speicherladung.\n"
        "- **Kundenspezifische Ladeleistung:** Lädt mit dem eingestellten Strom "
        "je Phase. Fehlende Leistung wird aus dem Netz ergänzt.")


def _current_help() -> dict:
    return _help("Ladestrom erklärt",
        "Maximaler Strom je Phase beim kundenspezifischen Laden. "
        "Das Fahrzeug kann weniger aufnehmen.")


def _tile(entity: str, name: str, *, icon: str | None = None,
          feature: str | None = None, columns: int = 12) -> dict:
    card = {"type": "tile", "entity": entity, "name": name,
            "tap_action": {"action": "more-info"},
            "grid_options": {"columns": columns, "rows": "auto"}}
    if icon:
        card["icon"] = icon
    if feature:
        card["features_position"] = "bottom"
        card["features"] = [{"type": feature}]
        if feature == "numeric-input":
            card["features"][0]["style"] = "buttons"
    return card


def _condition(card: dict, entity: str, value: str, *, invert: bool = False) -> dict:
    return {"type": "conditional", "conditions": [
        {"condition": "state", "entity": entity,
         "state_not" if invert else "state": value}], "card": card,
        "grid_options": card.get("grid_options", {"columns": 12, "rows": "auto"})}


def _available(card: dict, entity: str) -> dict:
    return _condition(_condition(card, entity, "unknown", invert=True),
                      entity, "unavailable", invert=True)


def _smart_mode_hint(entities: dict[str, str]) -> dict:
    """Re-evaluate prerequisites from live HA states without layout rebuilds.

Keep the switch accessible for disabling a stored Smart Mode. The API accepts
all three ECO modes; only Slow's automatic phase switch is documented, so this
hint must not invent a new write restriction for Standard or Fast.
"""
    keys = ("smart_mode", "charge_strategy_select", "obc_phase_select", "charge_mode_select")
    expressions = [f"states({json.dumps(entities[key])})" if entities.get(key) else "'unknown'"
                   for key in keys]
    template = "{% set smart, strategy, phase, mode = " + ", ".join(expressions) + " %}\n"
    template += (
        "{%- if smart in ['on', 'off'] -%}"
        "{%- if strategy == 'Zeitgesteuertes Aufladen' -%}"
        "Smart Mode ist bei Zeitsteuerung nicht verfügbar."
        "{%- elif phase in ['1-phasig', '2-phasig'] -%}"
        "Für Smart Mode die OBC-Phasenwahl auf **3-phasig** stellen."
        "{%- elif mode == 'Kundenspezifische Ladeleistung' -%}"
        "Für automatische Phasenumschaltung **Langsamladung** auswählen."
        "{%- elif smart == 'on' and mode in ['Schonladung / Standardleistung', 'Schnellladung'] -%}"
        "Automatische Phasenumschaltung ist nur für **Langsamladung** dokumentiert."
        "{%- elif smart == 'on' and (strategy not in ['Manuell', 'Plug and Play'] "
        "or phase != '3-phasig' or mode != 'Langsamladung') -%}"
        "Smart-Mode-Voraussetzungen derzeit nicht vollständig prüfbar."
        "{%- endif -%}{%- endif -%}")
    return {**_note(template), "show_empty": False,
            "entity_id": [entities[key] for key in keys if entities.get(key)]}


def _graph(title: str, entities: list[tuple[str | None, str]], rows: int = 3) -> dict | None:
    resolved = [{"entity": e, "name": n} for e, n in entities if e]
    if not resolved:
        return None
    return {"type": "history-graph", "title": title, "hours_to_show": 12,
            "entities": resolved, "grid_options": {"columns": "full", "rows": rows}}


def _portal_feedback(entity: str) -> dict:
    api = json.dumps(entity)
    template = (
        "{%- macro age(value) -%}"
        "{%- set stamp = as_timestamp(value, default=none) -%}"
        "{%- if stamp is none -%}noch keine"
        "{%- else -%}{%- set seconds = [0, (as_timestamp(now()) - stamp)|int]|max -%}"
        "vor {{ seconds if seconds < 60 else seconds // 60 if seconds < 3600 else seconds // 3600 }} "
        "{{ 's' if seconds < 60 else 'min' if seconds < 3600 else 'h' }}"
        "{%- endif -%}{%- endmacro -%}\n"
        f"{{%- set live = state_attr({api}, 'Letzte erfolgreiche Live-Abfrage') -%}}"
        f"{{%- set config = state_attr({api}, 'Letzte erfolgreiche Konfigurationsabfrage') -%}}"
        f"{{%- if state_attr({api}, 'Live-Endpunkt unterstützt') is sameas false -%}}"
        "Einstellungen: {{ age(config) }}"
        "{%- else -%}Live-Abfrage: {{ age(live) }} · Einstellungen: {{ age(config) }}{%- endif -%}"
        f"{{%- set result = state_attr({api}, 'Einstellungsübertragung') -%}}"
        f"{{%- set sent = as_timestamp(state_attr({api}, 'Übertragung angenommen am'), default=none) -%}}"
        f"{{%- set confirmed = as_timestamp(state_attr({api}, 'Im Portal bestätigt am'), default=none) -%}}"
        "{%- if result == 'Bestätigung ausstehend' and sent is not none and as_timestamp(now()) - sent >= 120 -%}"
        "{%- set result = 'Nicht bestätigt' -%}{%- endif -%}"
        "{%- if result == 'Im Portal bestätigt' and confirmed is not none and as_timestamp(now()) - confirmed >= 300 -%}"
        "{%- set result = none -%}{%- endif -%}"
        "{%- if result and result != 'Keine Übertragung erfasst' %}\n\n"
        "Letzte Einstellungsübertragung: **{{ result }}**."
        "{%- endif -%}")
    return {**_note(template), 'text_only': True, 'entity_id': [entity]}


def _unavailable_controls(entities: dict[str, str], profile: str | None) -> dict | None:
    buttons = [entities[key] for key in ('start', 'stop') if entities.get(key)]
    if profile not in {'g1T', 'g2T'} or not buttons:
        return None
    blocked = ' and '.join(f'is_state({json.dumps(e)}, "unavailable")' for e in buttons)
    reason = ' or '.join(f'state_attr({json.dumps(e)}, "Bedienhinweis")' for e in buttons)
    # Package 1 already explains this case next to the strategy selector.
    strategy = entities.get('charge_strategy_select')
    if profile == 'g2T' and strategy:
        blocked += f' and not is_state({json.dumps(strategy)}, "Zeitgesteuertes Aufladen")'
    template = '{% if ' + blocked + ' %}{{ ' + reason + " or '' }}{% endif %}"
    return {**_note(template), 'show_empty': False,
            'entity_id': buttons + ([strategy] if strategy else [])}


def _section(cards: list, *, wide: bool = False) -> dict:
    section = {"type": "grid", "cards": [card for card in cards if card]}
    if wide:
        section["column_span"] = 2
    return section


def build_wallbox_views(box: WallboxDashboard, *, prefix: str = "",
                        url_path: str = "alphaess-wallbox-bridge",
                        subview: bool = False, export: bool = False) -> list[dict]:
    """Build the same four views for the selected wallbox and its capabilities."""
    e = box.entities
    g2 = box.profile == "g2T"
    g1 = box.profile == "g1T"
    periods = box.settings.get("timePeriods")
    periods = periods if isinstance(periods, list) else []
    count = min(len(periods), 3 if g2 else 2 if g1 else 0)
    # Backend only supplies entities for a schema verified by schedule_supported.
    indices = [i for i in range(1, count + 1)
               if e.get(f"time_period_{i}_start") and e.get(f"time_period_{i}_end")]
    paths = {key: f"{prefix}{key}" for key in ("wallbox", "verlauf", "zeitfenster", "einstellungen")}
    views = []
    for key, title, icon in (("wallbox", "Wallbox", "mdi:ev-station"),
                             ("verlauf", "Verlauf", "mdi:chart-line"),
                             ("zeitfenster", "Zeitfenster", "mdi:calendar-clock"),
                             ("einstellungen", "Einstellungen", "mdi:cog")):
        view = {"title": title, "path": paths[key], "icon": icon,
                "type": "sections", "max_columns": 2, "sections": []}
        if subview:
            view["subview"] = True
            view["back_path"] = f"/{url_path}/wallboxen"
            links = " · ".join(f"[{label}](/{url_path}/{paths[target]})" for target, label in
                                 (("wallbox", "Wallbox"), ("verlauf", "Verlauf"),
                                  ("zeitfenster", "Zeitfenster"), ("einstellungen", "Einstellungen")))
            view["sections"].append(_section([_note(f"**{box.title}**\n\n{links}")], wide=True))
        views.append(view)
    status, history, schedule, settings = views
    left = [_heading(box.title)]
    if power := e.get("power"):
        left.append({"type": "gauge", "entity": power, "name": "Aktuelle Ladeleistung",
                     "min": 0, "max": 11 if box.power_unit == "kW" else 11000,
                     "needle": True, "tap_action": {"action": "more-info"},
                     "grid_options": {"columns": 12, "rows": 3}})
    if api := e.get("api_connection"):
        left.append(_condition(_note("> ⚠️ **Bridge-Verbindung prüfen**\n> Aktuelle Messwerte und Steuerbefehle können eingeschränkt sein."), api, "Verbunden", invert=True))
    if entity := e.get("status"):
        left += [_condition(_note("> ⚠️ **Keine Kommunikation zwischen Wallbox und Energiespeichersystem**"), entity,
                            "Keine Kommunikation zwischen Wallbox und Energiespeichersystem"),
                 _tile(entity, "Status", icon="mdi:ev-station")]
    for key, name in (("today_energy", "Heute geladen"), ("last_energy", "Letzte Ladung")):
        if entity := e.get(key):
            card = _tile(entity, name, columns=6)
            card["grid_options"]["rows"] = 1
            left.append(card)
    rows = [{"entity": e[key], "name": name, "icon": icon} for key, name, icon in (
        ("vehicle_connected", "Fahrzeug angeschlossen", "mdi:car-electric"),
        ("gun_locked", "Ladestecker verriegelt", "mdi:lock"),
        ("api_connection", "Wallbox Bridge Verbindung", "mdi:cloud-check")) if key in e]
    if rows:
        left.append({"type": "entities", "show_header_toggle": False, "entities": rows})
    if api:
        left.append(_portal_feedback(api))
    if indices:
        # One template string per row, no missing entity placeholders or invented values.
        lines = ["**Gespeicherte Zeitfenster**", "", "| Fenster | Freigabe | Zeit | Lademodus |",
                 "| :-- | :-- | :-- | :-- |"]
        for i in indices:
            enabled = e.get(f"time_period_{i}_enabled")
            flag = ("{{ 'Ein' if is_state('" + enabled + "', 'on') else 'Aus' if is_state('" + enabled + "', 'off') else 'Keine Daten' }}") if enabled else "Keine Daten"
            def time_value(key: str) -> str:
                entity_id = e[key]
                return "{{ states('" + entity_id + "')[:5] if states('" + entity_id + "') not in ['unknown','unavailable'] else '–' }}"
            period_mode = e.get(f"time_period_{i}_mode")
            mode_text = ("{{ states('" + period_mode + "') if states('" + period_mode + "') not in ['unknown','unavailable'] else 'Keine Daten' }}") if period_mode else "Globaler Modus"
            lines.append(f"| {i} | {flag} | {time_value(f'time_period_{i}_start')}–{time_value(f'time_period_{i}_end')} | {mode_text} |")
        lines += ["", f"[Zeitfenster bearbeiten](/{url_path}/{paths['zeitfenster']})"]
        left.append(_note("\n".join(lines)))
    right = [_heading("Laden bedienen", "mdi:car-electric")]
    strategy = e.get("charge_strategy_select")
    if strategy:
        right.append(_available(_tile(strategy, "Ladeeinstellung", feature="select-options"), strategy))
        if g2:
            right.append(_condition(_note(
                f"Lademodi unter [Zeitfenster](/{url_path}/{paths['zeitfenster']}) einstellen. "
                "Start/Stopp ist nur bei **Manuell** verfügbar."), strategy, "Zeitgesteuertes Aufladen"))
    if mode := e.get("charge_mode_select"):
        right.append(_available(_tile(mode, "Lademodus", feature="select-options"), mode))
        right.append(_available(_mode_help(), mode))
    if current := e.get("custom_charge_current"):
        right.append(_available(_tile(current, "Ladestrom (kundenspezifisch)", feature="numeric-input"), current))
        right.append(_available(_current_help(), current))
    if g2:
        for key, name, feature in (("obc_phase_select", "OBC Phasenwahl", "select-options"),
                                   ("smart_mode", "Smart Mode", "toggle")):
            if entity := e.get(key):
                right.append(_available(_tile(entity, name, feature=feature), entity))
                if key == "obc_phase_select":
                    right.append(_available(_help("Phasenwahl erklärt",
                        "Passend zum Ladegerät deines Fahrzeugs auswählen. "
                        "Die Auswahl zeigt keine tatsächlich gemessenen Phasen."), entity))
                elif key == "smart_mode":
                    right.append(_smart_mode_hint(e))
                    right.append(_available(_help("Smart Mode erklärt",
                        "Wechselt bei Langsamladung automatisch zwischen einer und drei Phasen. "
                        "Erfordert die OBC-Auswahl **3-phasig**."), entity))
    for key, name, icon in (("start", "Laden starten", "mdi:play"), ("stop", "Laden stoppen", "mdi:stop")):
        if entity := e.get(key):
            button = {"type": "button", "entity": entity, "name": name, "icon": icon,
                      "show_state": False, "tap_action": {"action": "perform-action",
                      "perform_action": "button.press", "target": {"entity_id": entity}},
                      "grid_options": {"columns": 6, "rows": 2}}
            # A valid button can be 'unknown' until its first press. Do not hide it for that.
            button = _condition(button, entity, "unavailable", invert=True)
            if g2:
                if not strategy:
                    continue
                button = _condition(button, strategy, "Manuell")
            right.append(button)
    if hint := _unavailable_controls(e, box.profile):
        right.append(hint)
    if (g1 and any(e.get(key) for key in ("charge_mode_select", "start", "stop"))
            and not any(e.get(f"time_period_{i}_mode") for i in indices)):
        right.append(_help("Ladesteuerung erklärt",
            "Der Lademodus gilt für beide Zeitfenster. Start/Stopp erscheint, "
            "wenn die Bridge die Aktion für den gemeldeten Status freigibt."))
    status["sections"] += [_section(left), _section(right)]

    graphs = [_heading("Ladeverlauf", "mdi:chart-line"),
              _graph("Ladeleistung · letzte 12 Stunden", [(e.get("power"), "Ladeleistung")], 6)]
    modes = _graph("Zeitfenster-Lademodi · letzte 12 Stunden", [
        (e.get(f"time_period_{i}_mode"), f"Zeitfenster {i}") for i in indices], 4)
    global_mode = _graph("Globaler Lademodus · letzte 12 Stunden", [(e.get("charge_mode_select"), "Lademodus")])
    if modes and strategy:
        graphs.append(_condition(modes, strategy, "Zeitgesteuertes Aufladen"))
        if global_mode:
            graphs.append(_condition(global_mode, strategy, "Zeitgesteuertes Aufladen", invert=True))
    elif global_mode:
        graphs.append(global_mode)
    graphs.append(_graph("Ladestatus und Bridge-Verbindung · letzte 12 Stunden", [
        (e.get("status"), "Ladestatus"), (api, "Bridge-Verbindung")]))
    if g2:
        graphs.append(_graph("OBC-Phasenwahl (Sollwert) · letzte 12 Stunden", [(e.get("obc_phase_select"), "Phasenwahl")]))
    graphs.append(_graph("Zeitfenster-Freigaben · letzte 12 Stunden", [
        (e.get(f"time_period_{i}_enabled"), f"Zeitfenster {i}") for i in indices], 4))
    if box.energy_statistics and (today := e.get("today_energy")):
        graphs.append({"type": "statistics-graph", "title": "Ladeenergie je Tag · letzte 7 Tage",
                       "entities": [{"entity": today, "name": "Geladene Energie"}],
                       "days_to_show": 7, "period": "day", "chart_type": "bar",
                       "stat_types": ["change"], "min_y_axis": 0,
                       "grid_options": {"columns": "full", "rows": 5}})
    else:
        graphs.append(_help("Warum fehlen die Tagesbalken?",
            "Es ist noch kein aktivierter Energiesensor mit geeigneter Summenstatistik verfügbar."))
    graphs.append(_help("Verlauf richtig lesen",
        "Modi und Phasenwahl zeigen Einstellungen. Zeitfenster-Freigaben zeigen Ein/Aus, "
        "keine tatsächlichen Ladezeiten. Tagesbalken nutzen gespeicherte Statistiken; "
        "fehlende Vergangenheit wird nicht ergänzt. Cloud-Verzögerungen können die Tageszuordnung beeinflussen."))
    history["sections"].append(_section(graphs, wide=True))

    intro = [_heading("Zeitgesteuertes Aufladen", "mdi:calendar-clock")]
    if g1 and (mode := e.get("charge_mode_select")) and not any(
            e.get(f"time_period_{i}_mode") for i in indices):
        intro.append(_available(_tile(mode, "Lademodus (für beide Zeitfenster)", feature="select-options"), mode))
        intro.append(_available(_mode_help(), mode))
    if strategy:
        intro.append(_available(_tile(strategy, "Ladeeinstellung", feature="select-options"), strategy))
    if strategy:
        intro.append(_condition(_note(
            "Zum Verwenden der Zeitfenster **Zeitgesteuertes Aufladen** auswählen."),
            strategy, "Manuell"))
        intro.append(_condition(_note(
            "Zum Verwenden der Zeitfenster **Zeitgesteuertes Aufladen** auswählen."),
            strategy, "Plug and Play"))
    if indices:
        intro.append(_help("Zeitfenster erklärt",
            "Ausgeschaltete Zeitfenster behalten ihre Uhrzeiten. "
            "Der Status zeigt die Portal-Einstellung, keine tatsächlich laufende Ladung."))
    schedule["sections"].append(_section(intro, wide=True))
    for i in indices:
        period_cards = [_heading(f"Zeitrahmen {i}", "mdi:calendar-clock")]
        if enabled := e.get(f"time_period_{i}_enabled"):
            period_cards.append(_tile(enabled, f"Zeitrahmen {i} Aktiv", icon="mdi:calendar-check", feature="toggle"))
        period_cards.append({"type": "entities", "show_header_toggle": False, "entities": [
            {"entity": e[f"time_period_{i}_{boundary}"], "name": name} for boundary, name in (("start", "Beginn"), ("end", "Ende"))]})
        if entity := e.get(f"time_period_{i}_mode"):
            period_cards.append(_available(_tile(entity, f"Zeitrahmen {i} Lademodus", feature="select-options"), entity))
            period_cards.append(_available(_mode_help(), entity))
        if entity := e.get(f"time_period_{i}_current"):
            period_cards.append(_available(_tile(entity, "Maximaler Strom", feature="numeric-input"), entity))
            period_cards.append(_available(_current_help(), entity))
        period_cards.append(_note("**Zeitfenster-Status:** {{ state_attr('" + e[f"time_period_{i}_start"] + "', 'Zeitfenster-Status') or 'Keine bestätigten Angaben vom Portal' }}"))
        schedule["sections"].append(_section(period_cards))
    if not indices:
        schedule["sections"].append(_section([_note("Für dieses Profil sind noch keine bestätigten Zeitfensterdaten verfügbar.")]))

    options = [_heading("Wallbox-Einstellungen", "mdi:tune")]
    for key, name, feature in (("gun_line_self_lock_enabled", "Kabel-Selbstverriegelung", "toggle"),
                               ("household_current", "Hausstrom-Einstellung", None),
                               ("installer_control_allowed", "Installateursteuerung erlaubt", None)):
        if entity := e.get(key):
            options.append(_available(_tile(entity, name, feature=feature), entity))
            if key == "household_current":
                options.append(_available(_help("Hausstrom-Einstellung erklärt",
                    "Anschlussgrenze des Hauses, kein Ladestrom-Sollwert."), entity))
    info = [_heading("Gerät und Diagnose", "mdi:information-outline")]
    details = [{"entity": e[key], "name": name} for key, name in (
        ("information_model", "Modell"), ("portal_profile", "Portal-Profil"),
        ("information_sn", "Serialnummer"), ("information_softwareVersion", "Software"),
        ("information_hardwareVersion", "Hardware"), ("information_phase", "Hardware-Phasen"),
        ("information_startUpPower", "Startleistung")) if key in e]
    if details:
        info.append({"type": "entities", "title": "Geräteinformationen", "entities": details})
    if not export and box.diagnostics_path:
        info.append({
            "type": "custom:alphaess-diagnostics-download",
            "path": box.diagnostics_path,
            "grid_options": {"columns": 12, "rows": 2},
        })
    if not export and box.export_url:
        info.append(_note(f"[Dashboard als Vorlage herunterladen]({box.export_url})"))
        info.append(_help("Vorlage verwenden",
            "In einem eigenen Dashboard unter **Raw-Konfiguration** einfügen. "
            "Die Kopie bleibt unabhängig von Bridge-Updates. "
            "Der Link gilt zehn Minuten; danach diese Ansicht neu laden."))
    settings["sections"] += [_section(options), _section(info)]
    return views


def build_dashboard(boxes: list[WallboxDashboard], *, url_path: str = "alphaess-wallbox-bridge",
                    export: bool = False) -> dict:
    """One sidebar entry; select a device when more than one is configured."""
    if len(boxes) == 1:
        views = build_wallbox_views(boxes[0], url_path=url_path, export=export)
    else:
        cards = [_heading("Wallbox auswählen")]
        views = [{"title": "Wallboxen", "path": "wallboxen", "icon": "mdi:ev-station",
                  "type": "sections", "max_columns": 2, "sections": [_section(cards)]}]
        for box in boxes:
            prefix = f"wb-{box.entry_id.lower()}-"
            cards.append({"type": "button", "name": box.title, "icon": "mdi:ev-station",
                          "tap_action": {"action": "navigate", "navigation_path": f"/{url_path}/{prefix}wallbox"}})
            views += build_wallbox_views(box, prefix=prefix, url_path=url_path, subview=True, export=export)
        # _section copies the list when filtering None values.
        views[0]["sections"][0]["cards"] = cards
    return {"title": "Wallbox Bridge", "views": views}

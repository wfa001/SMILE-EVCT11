"""Managed dashboard scenarios without network access or an HA installation."""
from __future__ import annotations

import ast
import importlib.util
import json
import runpy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'custom_components/alphaess_portal_bridge'
spec = importlib.util.spec_from_file_location('wallbox_dashboard_builder_test', ROOT / 'dashboard_builder.py')
builder = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = builder
spec.loader.exec_module(builder)
spec = importlib.util.spec_from_file_location('wallbox_dashboard_schedule_test', ROOT / 'schedule.py')
schedule = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schedule)


def adapter_namespace(hass=None):
    """Execute real adapter definitions against minimal HA boundary doubles."""
    tree = ast.parse((ROOT / 'dashboard.py').read_text())
    nodes = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
    for n in nodes:
        if hasattr(n, 'decorator_list'):
            n.decorator_list = []
    panels = {}
    class Base:
        def __init__(self, hass, url_path, config):
            self.hass = hass
            self.config = {**config, 'url_path': url_path}
            self.url_path = url_path
        def _config_updated(self):
            self.hass.events.append('updated')
    def register(hass, kind, **kwargs):
        panels[kwargs['frontend_url_path']] = kwargs
    ns = {
        'Any': object, 'HomeAssistant': object,
        'logging': __import__('logging'), 'timedelta': __import__('datetime').timedelta,
        'DOMAIN': 'alphaess_portal_bridge', 'CONF_SYSTEM_SERIAL': 'system_serial',
        'CONF_SHOW_DASHBOARD': 'show_dashboard',
        'MODE_YAML': 'yaml', 'LOVELACE_DATA': 'lovelace',
        'callback': lambda fn: fn, 'LovelaceConfig': Base, 'HomeAssistantView': object,
        'frontend': SimpleNamespace(async_panel_exists=lambda h,p:p in panels,
                                    async_register_built_in_panel=register,
                                    async_remove_panel=lambda h,p:panels.pop(p, None)),
        'er': SimpleNamespace(async_get=lambda h:h.registry),
        'dr': SimpleNamespace(async_get=lambda h:SimpleNamespace(async_get_device=lambda **kw:None)),
        'settings_object': lambda c:(c.profile,c.settings),
        'schedule_supported': schedule.schedule_supported,
        'strategy_supported': schedule.strategy_supported,
        'supported_dashboard_controls': runpy.run_path(str(ROOT / 'dashboard_capabilities.py'))['supported_dashboard_controls'],
        'WallboxDashboard': builder.WallboxDashboard, 'build_dashboard': builder.build_dashboard,
        'async_sign_path': lambda h,p,expiry:p+'?authSig=TEST-SECRET-SIGNATURE',
        'cached_json_fragment': lambda obj:obj,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*nodes],type_ignores=[])), str(ROOT/'dashboard.py'), 'exec'), ns)
    ns['panels'] = panels
    return ns


class Registry:
    def __init__(self, rows):
        self.rows = rows
    def async_get_entity_id(self, domain, platform, unique):
        return next((e for e,r in self.rows.items() if r.unique_id==unique and e.split('.')[0]==domain), None)
    def async_get(self, entity):
        return self.rows.get(entity)


def entry(key='entry-A',serial='system-A'):
    return SimpleNamespace(entry_id=key,title='Meine Wallbox',data={'system_serial':serial,'password':'NEVER-EXPORT'})


def row(key,entry_id='entry-A',disabled=None):
    return SimpleNamespace(unique_id='system-A_'+key,config_entry_id=entry_id,disabled_by=disabled)


def fake_hass(rows=None):
    events=[]
    def listen(kind,fn):
        events.append(('listen',kind))
        return lambda:events.append(('unlisten',kind))
    return SimpleNamespace(data={'lovelace':SimpleNamespace(dashboards={})},
                           events=events,bus=SimpleNamespace(async_listen=listen),
                           registry=Registry(rows or {}),states=SimpleNamespace(get=lambda e:None))


def coordinator(profile,settings):
    unsub=[]
    return SimpleNamespace(profile=profile,settings=settings,
        async_add_listener=lambda fn:(lambda:unsub.append(True)),unsub=unsub)


def period(**kw):
    return {'isEnable':True,'startTime':'00:15','endTime':'04:45',**kw}


def cards(value):
    if isinstance(value,dict):
        yield value
        for child in value.values():yield from cards(child)
    elif isinstance(value,list):
        for child in value:yield from cards(child)


class DashboardTests(unittest.TestCase):
    def test_registry_uses_renamed_entities_and_rejects_disabled_or_other_entry(self):
        ns=adapter_namespace()
        registry=Registry({'sensor.meine_ladung_neu':row('power'),
                           'sensor.disabled':row('today_energy',disabled='user'),
                           'sensor.foreign':row('status',entry_id='other')})
        self.assertEqual(ns['resolve_entities'](registry,entry()),{'power':'sensor.meine_ladung_neu'})

    def test_g1t_only_exposes_confirmed_two_periods_and_global_mode(self):
        ns=adapter_namespace()
        entities={k:f'{domain}.renamed_{k}' for k,domain in ns['ENTITY_DOMAINS'].items()}
        settings={'chargeMode':2,'timePeriods':[period(),period()]}
        filtered=ns['filter_capabilities'](entities,'g1T',settings)
        config=builder.build_dashboard([builder.WallboxDashboard('A','Garage','g1T',filtered,settings)])
        text=json.dumps(config)
        for forbidden in ('obc_phase_select','smart_mode','time_period_3','charge_strategy_select','time_period_1_mode','time_period_1_current'):
            self.assertNotIn(forbidden,text)
        self.assertIn('renamed_charge_mode_select',text)
        self.assertIn('renamed_time_period_2_start',text)

    def test_missing_or_malformed_g1t_schema_does_not_manufacture_controls(self):
        ns=adapter_namespace()
        entities={'time_period_1_start':'time.start','time_period_1_enabled':'switch.enable'}
        for settings in ({},{'timePeriods':[period()]},{'timePeriods':[{},{}]}):
            self.assertFalse(ns['filter_capabilities'](entities,'g1T',settings))

    def test_g2t_native_charts_and_compact_energy_cards(self):
        ns=adapter_namespace()
        entities={k:f'{domain}.wallbox_{k}' for k,domain in ns['ENTITY_DOMAINS'].items()}
        box=builder.WallboxDashboard('A','Garage','g2T',entities,{'timePeriods':[period(chargeMode=1,chargeCurrent=16)]*3},energy_statistics=True)
        config=builder.build_dashboard([box])
        flat=list(cards(config))
        self.assertEqual(len(config['views']),4)
        self.assertEqual(config['views'][0]['sections'][0]['cards'][1]['type'],'gauge')
        stat=next(c for c in flat if c.get('type')=='statistics-graph')
        self.assertEqual((stat['stat_types'],stat['period']),(['change'],'day'))
        for c in flat:
            self.assertFalse(str(c.get('type','')).startswith('custom:'))
            if c.get('entity') in (entities['today_energy'],entities['last_energy']) and c.get('type')=='tile':
                self.assertEqual(c['grid_options']['rows'],1)
        self.assertNotIn('shelly',json.dumps(config).lower())

    def test_gauge_respects_kw_override_without_relabelling_watts(self):
        config=builder.build_dashboard([builder.WallboxDashboard('A','Garage','g2T',{'power':'sensor.power'},power_unit='kW')])
        gauge=next(c for c in cards(config) if c.get('type')=='gauge')
        self.assertEqual(gauge['max'],11)
        self.assertNotIn('unit',gauge)

    def test_schedule_guidance_only_matches_known_inactive_strategies(self):
        config=builder.build_dashboard([builder.WallboxDashboard(
            'A','Garage','g2T',{'charge_strategy_select':'select.strategy'})])
        schedule_view=config['views'][2]
        hints=[c for c in cards(schedule_view) if c.get('type')=='conditional'
               and 'Zum Verwenden' in c.get('card',{}).get('content','')]
        self.assertEqual({c['conditions'][0]['state'] for c in hints},
                         {'Manuell','Plug and Play'})
        self.assertTrue(all(c['conditions'][0]['entity']=='select.strategy' for c in hints))
        # Renamed and multi-wallbox routes must also reach the correct schedule.
        config=builder.build_dashboard([
            builder.WallboxDashboard('A','Garage','g2T',{'charge_strategy_select':'select.strategy'}),
            builder.WallboxDashboard('B','Carport','g1T',{})],url_path='bridge-2')
        wallbox_view=config['views'][1]
        hint=next(c for c in cards(wallbox_view) if 'Lademodi unter' in c.get('content',''))
        self.assertIn('/bridge-2/wb-a-zeitfenster',hint['content'])

    def test_explanations_collapse_but_connection_warnings_remain_visible(self):
        config=builder.build_dashboard([builder.WallboxDashboard(
            'A','Garage','g2T',{'api_connection':'sensor.api',
            'obc_phase_select':'select.phase','household_current':'number.house'})])
        notes=[c for c in cards(config) if c.get('type')=='markdown']
        warning=next(c for c in notes if 'Bridge-Verbindung prüfen' in c['content'])
        self.assertNotIn('<details',warning['content'])
        for word in ('Phasenwahl erklärt','Hausstrom-Einstellung erklärt','Verlauf richtig lesen'):
            help_card=next(c for c in notes if word in c['content'])
            self.assertIn('<details>',help_card['content'])
            self.assertNotIn('<details open',help_card['content'])
        no_controls=builder.build_dashboard([builder.WallboxDashboard('B','Carport','g1T',{})])
        self.assertNotIn('Hausstrom-Einstellung erklärt',json.dumps(no_controls))
        self.assertNotIn('Ladesteuerung erklärt',json.dumps(no_controls))

    def test_multiple_wallboxes_have_selection_and_disjoint_targets(self):
        boxes=[builder.WallboxDashboard(key,key,'g1T',{'power':f'sensor.{key}'}) for key in ('a','b')]
        config=builder.build_dashboard(boxes)
        self.assertEqual(config['views'][0]['title'],'Wallboxen')
        self.assertEqual(len(config['views']),9)
        paths=[v['path'] for v in config['views']]
        self.assertEqual(len(paths),len(set(paths)))
        a=json.dumps(config['views'][1:5]);b=json.dumps(config['views'][5:])
        self.assertIn('sensor.a',a);self.assertNotIn('sensor.b',a)
        self.assertIn('sensor.b',b);self.assertNotIn('sensor.a',b)

    def test_mode_help_matches_global_and_period_controls_and_disappears_with_them(self):
        entities={'charge_mode_select':'select.global_mode',
                  'time_period_1_start':'time.start','time_period_1_end':'time.end',
                  'time_period_1_mode':'select.period_mode',
                  'time_period_1_current':'number.period_current'}
        config=builder.build_dashboard([builder.WallboxDashboard(
            'A','Garage','g2T',entities,{'timePeriods':[period(chargeMode=4,chargeCurrent=16)]})])
        help_nodes=[c for c in cards(config) if c.get('type')=='conditional'
                    and '<summary>Lademodi erklärt</summary>' in c.get('card',{}).get('content','')]
        self.assertEqual({c['conditions'][0]['entity'] for c in help_nodes},
                         {'select.global_mode','select.period_mode'})
        self.assertEqual(len({c['card']['content'] for c in help_nodes}),1)
        for node in help_nodes:
            self.assertEqual(node['conditions'][0]['state_not'],'unknown')
            parent=next(c for c in cards(config) if c.get('card') is node)
            self.assertEqual(parent['conditions'][0]['state_not'],'unavailable')
        self.assertIn('Ladestrom erklärt',json.dumps(config,ensure_ascii=False))
        config=builder.build_dashboard([builder.WallboxDashboard('B','Carport','g1T',{})])
        self.assertNotIn('Lademodi erklärt',json.dumps(config,ensure_ascii=False))

    def test_g1_mode_help_does_not_require_g2_features(self):
        config=builder.build_dashboard([builder.WallboxDashboard(
            'A','Garage','g1T',{'charge_mode_select':'select.old_wallbox'})])
        text=json.dumps(config,ensure_ascii=False)
        self.assertIn('Lademodi erklärt',text)
        self.assertNotIn('Smart Mode erklärt',text)
        self.assertNotIn('Phasenwahl erklärt',text)

    def test_no_statistic_chart_without_statistics_capability(self):
        config=builder.build_dashboard([builder.WallboxDashboard('A','Garage',None,{})])
        self.assertFalse(any(c.get('type')=='statistics-graph' for c in cards(config)))

    def test_lifecycle_preserves_existing_panel_and_removes_only_owned_panel(self):
        ns=adapter_namespace();hass=fake_hass()
        original=object();hass.data['lovelace'].dashboards['alphaess-wallbox-bridge']=original
        manager=ns['DashboardManager'](hass);hass.data[ns['DATA_MANAGER']]=manager
        self.assertEqual(manager.url_path,'alphaess-wallbox-bridge-2')
        a=coordinator('g1T',{});b=coordinator('g2T',{})
        manager.add(entry(),a);manager.add(entry('entry-B','system-B'),b)
        manager.remove('entry-A')
        self.assertIn(manager.url_path,hass.data['lovelace'].dashboards)
        manager.remove('entry-B')
        self.assertEqual(hass.data['lovelace'].dashboards,{'alphaess-wallbox-bridge':original})
        self.assertEqual((a.unsub,b.unsub),([True],[True]))
        self.assertNotIn(ns['DATA_MANAGER'],hass.data)

    def test_regeneration_follows_rename_and_export_excludes_credentials_and_signed_links(self):
        ns=adapter_namespace();hass=fake_hass({'sensor.old':row('power')})
        manager=ns['DashboardManager'](hass)
        manager.add(entry(),coordinator('g1T',{}))
        self.assertIn('sensor.old',json.dumps(manager.build()))
        hass.registry.rows={'sensor.new':row('power')}
        managed=json.dumps(manager.build())
        self.assertNotIn('sensor.old',managed);self.assertIn('sensor.new',managed)
        self.assertIn('authSig',managed)
        exported=json.dumps(manager.build(entry_id='entry-A',export=True))
        self.assertNotIn('authSig',exported)
        self.assertNotIn('NEVER-EXPORT',exported)
        self.assertNotIn('/api/',exported)
        self.assertNotIn('/alphaess-wallbox-bridge/',exported)

    def test_download_requires_authentication_and_unknown_entries_fail_closed(self):
        ns=adapter_namespace()
        self.assertTrue(ns['DashboardExportView'].requires_auth)
        self.assertIn('{entry_id}',ns['DashboardExportView'].url)


class DashboardOptionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_dashboard_opt_out_across_entry_reloads(self):
        ns = adapter_namespace()
        hass = fake_hass()
        setup = ns['async_setup_dashboard']
        unload = ns['async_unload_dashboard']
        a = entry()
        a.options = {'show_dashboard': False}
        b = entry('entry-B', 'system-B')
        b.options = {}
        g1t = coordinator('g1T', {})
        g2t = coordinator('g2T', {})

        await setup(hass, a, g1t)
        self.assertFalse(ns['panels'])
        self.assertNotIn(ns['DATA_MANAGER'], hass.data)

        await setup(hass, b, g2t)
        manager = hass.data[ns['DATA_MANAGER']]
        self.assertEqual(set(manager.entries), {'entry-B'})

        a.options = {'show_dashboard': True}
        await setup(hass, a, g1t)
        self.assertEqual(set(manager.entries), {'entry-A', 'entry-B'})

        unload(hass, b.entry_id)
        b.options = {'show_dashboard': False}
        await setup(hass, b, g2t)
        self.assertEqual(set(manager.entries), {'entry-A'})
        self.assertIn(manager.url_path, ns['panels'])

        unload(hass, a.entry_id)
        a.options = {'show_dashboard': False}
        await setup(hass, a, g1t)
        self.assertFalse(ns['panels'])
        self.assertNotIn(ns['DATA_MANAGER'], hass.data)


if __name__=='__main__':unittest.main()

"""Dashboard capability scenarios for partial and unexpected portal responses."""
from __future__ import annotations

import copy
import ast
import runpy
from types import SimpleNamespace
import unittest

from test_managed_dashboard import ROOT, adapter_namespace, builder, cards, entry, fake_hass, period

supported = runpy.run_path(str(ROOT / 'dashboard_capabilities.py'))['supported_dashboard_controls']


def g2():
    return {'chargeMode': 1, 'chargeCurrent': 16, 'chargeStrategy': 0,
            'obcPhase': 3, 'smartMode': False,
            'isSupportGunLineSelfLock': True, 'gunLineSelfLockEnable': False,
            'timePeriods': [period(chargeMode=1, chargeCurrent=16) for _ in range(3)]}


class CapabilityTests(unittest.TestCase):
    def test_g1_global_mode_remains_available_in_schedule_mode(self):
        tree = ast.parse((ROOT / 'select.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AlphaESSWallboxModeSelect')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'available')
        class Base:
            available = True
        subject = ast.ClassDef(name='Subject', bases=[ast.Name(id='Base',ctx=ast.Load())],
                               keywords=[],body=[method],decorator_list=[])
        namespace = {'Base': Base, 'settings_object': lambda c: (c.profile, c.settings),
                     **runpy.run_path(str(ROOT / 'schedule.py'))}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[subject],type_ignores=[])),
                     str(ROOT / 'select.py'), 'exec'), namespace)
        entity = namespace['Subject']()
        entity.coordinator = SimpleNamespace(profile='g1T', settings={
            'chargeMode':2, 'chargeStrategy':1, 'timePeriods':[period(),period()]})
        self.assertTrue(entity.available)
        entity.coordinator.profile = 'g2T'
        entity.coordinator.settings['timePeriods'].append(period())
        self.assertFalse(entity.available)
        entity.coordinator.settings['chargeStrategy'] = 0
        self.assertTrue(entity.available)

    def test_unknown_profile_keeps_readings_but_no_charging_controls(self):
        ns = adapter_namespace()
        entities = {key: f'{domain}.renamed_{key}' for key, domain in ns['ENTITY_DOMAINS'].items()}
        result = ns['filter_capabilities'](entities, None, g2())
        self.assertIn('power', result)
        self.assertIn('information_model', result)
        for key in ('start', 'stop', 'smart_mode', 'charge_mode_select', 'time_period_1_start'):
            self.assertNotIn(key, result)

    def test_g1_fields_do_not_unlock_g2_write_paths(self):
        settings = g2()
        settings['timePeriods'] = settings['timePeriods'][:2]
        controls = supported('g1T', settings)
        self.assertIn('time_period_2_end', controls)
        self.assertIn('charge_strategy_select', controls)
        for key in ('smart_mode', 'obc_phase_select', 'gun_line_self_lock_enabled', 'time_period_3_end'):
            self.assertNotIn(key, controls)
        del settings['chargeStrategy']
        self.assertNotIn('charge_strategy_select', supported('g1T', settings))

    def test_truncated_g2_schedule_never_offers_an_unwritable_window(self):
        for count in (0, 1, 2):
            settings = g2()
            settings['timePeriods'] = settings['timePeriods'][:count]
            self.assertFalse(any(k.startswith('time_period_') for k in supported('g2T', settings)))

    def test_bad_g2_period_does_not_remove_valid_siblings(self):
        settings = g2()
        settings['timePeriods'][1]['startTime'] = '24:00'
        controls = supported('g2T', settings)
        self.assertIn('time_period_1_start', controls)
        self.assertIn('time_period_3_start', controls)
        self.assertFalse(any(k.startswith('time_period_2_') for k in controls))

    def test_missing_null_or_wrong_types_do_not_become_capabilities(self):
        cases = {'chargeMode': ('charge_mode_select', [None, True, '1', 9]),
                 'chargeCurrent': ('custom_charge_current', [None, True, 5, 17, 6.5]),
                 'chargeStrategy': ('charge_strategy_select', [None, True, '0', 3]),
                 'obcPhase': ('obc_phase_select', [None, True, '3', 4]),
                 'smartMode': ('smart_mode', [None, 0, 'true']),
                 'gunLineSelfLockEnable': ('gun_line_self_lock_enabled', [None, 0, 'true'])}
        for field, (control, values) in cases.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    settings = g2()
                    settings[field] = value
                    self.assertNotIn(control, supported('g2T', settings))
            settings = g2()
            del settings[field]
            self.assertNotIn(control, supported('g2T', settings))
        self.assertEqual(supported('g2T', None), set())

    def test_false_is_a_valid_switch_state_and_support_flag_is_required(self):
        controls = supported('g2T', g2())
        self.assertIn('smart_mode', controls)
        self.assertIn('gun_line_self_lock_enabled', controls)
        for flag in (None, False, 1):
            settings = g2()
            settings['isSupportGunLineSelfLock'] = flag
            self.assertNotIn('gun_line_self_lock_enabled', supported('g2T', settings))

    def test_detection_never_changes_portal_settings(self):
        settings = g2()
        before = copy.deepcopy(settings)
        supported('g2T', settings)
        self.assertEqual(settings, before)

    def test_capability_refresh_does_not_rebuild_for_normal_value_changes(self):
        ns = adapter_namespace()
        hass = fake_hass()
        callbacks = []
        coordinator = SimpleNamespace(profile='g2T', settings=g2(),
            async_add_listener=lambda fn: (callbacks.append(fn) or (lambda: None)))
        manager = ns['DashboardManager'](hass)
        manager.add(entry(), coordinator)
        initial = hass.events.count('updated')
        coordinator.settings['obcPhase'] = 1
        coordinator.settings['smartMode'] = True
        callbacks[0]()
        self.assertEqual(hass.events.count('updated'), initial)
        del coordinator.settings['smartMode']
        callbacks[0]()
        self.assertEqual(hass.events.count('updated'), initial + 1)
        coordinator.settings['smartMode'] = False
        callbacks[0]()
        self.assertEqual(hass.events.count('updated'), initial + 2)

    def test_smart_hint_tracks_only_this_wallbox_and_does_not_hide_the_switch(self):
        entities = {'smart_mode': 'switch.renamed_smart', 'obc_phase_select': 'select.renamed_phase',
                    'charge_mode_select': 'select.renamed_mode', 'charge_strategy_select': 'select.renamed_strategy'}
        config = builder.build_dashboard([builder.WallboxDashboard('A', 'Garage', 'g2T', entities)])
        hint = next(c for c in cards(config) if c.get('show_empty') is False)
        self.assertEqual(set(hint['entity_id']), set(entities.values()))
        self.assertTrue(any(c.get('entity') == entities['smart_mode'] and c.get('type') == 'tile'
                            for c in cards(config)))
        no_phase = builder._smart_mode_hint({'smart_mode': 'switch.other'})
        self.assertEqual(no_phase['entity_id'], ['switch.other'])
        self.assertNotIn('renamed_phase', no_phase['content'])


if __name__ == '__main__':
    unittest.main()

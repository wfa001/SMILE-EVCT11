"""Diagnosis must separate API health, status evidence and fault categories."""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from test_fast_live_polling import FakeCoordinator, PortalConnectionError
from test_managed_dashboard import builder, cards

ROOT=Path(__file__).resolve().parents[1]/'custom_components/alphaess_portal_bridge'
helper=runpy.run_path(str(ROOT/'wallbox_diagnosis.py'))
summarize=helper['summarize_wallbox']


def diagnosis(**changes):
    args={'profile':'g2T','model':'SMILE-G3-EVCT11/S','status':{'status':'Charging','power':0},
          'source':'real_status','portal':'Verbunden','age':2,'stale_after':25}
    return summarize(**(args|changes))


class DiagnosisTests(unittest.TestCase):
    def test_all_documented_names_and_spacing_aliases_have_bounded_categories(self):
        for code in ('OverVolt','UnderVolt','OverCurr','OverFreq','UnderFreq','OverTemp',
                     'OverDCLeak','Over DCLeak','PhaseError','Phase Error','CableRCError','CableRC Error'):
            result=diagnosis(status={'status':'Error','faultCode':code})
            self.assertIsNotNone(result['fault_text'])
            self.assertLess(len(result['fault_text']),50)

    def test_reachable_portal_does_not_prove_device_communication(self):
        for status in ({},{'power':0},{'status':None}):
            result=diagnosis(status=status)
            self.assertEqual(result['portal'],'Verbunden')
            self.assertEqual(result['summary'],'Keine Statusrückmeldung')
            self.assertNotIn('RS485',result['communication'])

    def test_system_fallback_or_failed_reply_is_not_a_communication_fault(self):
        for result in (diagnosis(source='system',status={}),diagnosis(age=None,status={}),
                       diagnosis(age=90,status={},portal='Getrennt')):
            self.assertNotEqual(result['summary'],'Keine Statusrückmeldung')
        self.assertEqual(diagnosis(age=90,portal='Getrennt')['summary'],'Portal nicht erreichbar')

    def test_zero_power_and_known_waiting_states_are_not_faults(self):
        for state in ('Charging','NotInsertedGun','PendingStart','InsufficientPower','Upgrading'):
            result=diagnosis(status={'status':state,'power':0})
            self.assertEqual(result['summary'],'Kein Fehlerstatus gemeldet')
            self.assertFalse(result['fault_reported'])

    def test_named_fault_is_translated_without_inferring_a_repair(self):
        for model in ('SMILE-EVCT11','SMILE-G3-EVCT11','SMILE-G3-EVCT11/S'):
            result=diagnosis(model=model,status={'status':'Fault','faultCode':'OverTemp'})
            self.assertEqual(result['summary'],'Wallbox meldet Störung')
            self.assertEqual(result['fault_text'],'Übertemperatur')
            self.assertEqual(result['recognized_name'],'OverTemp')

    def test_unknown_model_and_numeric_codes_get_no_invented_meaning(self):
        for code in (0,1,2,6,12,65535,'0','12','FutureCode'):
            result=diagnosis(status={'status':'Fault','faultCode':code})
            self.assertEqual(result['raw_code'],code)
            self.assertIsNone(result['recognized_name'])
            self.assertIn('keine Zuordnung',result['fault_explanation'])
        self.assertIsNone(diagnosis(model='Other model',status={'status':'Fault','faultCode':'OverTemp'})['fault_text'])

    def test_old_fault_code_or_normal_state_does_not_prove_active_fault(self):
        result=diagnosis(status={'status':'NotInsertedGun','faultCode':'OverTemp'})
        self.assertEqual(result['summary'],'Kein Fehlerstatus gemeldet')
        self.assertFalse(result['fault_reported'])
        old=diagnosis(age=40,status={'status':'Fault','faultCode':'OverTemp'})
        self.assertFalse(old['fault_reported'])
        self.assertEqual(old['summary'],'Status nicht aktuell prüfbar')

    def test_invalid_or_future_data_is_never_fresh_or_all_clear(self):
        for changes in ({'age':-1},{'age':float('nan')},{'age':None},{'profile':'future'},
                        {'status':[]},{'source':[]},{'status':{'status':[]}}):
            result=diagnosis(**changes)
            self.assertNotEqual(result['summary'],'Kein Fehlerstatus gemeldet')
        self.assertEqual(diagnosis(status={'status':'FutureState'})['summary'],'Status nicht eindeutig')

    def test_default_export_does_not_contain_unknown_raw_values(self):
        private='PRIVATE-EMAIL-TOKEN-SERIAL'
        result=diagnosis(model=private,status={'status':private,'faultCode':private},source=private)
        public=helper['public_diagnosis'](result)
        self.assertNotIn(private,json.dumps(public))
        self.assertNotIn('raw_code',public)
        self.assertEqual(helper['public_write_feedback'](SimpleNamespace(settings_feedback=SimpleNamespace(state=private))), 'Nicht verfügbar')

    def test_dashboard_separates_portal_and_device_diagnosis(self):
        config=builder.build_dashboard([builder.WallboxDashboard('A','Garage','g2T',
            {'api_connection':'sensor.api','diagnosis':'sensor.diagnosis'})])
        settings=config['views'][3]
        tiles=[c for c in cards(settings) if c.get('type')=='tile']
        self.assertTrue(any(c['entity']=='sensor.api' and c['name']=='Portal-Verbindung' for c in tiles))
        self.assertTrue(any(c['entity']=='sensor.diagnosis' for c in tiles))
        warning=next(c for c in cards(config['views'][0]) if c.get('show_empty') is False)
        self.assertEqual(warning['entity_id'],['sensor.diagnosis'])


class CoordinatorDiagnosisTests(unittest.IsolatedAsyncioTestCase):
    async def test_reply_after_polling_stopped_does_not_renew_device_status(self):
        item=FakeCoordinator()
        old=datetime.now(timezone.utc)-timedelta(minutes=5)
        item._last_status_success=old
        async def reply_after_stop(serial):
            item._stopped=True
            return {'status':'Charging'}
        item.api.async_get_live_status=reply_after_stop
        await item._async_live_refresh(None)
        self.assertEqual(item._last_status_success,old)
        self.assertEqual(item.notify_count,0)

    async def test_new_sensor_remains_read_only_and_default_export_omits_raw_code(self):
        item=FakeCoordinator()
        item.api_connection_status='Verbunden'
        item.update_interval=timedelta(seconds=30)
        item.last_update_success=False
        item._last_status_success=datetime.now(timezone.utc)
        item._advanced_diagnostics_until=0.0
        wallbox={'model':'SMILE-G3-EVCT11/S','sn':'PRIVATE-SERIAL','g2T':{}}
        item.api._find_wallbox_data=lambda document,serial:wallbox
        item.data.update(configuration={'wallbox':wallbox},
                         wallbox_status={'status':'Fault','faultCode':'PRIVATE-UNKNOWN-CODE'},
                         wallbox_status_source='real_status')
        source=ast.parse((ROOT/'sensor.py').read_text())
        cls=next(n for n in source.body if isinstance(n,ast.ClassDef) and n.name=='AlphaESSWallboxDiagnosisSensor')
        class Base:
            def __init__(self,coordinator,entry,key):
                self.coordinator=coordinator
                self.key=key
            @property
            def wallbox(self):return wallbox
        ns={'AlphaESSWallboxEntity':Base,'SensorEntity':type('SensorEntity',(),{}),
            'EntityCategory':SimpleNamespace(DIAGNOSTIC='diagnostic'),**helper}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[cls],type_ignores=[])),str(ROOT/'sensor.py'),'exec'),ns)
        sensor=ns['AlphaESSWallboxDiagnosisSensor'](item,None)
        self.assertTrue(sensor.available)
        self.assertEqual(sensor.key,'diagnosis')
        self.assertEqual(sensor.native_value,'Wallbox meldet Störung')
        self.assertEqual(sensor.extra_state_attributes['Fehlercode (Portal)'],'PRIVATE-UNKNOWN-CODE')
        item._stopped=True
        self.assertEqual(sensor.native_value,'Status nicht aktuell prüfbar')
        item._stopped=False
        from test_diagnostics_privacy import load_helpers
        export=await load_helpers()['async_get_config_entry_diagnostics'](
            SimpleNamespace(data={'alphaess_portal_bridge':{'entry':item}}),SimpleNamespace(entry_id='entry'))
        self.assertEqual(export['diagnostics_schema'],3)
        self.assertTrue(export['health_summary']['fault_reported'])
        self.assertNotIn('PRIVATE-',json.dumps(export))
        self.assertNotIn('advanced_api_snapshot',export)

    async def test_status_reply_age_is_independent_of_failed_settings_read(self):
        item=FakeCoordinator('g1T')
        item._last_full_success=datetime.now(timezone.utc)-timedelta(minutes=10)
        item._last_status_success=item._last_full_success
        item._last_live_success=None
        item._full_consecutive_errors=0
        item._live_status_supported=False
        item.update_interval=timedelta(seconds=30)
        item.api.async_get_wallbox_data=AsyncMock(return_value={
            'wallbox_status':{'status':'NotInsertedGun'},'wallbox_status_source':'system',
            'configuration_read_ok':False})
        before=item._last_full_success
        await item._async_update_data()
        self.assertEqual(item._last_full_success,before)
        self.assertGreater(item._last_status_success,before)
        tree=ast.parse((ROOT/'coordinator.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='AlphaESSWallboxCoordinator')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='api_connection_status')
        method.decorator_list=[]
        ns={'datetime':datetime,'timezone':timezone}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),str(ROOT/'coordinator.py'),'exec'),ns)
        self.assertEqual(ns['api_connection_status'](item),'Gestört')

    async def test_live_failure_does_not_renew_status_timestamp(self):
        item=FakeCoordinator()
        old=datetime.now(timezone.utc)-timedelta(minutes=5)
        item._last_status_success=old
        item.api.statuses=[PortalConnectionError(status=503)]
        await item._async_live_refresh(None)
        self.assertEqual(item._last_status_success,old)


if __name__=='__main__':unittest.main()

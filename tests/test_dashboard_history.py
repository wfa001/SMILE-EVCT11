"""History must remain readable across current strategy and unit changes."""
from __future__ import annotations

from types import SimpleNamespace
import unittest

from test_managed_dashboard import adapter_namespace, builder, cards, entry, fake_hass, period, row


def state(unit='kWh', device='energy', kind='total_increasing', value='2.13'):
    return SimpleNamespace(state=value, attributes={
        'device_class':device, 'state_class':kind, 'unit_of_measurement':unit})


class HistoryTests(unittest.TestCase):
    def test_history_is_not_hidden_by_current_charge_strategy(self):
        entities={'power':'sensor.power','mode':'sensor.mode',
                  'charge_mode_select':'select.mode','charge_strategy_select':'select.strategy'}
        for i in range(1,4):
            for suffix in ('start','end','mode','enabled'):
                entities[f'time_period_{i}_{suffix}']=f'sensor.p{i}_{suffix}'
        for strategy in (0,1,2):
            settings={'chargeStrategy':strategy,'timePeriods':[period()]*3}
            config=builder.build_dashboard([builder.WallboxDashboard('A','Garage','g2T',entities,settings)])
            view=config['views'][1]
            self.assertFalse(any(c.get('type')=='conditional' for c in cards(view)))
            timeline=next(c for c in cards(view) if c.get('title','').startswith('Ladeeinstellung und'))
            ids={item['entity'] for item in timeline['entities']}
            self.assertEqual(ids,{'sensor.mode','select.strategy','sensor.p1_mode','sensor.p2_mode','sensor.p3_mode'})
            self.assertNotIn('select.mode',ids)
            self.assertEqual(timeline['grid_options']['rows'],'auto')
            power=next(c for c in cards(view) if c.get('title','').startswith('Ladeleistung'))
            self.assertEqual(power['grid_options']['rows'],6)

    def test_energy_tiles_are_compact_and_single_tile_uses_full_width(self):
        for entities in ({'today_energy':'sensor.day','last_energy':'sensor.session'},
                         {'last_energy':'sensor.session'}):
            config=builder.build_dashboard([builder.WallboxDashboard('A','Garage','g1T',entities)])
            tiles=[c for c in cards(config['views'][0]) if c.get('type')=='tile']
            self.assertEqual(len(tiles),len(entities))
            self.assertTrue(all(c['grid_options']['rows']==1 for c in tiles))
            self.assertTrue(all(c['grid_options']['columns']==(6 if len(entities)==2 else 12) for c in tiles))
            session=next(c for c in tiles if c['entity']=='sensor.session')
            self.assertEqual(session['name'],'Ladesitzung')

    def test_smart_mode_history_never_claims_measured_phases_or_creates_g1_features(self):
        entities={'obc_phase_select':'select.phase','smart_mode':'switch.smart'}
        config=builder.build_dashboard([builder.WallboxDashboard('A','Garage','g2T',entities)])
        graph=next(c for c in cards(config['views'][1]) if c.get('title','').startswith('Phasenwahl und'))
        self.assertIn('Einstellungen',graph['title'])
        self.assertEqual({e['entity'] for e in graph['entities']},set(entities.values()))
        config=builder.build_dashboard([builder.WallboxDashboard('B','Carport','g1T',{})])
        self.assertFalse(any(c.get('title','').startswith('Phasenwahl und') for c in cards(config)))

    def test_last_charge_tile_and_current_charge_are_separate(self):
        config = builder.build_dashboard([builder.WallboxDashboard("A", "Garage", "g2T", {
            "status": "sensor.status", "last_energy": "sensor.live",
            "last_completed_energy": "sensor.completed", "today_energy": "sensor.day",
        })])
        overview = list(cards(config["views"][0]))
        completed = next(card for card in overview if card.get("entity") == "sensor.completed")
        self.assertEqual(completed["name"], "Letzte Ladung")
        self.assertFalse(any(card.get("entity") == "sensor.live" for card in overview))
        current = next(card for card in overview if "Energiewert ausstehend" in card.get("card", {}).get("content", ""))
        self.assertEqual(current["conditions"][0]["state"], "Lädt")

    def test_only_daily_counter_supplies_statistics(self):
        config=builder.build_dashboard([builder.WallboxDashboard('A','Garage','g2T',
            {'today_energy':'sensor.day','last_energy':'sensor.session'}, energy_statistics=True)])
        graph=next(c for c in cards(config) if c.get('type')=='statistics-graph')
        self.assertEqual(graph['entities'],[{'entity':'sensor.day','name':'Geladene Energie'}])
        self.assertEqual((graph['days_to_show'],graph['period'],graph['stat_types']), (7,'day',['change']))

    def test_local_prerequisites_do_not_depend_on_current_numeric_state(self):
        ns=adapter_namespace(); hass=fake_hass()
        hass.data['test_recorder']=SimpleNamespace(entity_filter=None)
        for value in ('2.13','unknown','unavailable'):
            hass.states.get=lambda entity:state(value=value)
            self.assertEqual(ns['daily_statistics_eligibility'](hass,'sensor.renamed'),(True,None))

    def test_wrong_statistics_kind_device_or_unit_is_rejected(self):
        ns=adapter_namespace(); hass=fake_hass()
        hass.data['test_recorder']=SimpleNamespace(entity_filter=None)
        for wrong in (state(kind=None),state(kind='measurement'),state(device='power'),state(unit='W'),state(unit=None)):
            hass.states.get=lambda entity:wrong
            self.assertFalse(ns['daily_statistics_eligibility'](hass,'sensor.day')[0])
        hass.states.get=lambda entity:state(unit='Wh')
        self.assertTrue(ns['daily_statistics_eligibility'](hass,'sensor.day')[0])

    def test_missing_recorder_or_excluded_daily_counter_gets_specific_help(self):
        ns=adapter_namespace(); hass=fake_hass()
        hass.states.get=lambda entity:state()
        allowed,reason=ns['daily_statistics_eligibility'](hass,'sensor.day')
        self.assertFalse(allowed);self.assertIn('nicht aktiv',reason)
        hass.data['test_recorder']=SimpleNamespace(entity_filter=lambda entity:entity=='sensor.other')
        allowed,reason=ns['daily_statistics_eligibility'](hass,'sensor.day')
        self.assertFalse(allowed);self.assertIn('ausgeschlossen',reason)
        config=builder.build_dashboard([builder.WallboxDashboard('A','Garage','g2T',
            {'today_energy':'sensor.day'},energy_statistics_note=reason)])
        self.assertFalse(any(c.get('type')=='statistics-graph' for c in cards(config)))

    def test_statistics_prerequisite_changes_update_layout_but_counter_changes_do_not(self):
        ns=adapter_namespace(); hass=fake_hass({'sensor.day':row('today_energy')})
        callbacks=[]
        coordinator=SimpleNamespace(profile='g1T',settings={},
            async_add_listener=lambda fn:(callbacks.append(fn) or (lambda:None)))
        manager=ns['DashboardManager'](hass); manager.add(entry(),coordinator)
        before=hass.events.count('updated')
        values={'sensor.day':state()}
        hass.states.get=lambda entity:values.get(entity)
        hass.data['test_recorder']=SimpleNamespace(entity_filter=None)
        callbacks[0]()
        self.assertEqual(hass.events.count('updated'),before+1)
        self.assertTrue(any(c.get('type')=='statistics-graph' for c in cards(manager.build())))
        values['sensor.day']=state(value='3.2');callbacks[0]()
        self.assertEqual(hass.events.count('updated'),before+1)
        hass.data['test_recorder'].entity_filter=lambda entity:False
        callbacks[0]()
        self.assertEqual(hass.events.count('updated'),before+2)
        self.assertFalse(any(c.get('type')=='statistics-graph' for c in cards(manager.build())))


if __name__=='__main__':
    unittest.main()

"""Device metadata must follow the portal without changing HA identities."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'custom_components/alphaess_portal_bridge/entity.py'


class CoordinatorEntity:
    @classmethod
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, coordinator):
        self.coordinator = coordinator


def entity_for(wallbox):
    tree = ast.parse(SOURCE.read_text())
    selected = [node for node in tree.body if (
        isinstance(node, ast.FunctionDef) and node.name == 'wallbox_object'
    ) or (isinstance(node, ast.ClassDef) and node.name == 'AlphaESSWallboxEntity')]
    ns = {'CoordinatorEntity': CoordinatorEntity, 'DeviceInfo': dict,
          'AlphaESSWallboxCoordinator': object,
          'DOMAIN': 'alphaess_portal_bridge', 'CONF_SYSTEM_SERIAL': 'system_serial'}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *selected], type_ignores=[])), str(SOURCE), 'exec'), ns)
    coordinator = SimpleNamespace(data={'configuration': wallbox}, api=SimpleNamespace(
        _find_wallbox_data=lambda config, serial: config))
    entry = SimpleNamespace(data={'system_serial': 'example-system'})
    return ns['AlphaESSWallboxEntity'](coordinator, entry, 'status')


class DeviceMetadataTests(unittest.TestCase):
    def test_g2t_model_and_versions_come_from_portal(self):
        entity = entity_for({'model': 'SMILE-G3-EVCT11/S', 'softwareVersion': '1.6.610', 'hardwareVersion': '1.0.02'})
        info = entity.device_info
        self.assertEqual(info['model'], 'SMILE-G3-EVCT11/S')
        self.assertEqual(info['sw_version'], '1.6.610')
        self.assertEqual(info['hw_version'], '1.0.02')
        self.assertEqual(info['identifiers'], {('alphaess_portal_bridge', 'example-system')})
        self.assertEqual(entity._attr_unique_id, 'example-system_status')

    def test_g1t_model_is_not_replaced_with_g2t(self):
        self.assertEqual(entity_for({'model': 'SMILE-EVCT11'}).device_info['model'], 'SMILE-EVCT11')

    def test_missing_or_invalid_metadata_does_not_claim_an_old_model(self):
        for model in (None, '', ' ', 123):
            info = entity_for({'model': model, 'softwareVersion': None, 'hardwareVersion': 123}).device_info
            self.assertEqual(info['model'], 'AlphaESS Wallbox')
            self.assertNotIn('sw_version', info)
            self.assertNotIn('hw_version', info)

    def test_metadata_uses_latest_configuration_with_stable_identity(self):
        entity = entity_for({})
        before = entity.device_info
        entity.coordinator.data['configuration'] = {'model': 'SMILE-G3-EVCT11/S'}
        self.assertEqual(entity.device_info['model'], 'SMILE-G3-EVCT11/S')
        self.assertEqual(entity.device_info['identifiers'], before['identifiers'])

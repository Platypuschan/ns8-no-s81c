import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'imageroot/pypkg/localfonts/lifecycle.py'

class LifecycleTests(unittest.TestCase):
    def load(self):
        self.assertTrue(SOURCE.exists(), 'native module lifecycle is not implemented')
        spec = importlib.util.spec_from_file_location('lf_lifecycle', SOURCE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_units_are_oneshot_and_instance_scoped(self):
        mod = self.load()
        units = mod.units('no-s81c1', Path('/var/lib/nethserver/no-s81c1/state'))
        self.assertEqual(set(units), {'no-s81c1-refresh.service','no-s81c1-refresh.timer','no-s81c1-refresh.path'})
        service = units['no-s81c1-refresh.service']
        self.assertIn('Type=oneshot', service)
        self.assertIn('runagent -m no-s81c1 python3 -m localfonts.actions reconcile', service)
        self.assertIn('ProtectSystem=strict', service)
        self.assertIn('OnUnitInactiveSec=15min', units['no-s81c1-refresh.timer'])
        self.assertIn('PathChanged=/var/lib/nethserver/cluster/ui/css', units['no-s81c1-refresh.path'])

    def test_install_is_idempotent_and_refuses_foreign_units(self):
        mod = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            unitdir = Path(tmp)
            calls = []
            ctl = lambda *args: calls.append(args)
            state = Path('/var/lib/nethserver/no-s81c1/state')
            mod.install('no-s81c1', state, unitdir, ctl)
            self.assertEqual(len(list(unitdir.glob('*.service'))), 1)
            self.assertIn(('daemon-reload',), calls)
            calls.clear()
            mod.install('no-s81c1', state, unitdir, ctl)
            self.assertNotIn(('daemon-reload',), calls)
            service = unitdir / 'no-s81c1-refresh.service'
            service.write_text('foreign unit')
            with self.assertRaises(RuntimeError):
                mod.install('no-s81c1', state, unitdir, ctl)
            self.assertEqual(service.read_text(), 'foreign unit')

    def test_remove_only_owned_units_and_stop_watchers_first(self):
        mod = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            unitdir = Path(tmp)
            calls = []
            ctl = lambda *args: calls.append(args)
            state = Path('/var/lib/nethserver/no-s81c1/state')
            mod.install('no-s81c1', state, unitdir, ctl)
            other = unitdir / 'guardian1.service'
            other.write_text('unrelated')
            calls.clear()
            mod.remove('no-s81c1', state, unitdir, ctl)
            self.assertEqual(other.read_text(), 'unrelated')
            self.assertEqual(len(list(unitdir.glob('no-s81c1*'))), 0)
            self.assertEqual(calls[0][0:2], ('disable', '--now'))
            self.assertEqual(calls[0][2:], ('no-s81c1-refresh.path','no-s81c1-refresh.timer'))
            calls.clear()
            mod.remove('no-s81c1', state, unitdir, ctl)
            self.assertEqual(calls, [], 'repeated cleanup must not stop absent units')

if __name__ == '__main__':
    unittest.main()

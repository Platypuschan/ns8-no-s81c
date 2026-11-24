import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import io
import os
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'imageroot/pypkg'))

class ActionsTests(unittest.TestCase):
    def test_disable_restores_and_scheduled_reconcile_stays_disabled(self):
        try:
            from localfonts.actions import Controller
        except ImportError:
            self.fail('module actions missing')
        with tempfile.TemporaryDirectory() as tmp:
            engine = Mock()
            engine.reconcile.return_value = {'remaining_remote': 0}
            engine.disable.return_value = {'remaining_local': 0}
            engine.status.return_value = {'remaining_remote': 1}
            life = Mock()
            ctrl = Controller(engine, 'no-s81c1', Path(tmp), life)
            result = ctrl.execute('configure-module', {'enabled':False})
            self.assertFalse(result['enabled'])
            engine.disable.assert_called_once()
            ctrl.execute('reconcile', {})
            engine.reconcile.assert_not_called()
            result = ctrl.execute('configure-module', {'enabled':True})
            self.assertTrue(result['enabled'])
            engine.reconcile.assert_called_once()

    def test_refresh_fonts_uses_configured_state_without_changing_it(self):
        from localfonts.actions import Controller
        with tempfile.TemporaryDirectory() as tmp:
            engine = Mock()
            engine.reconcile.return_value = {'ok':True}
            engine.status.return_value = {'ok':True}
            engine.disable.return_value = {'ok':True}
            ctrl = Controller(engine, 'no-s81c1', Path(tmp), Mock())
            self.assertTrue(ctrl.execute('refresh-fonts', {})['enabled'])
            engine.reconcile.assert_called_once()
            ctrl.execute('configure-module', {'enabled':False})
            result = ctrl.execute('refresh-fonts', {})
            self.assertFalse(result['enabled'])
            engine.reconcile.assert_called_once()
            engine.status.assert_called_once()

    def test_font_status_action_does_not_collide_with_core_get_status(self):
        root = Path(__file__).resolve().parents[1] / 'imageroot/actions'
        self.assertTrue((root/'get-font-status/50execute').exists())
        self.assertFalse((root/'get-status').exists())

    def test_real_engine_disabled_status_is_healthy_and_reenable_works(self):
        from localfonts.actions import Controller
        from localfonts.engine import Engine
        from test_engine import css, F1, FakeDL
        with tempfile.TemporaryDirectory() as tmp:
            ui, state = Path(tmp)/'ui', Path(tmp)/'state'
            ui.mkdir()
            (ui/'a.css').write_text(css(F1))
            ctrl = Controller(Engine(ui,state,downloader=FakeDL()), 'no-s81c1', state, Mock())
            self.assertTrue(ctrl.execute('configure-module', {'enabled':True})['ok'])
            self.assertTrue(ctrl.execute('configure-module', {'enabled':False})['ok'])
            off = ctrl.execute('get-status', {})
            self.assertFalse(off['enabled'])
            self.assertTrue(off['ok'], 'intentionally disabled module must not report unhealthy')
            self.assertTrue(ctrl.execute('configure-module', {'enabled':True})['ok'])
            self.assertNotIn('s81c', (ui/'a.css').read_text())

    def test_main_non_ok_status_is_nonzero_even_without_errors(self):
        from localfonts import actions
        with tempfile.TemporaryDirectory() as tmp:
            engine = Mock()
            engine.status.return_value = {'ok':False,'errors':[]}
            with patch.dict(os.environ, {'MODULE_ID':'no-s81c1','AGENT_STATE_DIR':tmp}), \
                 patch.object(actions.lifecycle, 'units'), \
                 patch('localfonts.engine.Engine', return_value=engine), \
                 patch.object(sys,'stdin',io.StringIO('')), \
                 patch.object(sys,'stdout',io.StringIO()), \
                 patch.object(sys,'argv',['actions','get-status']):
                self.assertEqual(actions.main(), 1)

if __name__ == '__main__':
    unittest.main()

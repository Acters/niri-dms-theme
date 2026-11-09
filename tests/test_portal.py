# SPDX-License-Identifier: MIT
"""Portal activation is desktop-gated and never changes manager/app state."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from themekit import app, integrate, portal
from themekit.paths import context


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='niri-portal-tests-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ctx = context(str(self.root/'home with spaces % $dollar'))
        self.backend = self.root/'backend'
        self.backend.write_text('#!'+sys.executable+'\nimport os,sys,json\n'
            'keys=("XDG_CURRENT_DESKTOP","QT_STYLE_OVERRIDE","QTENGINE_CONFIG","NIRI_DMS_THEME_PROFILE",'
            '"QT_PLUGIN_PATH","XDG_DATA_DIRS","XDG_CONFIG_DIRS","KEEP_PREF")\n'
            'print(json.dumps({"argv":sys.argv[1:],"env":{key:os.environ.get(key) for key in keys}}))\n')
        self.backend.chmod(0o700)
        self.wrapper = self.root/'wrapper'
        self.wrapper.write_bytes(portal.launcher(self.ctx,app.environment(self.ctx),self.backend))
        self.wrapper.chmod(0o700)

    def launch(self, desktop):
        env={'PATH':'/usr/bin:/bin','XDG_CURRENT_DESKTOP':desktop,'QT_STYLE_OVERRIDE':'Other',
             'XDG_DATA_DIRS':'/custom/data','XDG_CONFIG_DIRS':'/custom/config',
             'QT_PLUGIN_PATH':'/custom/plugins','KEEP_PREF':'untouched'}
        result=subprocess.run([str(self.wrapper),'--one','argument with spaces'],
                              env=env,capture_output=True,text=True,check=True)
        return json.loads(result.stdout)

    def test_niri_backend_receives_profile_but_preserves_desktop_and_other_roots(self):
        result=self.launch('NIRI:Wayland');values=result['env']
        self.assertEqual(result['argv'],['--one','argument with spaces'])
        self.assertEqual(values['XDG_CURRENT_DESKTOP'],'NIRI:Wayland')
        self.assertEqual(values['QT_STYLE_OVERRIDE'],'NiriGlass')
        self.assertEqual(values['QTENGINE_CONFIG'],str(Path(self.ctx['PROFILE_CONFIG'])/'qtengine.json'))
        self.assertEqual(values['NIRI_DMS_THEME_PROFILE'],'niri-dms-glass')
        self.assertEqual(values['QT_PLUGIN_PATH'],self.ctx['PLUGIN_ROOT']+':/custom/plugins')
        self.assertEqual(values['XDG_DATA_DIRS'],self.ctx['PROFILE_SHARE']+':/custom/data')
        self.assertTrue(values['XDG_CONFIG_DIRS'].endswith(':/custom/config'))
        self.assertEqual(values['KEEP_PREF'],'untouched')

    def test_other_desktops_do_not_get_profile_overrides(self):
        for desktop in ('COSMIC','notniri',''):
            with self.subTest(desktop=desktop):
                values=self.launch(desktop)['env']
                self.assertEqual(values['QT_STYLE_OVERRIDE'],'Other')
                self.assertIsNone(values['NIRI_DMS_THEME_PROFILE'])
                self.assertIsNone(values['QTENGINE_CONFIG'])
                self.assertEqual(values['QT_PLUGIN_PATH'],'/custom/plugins')

    def test_unit_uses_execstart_quoting_not_environmentfile_quoting(self):
        unit=portal.service_dropin('/a path/percent%/$dollar/quote"/wrapper').decode()
        self.assertIn('ExecStart=\nExecStart="',unit)
        self.assertIn('percent%%/$$dollar/quote\\"',unit)
        self.assertNotIn('Environment=',unit)
        with self.assertRaises(ValueError):portal.service_dropin('/bad\npath')

    def test_install_restore_owns_only_the_wrapper_and_dropin_and_never_restarts_portal(self):
        config=Path(self.ctx['CONFIG_HOME']);niri=config/'niri/config.kdl'
        niri.parent.mkdir(parents=True);niri.write_text('layout { fullscreen-backdrop-color "#00000000"; }\n')
        wrapper=Path(self.ctx['PROFILE_DATA'])/'bin'/portal.LAUNCHER
        items=[integrate.Resource(wrapper,portal.launcher(self.ctx,app.environment(self.ctx),self.backend),0o700)]
        dropin=config/f'systemd/user/{portal.UNIT}.d/50-niri-dms-theme.conf'
        foreign=dropin.parent/'90-user.conf';foreign.parent.mkdir(parents=True);foreign.write_text('[Service]\nRestart=no\n')
        with patch.object(integrate,'_services') as services:
            integrate.apply(self.ctx,items,app.environment(self.ctx),live=False)
            self.assertTrue(wrapper.is_file());self.assertTrue(dropin.is_file())
            self.assertIn(str(wrapper).replace('%','%%').replace('$','$$'),dropin.read_text())
            integrate.restore(self.ctx,live=False)
            self.assertTrue(all(call.args==(False,) for call in services.call_args_list))
        self.assertFalse(wrapper.exists());self.assertFalse(dropin.exists())
        self.assertEqual(foreign.read_text(),'[Service]\nRestart=no\n')
        self.assertIn('fullscreen-backdrop-color "#00000000"',niri.read_text())

    def test_no_backend_does_not_produce_portal_wrapper(self):
        with patch.object(portal,'find_backend',return_value=None):
            items=app.resources(self.ctx,'dark',names=())
        self.assertFalse(any(item.path.name==portal.LAUNCHER for item in items))


if __name__=='__main__':unittest.main()

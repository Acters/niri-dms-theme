# SPDX-License-Identifier: MIT
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from themekit import cli, session

ROOT=Path(__file__).resolve().parents[1]

class ProfileIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.work=tempfile.TemporaryDirectory(prefix='theme-profile-integration-')
        self.root=Path(self.work.name)
        self.home=self.root/'home with spaces'
        self.ctx=cli.context(self.home)
        self.manifest=cli.load_manifest(ROOT)
    def tearDown(self): self.work.cleanup()
    def plan(self):
        # Native binaries are checked separately; do not fake or load them in Python tests.
        manifest=dict(self.manifest)
        manifest['files']=[s for s in manifest['files'] if not s['source'].startswith('build/')]
        return cli.make_plan(ROOT,manifest,self.ctx,'light')
    def apply(self):
        with contextlib.redirect_stdout(io.StringIO()): cli.install(self.plan(),self.ctx,True)
    def test_environmentfile_and_session_parser_agree(self):
        self.apply()
        env=session.parse_env_file(Path(self.ctx['PROFILE_CONFIG'])/'session.env')
        self.assertEqual(env['NIRI_DMS_THEME_PROFILE'],'niri-dms-glass')
        self.assertEqual(env['QT_PLUGIN_PATH'],self.ctx['PLUGIN_ROOT'])
        self.assertTrue(env['XDG_CONFIG_DIRS'].startswith(str(Path(self.ctx['PROFILE_CONFIG'])/'shared')))
        self.assertNotIn('export ',(Path(self.ctx['PROFILE_CONFIG'])/'session.env').read_text())
        q=json.loads((Path(self.ctx['PROFILE_CONFIG'])/'qtengine.json').read_text())
        self.assertTrue(Path(q['theme']['colorScheme']).is_file())
    def test_default_units_do_not_import_manager_environment(self):
        for name in ('niri.service.conf.in','dms.service.conf.in'):
            text=(ROOT/'session'/name).read_text()
            self.assertIn('EnvironmentFile=',text)
            self.assertNotIn('ExecStartPost=',text)
            self.assertNotIn('manager-enter',text)
    def test_installed_helper_exec_is_process_local_and_rejects_other_desktop(self):
        self.apply()
        helper=Path(self.ctx['PROFILE_DATA'])/'bin/theme-session'
        envfile=Path(self.ctx['PROFILE_CONFIG'])/'session.env'
        env=os.environ.copy(); env['XDG_CURRENT_DESKTOP']='niri'
        code='import os; print(os.environ["NIRI_DMS_THEME_PROFILE"])'
        result=subprocess.run([str(helper),'exec','--env-file',str(envfile),'--',sys.executable,'-c',code],env=env,cwd='/tmp',text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'niri-dms-glass')
        env['XDG_CURRENT_DESKTOP']='COSMIC'
        result=subprocess.run([str(helper),'exec','--env-file',str(envfile),'--',sys.executable,'-c',code],env=env,cwd='/tmp',text=True,capture_output=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('include niri',result.stderr)
    def test_drawy_wrapper_falls_back_outside_profile_and_isolates_inside(self):
        # Substitute a recording executable into a temporary copy, never run real Drawy.
        stub=self.root/'drawy-stub'
        stub.write_text('#!'+sys.executable+'\nimport json,os\nprint(json.dumps({k:os.environ.get(k) for k in ("XDG_CONFIG_HOME","XDG_DATA_HOME","QT_STYLE_OVERRIDE")}))\n')
        stub.chmod(0o700)
        wrapper=self.root/'wrapper'
        wrapper.write_text((ROOT/'assets/drawy/drawy-glass').read_text().replace('/usr/bin/drawy',str(stub)))
        wrapper.chmod(0o700)
        env=os.environ.copy()
        env.update(XDG_CURRENT_DESKTOP='COSMIC',NIRI_DMS_THEME_PROFILE='niri-dms-glass',XDG_CONFIG_HOME=str(self.home/'original config'),XDG_DATA_HOME=str(self.home/'original data'),QT_STYLE_OVERRIDE='NativeStyle')
        result=subprocess.run([str(wrapper)],env=env,text=True,capture_output=True,check=True)
        self.assertEqual(json.loads(result.stdout)['QT_STYLE_OVERRIDE'],'NativeStyle')
        env.update(XDG_CURRENT_DESKTOP='niri',NIRI_DMS_THEME_CONFIG_HOME=self.ctx['PROFILE_CONFIG'],NIRI_DMS_THEME_DATA_HOME=self.ctx['PROFILE_DATA'],XDG_CACHE_HOME=self.ctx['CACHE_HOME'],XDG_STATE_HOME=self.ctx['STATE_HOME'])
        result=subprocess.run([str(wrapper)],env=env,text=True,capture_output=True,check=True)
        data=json.loads(result.stdout)
        self.assertEqual(data['QT_STYLE_OVERRIDE'],'DrawyGlass')
        self.assertEqual(data['XDG_CONFIG_HOME'],str(Path(self.ctx['PROFILE_CONFIG'])/'apps/drawy'))
        self.assertEqual(data['XDG_DATA_HOME'],str(Path(self.ctx['PROFILE_DATA'])/'apps/drawy/data'))

if __name__=='__main__': unittest.main()

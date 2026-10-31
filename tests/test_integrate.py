"""Integration tests use only temporary homes and a fake service manager."""
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch, Mock

from themekit.integrate import Error, Resource, apply, restore


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='niri-integrate-')
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name)
        self.ctx = {'HOME': str(home)}
        for key, suffix in [('CONFIG_HOME', '.config'), ('DATA_HOME', '.local/share'),
                            ('STATE_HOME', '.local/state'), ('CACHE_HOME', '.cache')]:
            self.ctx[key] = str(home / suffix)
        for key, value in [('PROFILE_CONFIG', Path(self.ctx['CONFIG_HOME']) / 'niri-dms-theme'),
                           ('PROFILE_DATA', Path(self.ctx['DATA_HOME']) / 'niri-dms-theme')]:
            self.ctx[key] = str(value)
        self.ctx['PLUGIN_ROOT'] = str(Path(self.ctx['PROFILE_DATA']) / 'qt-plugins')
        self.ctx['PROFILE_SHARE'] = str(Path(self.ctx['PROFILE_DATA']) / 'share')
        self.config = Path(self.ctx['CONFIG_HOME'])
        self.niri = self.put('niri/config.kdl', '// input and rules stay mine\ninput { keyboard { xkb { layout "us"; }; }; }\nenvironment {\n    GPU "keep"\n    QT_QPA_PLATFORMTHEME "native" // original\n}\nbinds { Mod+Q { close-window; }; }\n')
        self.env = {'QT_QPA_PLATFORMTHEME': 'qtengine', 'NIRI_DMS_THEME_PROFILE': 'niri-dms-glass'}
        self.asset = Path(self.ctx['PROFILE_CONFIG']) / 'qtengine.json'
        self.envpath = Path(self.ctx['PROFILE_CONFIG']) / 'niri/environment.kdl'
        self.resources = [Resource(self.asset, b'{"theme":"glass"}\n')]
        self.manager = patch('themekit.integrate.subprocess.run', side_effect=AssertionError('real manager boundary'))
        self.manager.start()
        self.addCleanup(self.manager.stop)

    def put(self, name, text):
        path = self.config / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def install(self, **kw):
        return apply(self.ctx, self.resources, self.env, **kw)

    def test_environment_file_uses_systemd_path_not_shell_quotes(self):
        self.ctx['PROFILE_CONFIG'] = str(self.config / 'theme with spaces')
        self.asset = Path(self.ctx['PROFILE_CONFIG']) / 'qtengine.json'
        self.resources = [Resource(self.asset, b'{}\n')]
        self.install()
        expected = 'EnvironmentFile=' + str(Path(self.ctx['PROFILE_CONFIG']) / 'session.env') + '\n'
        for unit in ('niri', 'dms'):
            dropin = self.config / f'systemd/user/{unit}.service.d/50-niri-dms-theme.conf'
            self.assertIn(expected, dropin.read_text())
            self.assertNotIn('EnvironmentFile="', dropin.read_text())

    def test_reinstall_adds_material_include_and_keeps_original_restore_baseline(self):
        material = Path(self.ctx['PROFILE_CONFIG']) / 'niri/material.kdl'
        for ending in ('', '\n'):
            with self.subTest(ending=repr(ending)):
                original = 'environment { GPU "keep"; }' + ending
                self.niri.write_text(original)
                self.install()
                self.assertNotIn(str(material), self.niri.read_text())
                self.resources.append(Resource(material, b'// scoped material rules\n'))
                self.install()
                self.assertIn('include ' + json.dumps(str(material)), self.niri.read_text())
                self.assertEqual(self.niri.read_text().count('// BEGIN niri-dms-theme'), 1)
                self.install()
                restore(self.ctx)
                self.assertEqual(self.niri.read_text(), original)
                self.assertFalse(material.exists())
                self.resources.pop()

    def test_fresh_kate_is_enabled_and_reinstall_keeps_drawy_preferences(self):
        drawy = Path(self.ctx['PROFILE_CONFIG']) / 'apps/drawy/drawyrc'
        self.resources.append(Resource(drawy, b'[Canvas]\nBackgroundColorDark=0,0,0,128\n'))
        self.install()
        anonymous = Path(self.ctx['DATA_HOME']) / 'kate/anonymous.katesession'
        self.assertIn('katebalancedglassplugin=true', anonymous.read_text())
        edited = drawy.read_text() + '\n[Properties]\nStrokeWidth=9\n'
        drawy.write_text(edited)
        self.install()
        self.assertEqual(drawy.read_text(), edited)
        self.asset.unlink()
        self.install()
        self.assertEqual(self.asset.read_bytes(), b'{"theme":"glass"}\n')

    def test_restore_without_backup_is_noop_even_live(self):
        original = self.niri.read_bytes()
        self.assertEqual(restore(self.ctx, live=True), [])
        self.assertEqual(restore(self.ctx, dry_run=True, live=True), [])
        self.assertEqual(self.niri.read_bytes(), original)
        self.assertFalse(Path(self.ctx['STATE_HOME']).exists())

    def test_dry_run_and_missing_niri(self):
        self.install(dry_run=True)
        self.assertFalse(self.asset.exists())
        self.assertFalse(Path(self.ctx['STATE_HOME']).exists())
        self.niri.unlink()
        with self.assertRaisesRegex(Error, 'missing Niri config'):
            self.install()
        self.assertFalse(self.asset.exists())

    def test_activation_and_private_baseline(self):
        dms = self.put('dms/settings.json', '{"wallpaper":"mine","matugenTemplateQtengine":true}')
        original = self.niri.read_text()
        self.install()
        text = self.niri.read_text()
        self.assertIn('GPU "keep"', text)
        self.assertIn('binds { Mod+Q', text)
        self.assertIn('include ' + json.dumps(str(self.envpath)), text)
        self.assertIn('"QT_QPA_PLATFORMTHEME" "qtengine"', self.envpath.read_text())
        self.assertTrue(text.startswith(original))
        settings = json.loads(dms.read_text())
        self.assertEqual(settings['wallpaper'], 'mine')
        self.assertFalse(settings['matugenTemplateQtengine'])
        self.assertEqual(settings['currentThemeName'], 'custom')
        backup = Path(self.ctx['STATE_HOME']) / 'niri-dms-theme/backup.json'
        baseline = backup.read_bytes()
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(backup.parent.stat().st_mode), 0o700)
        self.assertEqual(self.install(), [])
        self.assertEqual(backup.read_bytes(), baseline)
        self.assertTrue((self.config / 'matugen/dms/configs/niri-dms-theme.toml').is_file())
        for unit in ('niri', 'dms'):
            dropin = self.config / f'systemd/user/{unit}.service.d/50-niri-dms-theme.conf'
            self.assertIn(str(Path(self.ctx['PROFILE_CONFIG']) / 'session.env'), dropin.read_text())
            self.assertNotIn('import-environment', dropin.read_text())
        restore(self.ctx)
        self.assertIn('QT_QPA_PLATFORMTHEME "native" // original', self.niri.read_text())
        self.assertEqual(self.niri.read_text(), original)
        self.assertEqual(json.loads(dms.read_text()), {'wallpaper': 'mine', 'matugenTemplateQtengine': True})
        self.assertFalse(self.asset.exists())
        self.assertFalse(backup.exists())

    def test_restore_preserves_gui_changes_and_session_data(self):
        kate = Path(self.ctx['DATA_HOME']) / 'kate/anonymous.katesession'
        named = kate.parent / 'sessions/Private.katesession'
        named.parent.mkdir(parents=True)
        kate.write_text('[Kate Plugins]\nother=true\nkatebalancedglassplugin=false\n[View]\ncursor=4\n')
        named.write_text('[View]\nlayout=mine\n')
        dms = self.put('dms/settings.json', '{"wallpaper":"before"}')
        self.install()
        self.assertIn('katebalancedglassplugin=true', named.read_text())
        kate.write_text(kate.read_text().replace('cursor=4', 'cursor=99') + 'layout=new\n')
        settings = json.loads(dms.read_text())
        settings['wallpaper'] = 'after'
        settings['volume'] = 51
        dms.write_text(json.dumps(settings))
        self.niri.write_text(self.niri.read_text().replace('GPU "keep"', 'GPU "new"') + 'window-rule { opacity 0.9; }\n')
        restore(self.ctx)
        self.assertIn('cursor=99', kate.read_text())
        self.assertIn('layout=new', kate.read_text())
        self.assertIn('katebalancedglassplugin=false', kate.read_text())
        self.assertNotIn('katebalancedglassplugin', named.read_text())
        self.assertIn('layout=mine', named.read_text())
        self.assertEqual(json.loads(dms.read_text()), {'wallpaper': 'after', 'volume': 51})
        self.assertIn('GPU "new"', self.niri.read_text())
        self.assertIn('window-rule', self.niri.read_text())

    def test_exact_legacy_cleanup_preserves_gpu_hooks_and_other_values(self):
        legacy = self.put('environment.d/95-qt-style.conf', 'QT_QPA_PLATFORMTHEME=qtengine\nQT_STYLE_OVERRIDE=CustomStyle\nFOO=bar\n')
        second = self.put('environment.d/96-kate-balanced-glass.conf', f'QT_PLUGIN_PATH={self.ctx["HOME"]}/.local/lib/qt6/plugins\nQT_PLUGIN_PATH=/other/plugins\n')
        override = self.put('systemd/user/niri.service.d/override.conf', '[Service]\nEnvironment=GPU=mine\nExecStartPre=/usr/bin/systemctl --user set-environment QT_QPA_PLATFORMTHEME=qtengine\nExecStopPost=/usr/bin/systemctl --user unset-environment QT_PLUGIN_PATH=old\nExecStartPre=/usr/bin/gpu-helper\nExecStartPost=/usr/bin/systemctl --user import-environment DISPLAY\n')
        self.install()
        self.assertEqual(legacy.read_text(), 'QT_STYLE_OVERRIDE=CustomStyle\nFOO=bar\n')
        self.assertEqual(second.read_text(), 'QT_PLUGIN_PATH=/other/plugins\n')
        self.assertNotIn('QT_QPA_PLATFORMTHEME=qtengine', override.read_text())
        self.assertNotIn('unset-environment', override.read_text())
        self.assertIn('GPU=mine', override.read_text())
        self.assertIn('gpu-helper', override.read_text())
        self.assertIn('import-environment DISPLAY', override.read_text())
        legacy.write_text(legacy.read_text() + 'NEW=keep\n')
        restore(self.ctx)
        self.assertIn('NEW=keep', legacy.read_text())
        self.assertIn('QT_QPA_PLATFORMTHEME=qtengine', legacy.read_text())

    def test_asset_drift_preflight_and_generated_palette(self):
        palette = Path(self.ctx['PROFILE_DATA']) / 'generated/palette.colors'
        self.resources.append(Resource(palette, b'first', generated=True))
        drawing = Path(self.ctx['PROFILE_DATA']) / 'apps/drawy/data/drawing.svg'
        drawing.parent.mkdir(parents=True)
        drawing.write_bytes(b'private drawing')
        self.install()
        palette.write_bytes(b'normal matugen update')
        self.asset.write_bytes(b'user edit')
        with self.assertWarnsRegex(RuntimeWarning, 'preserving modified asset'):
            restore(self.ctx)
        self.assertNotIn('BEGIN niri-dms-theme', self.niri.read_text())
        self.assertFalse(self.envpath.exists())
        self.assertEqual(self.asset.read_bytes(), b'user edit')
        backup = Path(self.ctx['STATE_HOME']) / 'niri-dms-theme/backup.json'
        self.assertTrue(backup.exists())
        self.asset.write_bytes(self.resources[0].data)
        restore(self.ctx)
        self.assertFalse(backup.exists())
        self.assertFalse(palette.exists())
        self.assertEqual(drawing.read_bytes(), b'private drawing')

    def test_resource_mode_and_original_asset_restored(self):
        self.asset.parent.mkdir(parents=True)
        self.asset.write_bytes(b'original')
        self.asset.chmod(0o644)
        self.resources[0].mode = 0o700
        self.install()
        self.assertEqual(stat.S_IMODE(self.asset.stat().st_mode), 0o700)
        restore(self.ctx)
        self.assertEqual(self.asset.read_bytes(), b'original')
        self.assertEqual(stat.S_IMODE(self.asset.stat().st_mode), 0o644)

    def test_symlink_rejected_before_any_write(self):
        self.asset.parent.mkdir(parents=True)
        target = Path(self.tmp.name) / 'victim'
        target.write_text('untouched')
        self.asset.symlink_to(target)
        with self.assertRaisesRegex(Error, 'symlink'):
            self.install()
        self.assertEqual(target.read_text(), 'untouched')
        self.assertFalse(Path(self.ctx['STATE_HOME']).exists())

    def test_exact_include_marker_is_required_before_removing_environment(self):
        self.niri.write_text('environment {}\nenvironment {}\n')
        original = self.niri.read_text()
        self.install()
        self.assertTrue(self.niri.read_text().startswith(original))
        self.niri.write_text(self.niri.read_text().replace('include ', 'include "other.kdl"; include ', 1))
        with self.assertRaisesRegex(Error, 'modified.*include block'):
            restore(self.ctx)
        self.assertTrue(self.envpath.exists())
        self.assertTrue(self.asset.exists())
        self.niri.write_text(self.niri.read_text().replace('include "other.kdl"; include ', 'include ', 1))
        restore(self.ctx)
        self.assertEqual(self.niri.read_text(), original)

    def test_json_null_baseline_and_complex_kdl_comments(self):
        dms = self.put('dms/settings.json', '{"customThemeFile":null}')
        self.niri.write_text('/* outer /* environment { } */ still comment */\n/- environment { FOO "disabled"; }\ninput { name r#"raw " } environment {"#; }\n"environment" {\n GPU "mine"\n}\n')
        self.install()
        self.assertIn('"QT_QPA_PLATFORMTHEME" "qtengine"', self.envpath.read_text())
        restore(self.ctx)
        self.assertEqual(json.loads(dms.read_text()), {'customThemeFile': None})

    def test_restore_preserves_user_changes_to_owned_keys_and_drawy_config(self):
        dms = self.put('dms/settings.json', '{"customThemeFile":"before"}')
        kate = Path(self.ctx['DATA_HOME']) / 'kate/anonymous.katesession'
        kate.parent.mkdir(parents=True)
        kate.write_text('[Kate Plugins]\nother=true\n')
        drawy = Path(self.ctx['PROFILE_CONFIG']) / 'apps/drawy/drawyrc'
        self.resources.append(Resource(drawy, b'[General]\nzoom=1\n'))
        self.install()
        settings = json.loads(dms.read_text())
        settings['customThemeFile'] = 'user-selected-theme'
        dms.write_text(json.dumps(settings))
        kate.write_text(kate.read_text().replace('katebalancedglassplugin=true', 'katebalancedglassplugin=false'))
        drawy.write_bytes(b'[General]\nzoom=2\n')
        with self.assertWarns(RuntimeWarning):
            restore(self.ctx)
        self.assertEqual(json.loads(dms.read_text()), {'customThemeFile': 'user-selected-theme'})
        self.assertIn('katebalancedglassplugin=false', kate.read_text())
        self.assertEqual(drawy.read_bytes(), b'[General]\nzoom=2\n')
        self.assertNotIn('BEGIN niri-dms-theme', self.niri.read_text())
        self.assertFalse(self.envpath.exists())
        self.assertFalse((self.config / 'systemd/user/niri.service.d/50-niri-dms-theme.conf').exists())
        self.assertTrue((Path(self.ctx['STATE_HOME']) / 'niri-dms-theme/backup.json').exists())

    def test_live_exact_legacy_manager_cleanup_and_ownership_restore(self):
        self.manager.stop()
        oldpath = self.ctx['HOME'] + '/.local/lib/qt6/plugins'
        values = {'QT_QPA_PLATFORMTHEME': 'qtengine', 'QT_QPA_PLATFORMTHEME_QT6': 'native',
                  'QT_PLUGIN_PATH': oldpath, 'QT_STYLE_OVERRIDE': 'Custom', 'DISPLAY': ':5'}
        calls = []
        def manager(command, **kwargs):
            calls.append(command)
            action = command[2]
            if action == 'show-environment':
                return Mock(returncode=0, stdout=''.join(k + '=' + v + '\n' for k, v in values.items()))
            if action == 'unset-environment':
                for name in command[3:]:
                    self.assertNotIn('=', name)
                    values.pop(name)
            if action == 'set-environment':
                for entry in command[3:]:
                    key, value = entry.split('=', 1)
                    values[key] = value
            return Mock(returncode=0)
        with patch('themekit.integrate.subprocess.run', side_effect=manager):
            self.install(live=True)
            self.assertNotIn('QT_PLUGIN_PATH', values)
            self.assertNotIn('QT_QPA_PLATFORMTHEME', values)
            self.assertEqual(values['QT_QPA_PLATFORMTHEME_QT6'], 'native')
            self.assertEqual(values['QT_STYLE_OVERRIDE'], 'Custom')
            values['QT_QPA_PLATFORMTHEME'] = 'new-owner'
            restore(self.ctx, live=True)
            self.assertEqual(values['QT_QPA_PLATFORMTHEME'], 'new-owner')
            self.assertEqual(values['QT_PLUGIN_PATH'], oldpath)
        self.assertFalse(any('dbus' in ' '.join(c) or 'import-environment' in c for c in calls))

    def test_known_kde_style_only_and_reinstall_new_env_key(self):
        kde = self.put('kdeglobals', '[KDE]\nwidgetStyle=Darkly\nother=keep\n[General]\nColorScheme=Personal\n')
        self.install()
        self.assertNotIn('widgetStyle=', kde.read_text())
        self.assertIn('ColorScheme=Personal', kde.read_text())
        self.env['NEW_PROFILE_KEY'] = 'value'
        self.install()
        kde.write_text(kde.read_text().replace('other=keep', 'other=new'))
        restore(self.ctx)
        self.assertIn('widgetStyle=Darkly', kde.read_text())
        self.assertIn('other=new', kde.read_text())
        self.assertIn('ColorScheme=Personal', kde.read_text())
        self.assertNotIn('NEW_PROFILE_KEY', self.niri.read_text())
        kde.write_text('[KDE]\nwidgetStyle=Breeze\n')
        self.install()
        self.assertEqual(kde.read_text(), '[KDE]\nwidgetStyle=Breeze\n')

    def test_no_final_newline_and_environment_block_comment(self):
        self.niri.write_text('environment {\n/*\nQT_QPA_PLATFORMTHEME "comment only"\n*/\nGPU "mine"}')
        kate = Path(self.ctx['DATA_HOME']) / 'kate/anonymous.katesession'
        kate.parent.mkdir(parents=True)
        kate.write_text('[Kate Plugins]\nother=true')
        self.install()
        self.assertIn('GPU "mine"}', self.niri.read_text())
        self.assertIn('QT_QPA_PLATFORMTHEME "comment only"', self.niri.read_text())
        self.assertIn('other=true\nkatebalancedglassplugin=true', kate.read_text())
        restore(self.ctx)
        self.assertIn('QT_QPA_PLATFORMTHEME "comment only"', self.niri.read_text())

    def test_interrupted_install_keeps_recoverable_backup(self):
        import themekit.integrate as integration
        write = integration._write
        calls = 0
        def failing_write(*args):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError('fake disk failure')
            return write(*args)
        with patch('themekit.integrate._write', side_effect=failing_write):
            with self.assertRaisesRegex(Error, 'run restore'):
                self.install()
        with self.assertRaisesRegex(Error, 'interrupted install'):
            self.install()
        restore(self.ctx, dry_run=True, live=True)
        restore(self.ctx)
        self.assertFalse(self.asset.exists())
        self.assertIn('QT_QPA_PLATFORMTHEME "native"', self.niri.read_text())

    def test_live_reloads_and_restarts_only_active_dms(self):
        self.manager.stop()
        with patch('themekit.integrate.subprocess.run', return_value=Mock(returncode=0, stdout='')) as run:
            self.install(live=True)
            self.assertEqual([c.args[0] for c in run.call_args_list], [
                ['systemctl', '--user', 'show-environment'],
                ['systemctl', '--user', 'daemon-reload'],
                ['systemctl', '--user', 'is-active', '--quiet', 'dms.service'],
                ['systemctl', '--user', 'restart', 'dms.service']])
        with patch('themekit.integrate.subprocess.run', return_value=Mock(returncode=3)) as run:
            restore(self.ctx, live=True)
            self.assertEqual(len(run.call_args_list), 2)


if __name__ == '__main__':
    unittest.main()

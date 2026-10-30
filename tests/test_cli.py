"""Pure stdlib tests: all deployment writes are confined to temporary homes."""
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock

from themekit import cli


class CLITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="themekit test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repository space"
        self.repo.mkdir()
        self.home = self.root / "home space"
        self.source = self.repo / "asset.txt"
        self.source.write_text("Hello @HOME@\n", encoding="utf-8")
        self.manifest = {"schema": 1, "id": "niri-dms-glass", "files": [
            {"source": "asset.txt", "target": "@PROFILE_CONFIG@/nested/asset.txt", "render": True}],
            "environment": {"TEST_HOME": "@HOME@", "XDG_DATA_DIRS": "@MERGED_DATA_DIRS@"}}
        self.target = self.home / ".config/niri-dms-theme/nested/asset.txt"

    def run_cli(self, command, *args):
        (self.repo / "profile.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = cli.main([command, "--repo", str(self.repo), "--home", str(self.home), *args])
        return result, output.getvalue()

    def test_dryrun_writes_nothing(self):
        code, output = self.run_cli("install")
        self.assertEqual(code, 0, output)
        self.assertIn("Dry-run", output)
        self.assertFalse(self.home.exists())

    def test_explicit_home_ignores_all_ambient_xdg(self):
        environ = {"XDG_" + key: str(self.root / "unsafe" / key) for key in
                   ("CONFIG_HOME", "DATA_HOME", "STATE_HOME", "CACHE_HOME", "DATA_DIRS", "CONFIG_DIRS")}
        with mock.patch.dict(os.environ, environ):
            ctx = cli.context(self.home)
            self.assertEqual(ctx["CACHE_HOME"], str(self.home / ".cache"))
            self.assertEqual(ctx["MERGED_CONFIG_DIRS"], str(self.home / ".config/niri-dms-theme/shared") + ":/etc/xdg")
            self.assertEqual(ctx["MERGED_DATA_DIRS"], str(self.home / ".local/share/niri-dms-theme/share") + ":/usr/local/share:/usr/share")
            code, output = self.run_cli("install", "--apply")
        self.assertEqual(code, 0, output)
        self.assertTrue(self.target.is_file())
        self.assertFalse((self.root / "unsafe").exists())

    def test_default_home_honors_xdg_and_deduplicates(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root / "custom"),
                                        "XDG_DATA_DIRS": "/usr/share:/usr/share:/opt/share",
                                        "XDG_CONFIG_DIRS": "/etc/xdg:/etc/xdg:/opt/config"}):
            ctx = cli.context()
        self.assertEqual(ctx["CONFIG_HOME"], str(self.root / "custom"))
        self.assertEqual(ctx["MERGED_CONFIG_DIRS"], str(self.root / "custom/niri-dms-theme/shared") + ":/etc/xdg:/opt/config")
        self.assertEqual(ctx["MERGED_DATA_DIRS"].split(":" )[-2:], ["/usr/share", "/opt/share"])

    def test_idempotence_private_modes_and_rollback_created(self):
        code, output = self.run_cli("install", "--apply")
        self.assertEqual(code, 0, output)
        state = self.home / ".local/state/niri-dms-theme/transactions.json"
        original_state = state.read_bytes()
        timestamp = self.target.stat().st_mtime_ns
        code, output = self.run_cli("install", "--apply")
        self.assertEqual(code, 0, output)
        self.assertIn("0 changed", output)
        self.assertEqual(timestamp, self.target.stat().st_mtime_ns)
        self.assertEqual(original_state, state.read_bytes())
        self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.target.parent.stat().st_mode), 0o700)
        self.assertIn(str(self.home), self.target.read_text())
        self.assertEqual(self.run_cli("rollback")[0], 0)
        self.assertTrue(self.target.exists())
        self.assertEqual(self.run_cli("rollback", "--apply")[0], 0)
        self.assertFalse(self.target.exists())

    def test_backup_restores_bytes_and_permissions(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"original\x00bytes")
        self.target.chmod(0o640)
        self.assertEqual(self.run_cli("install", "--apply")[0], 0)
        self.assertEqual(self.run_cli("rollback", "--apply")[0], 0)
        self.assertEqual(self.target.read_bytes(), b"original\x00bytes")
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o640)

    def test_rollback_refuses_drift_without_partial_restore(self):
        self.assertEqual(self.run_cli("install", "--apply")[0], 0)
        self.target.write_text("user modification")
        code, output = self.run_cli("rollback", "--apply")
        self.assertEqual(code, 1)
        self.assertIn("drift", output)
        self.assertTrue((self.home / ".config/niri-dms-theme/session.env").exists())
        self.assertEqual(self.target.read_text(), "user modification")

    def test_rejects_target_escape_traversal_and_unresolved_tokens(self):
        for target in ("@CONFIG_HOME@/niri/config.kdl", "@PROFILE_CONFIG@/../escape", "@UNKNOWN@/x"):
            with self.subTest(target=target):
                self.manifest["files"][0]["target"] = target
                self.assertEqual(self.run_cli("install", "--apply")[0], 1)
                self.assertFalse(self.home.exists())

    def test_rejects_source_escape(self):
        outside = self.root / "outside.txt"
        outside.write_text("outside")
        (self.repo / "link.txt").symlink_to(outside)
        for source in ("../outside.txt", str(outside), "link.txt"):
            self.manifest["files"][0]["source"] = source
            self.assertEqual(self.run_cli("install", "--apply")[0], 1)
            self.assertFalse(self.home.exists())

    def test_rejects_symlink_parent_and_nonregular_target(self):
        outside = self.root / "outside"
        outside.mkdir()
        profile = self.home / ".config/niri-dms-theme"
        profile.parent.mkdir(parents=True)
        profile.symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.run_cli("install", "--apply")[0], 1)
        self.assertEqual(list(outside.iterdir()), [])
        profile.unlink()
        self.target.mkdir(parents=True)
        self.assertEqual(self.run_cli("install", "--apply")[0], 1)
        self.assertFalse((profile / "session.env").exists())

    def test_rollback_rejects_symlink(self):
        self.assertEqual(self.run_cli("install", "--apply")[0], 0)
        original = self.target.read_bytes()
        outside = self.root / "outside"
        outside.write_bytes(original)
        self.target.unlink()
        self.target.symlink_to(outside)
        self.assertEqual(self.run_cli("rollback", "--apply")[0], 1)
        self.assertEqual(outside.read_bytes(), original)

    def test_missing_build_output_plan_and_apply(self):
        self.manifest["files"][0]["source"] = "build/plugin.so"
        self.assertEqual(self.run_cli("plan")[0], 0)
        self.assertIn("MISSING", self.run_cli("plan")[1])
        self.assertEqual(self.run_cli("install")[0], 0)
        self.assertEqual(self.run_cli("install", "--apply")[0], 1)
        self.assertFalse(self.home.exists())

    def test_environment_escaping_and_newline_rejection(self):
        self.manifest["environment"]["SPECIAL"] = 'a "$`\\ value'
        code, output = self.run_cli("install", "--apply")
        self.assertEqual(code, 0, output)
        env = (self.home / ".config/niri-dms-theme/session.env").read_text()
        self.assertIn('SPECIAL="a \\"$`\\\\ value"', env)
        self.assertNotIn("export ", env)
        import shlex
        assignment = next(line for line in env.splitlines() if line.startswith("SPECIAL="))
        self.assertEqual(shlex.split(assignment)[0], 'SPECIAL=a "$`\\ value')
        kdl = (self.home / ".config/niri-dms-theme/niri/environment.kdl").read_text()
        self.assertIn(json.dumps('a "$`\\ value'), kdl)
        self.manifest["environment"]["SPECIAL"] = "bad\nvalue"
        self.assertEqual(self.run_cli("install", "--apply")[0], 1)

    def test_optional_palette_contract(self):
        (self.repo / "theme.json").write_text('{"color": "blue"}')
        (self.repo / "template.txt").write_text("template")
        self.manifest["palette"] = {"theme_source": "theme.json", "template_source": "template.txt",
                                    "target": "@PROFILE_CONFIG@/palette.kdl"}
        fake = types.ModuleType("themekit.palette")
        fake.render_palette = mock.Mock(return_value="rendered palette")
        with mock.patch.dict(sys.modules, {"themekit.palette": fake}):
            code, output = self.run_cli("install", "--apply", "--mode", "light")
        self.assertEqual(code, 0, output)
        fake.render_palette.assert_called_once_with({"color": "blue"}, "template", mode="light")
        self.assertEqual((self.home / ".config/niri-dms-theme/palette.kdl").read_text(), "rendered palette")

    def test_build_commands_and_preflight(self):
        (self.repo / "src").mkdir()
        self.manifest["builds"] = [{"name": "plugin", "source": "src", "build_dir": "build/plugin",
                                    "artifact": "build/plugin/plugin.so"}]
        with mock.patch.object(cli.subprocess, "run") as run:
            self.assertEqual(self.run_cli("build")[0], 0)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args_list[0].args[0], ["cmake", "-S", str(self.repo / "src"), "-B",
                             str(self.repo / "build/plugin"), "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release"])
            self.assertEqual(run.call_args_list[1].args[0][-1], "-j2")
            self.manifest["builds"][0]["build_dir"] = "outside"
            run.reset_mock()
            self.assertEqual(self.run_cli("build")[0], 1)
            run.assert_not_called()

    def test_state_symlink_refused_before_deploy(self):
        state = self.home / ".local/state/niri-dms-theme"
        state.parent.mkdir(parents=True)
        outside = self.root / "outside"
        outside.mkdir()
        state.symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.run_cli("install", "--apply")[0], 1)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(outside.iterdir()), [])

    def test_failed_write_restores_prior_files(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_text("original")
        writer = cli.atomic_write

        def fail_environment(path, content, mode):
            if path.name == "session.env":
                raise OSError("simulated failure")
            return writer(path, content, mode)

        with mock.patch.object(cli, "atomic_write", side_effect=fail_environment):
            code, output = self.run_cli("install", "--apply")
        self.assertEqual(code, 1, output)
        self.assertEqual(self.target.read_text(), "original")
        state = self.home / ".local/state/niri-dms-theme/transactions.json"
        self.assertEqual(json.loads(state.read_text()), [])

    def test_interrupted_install_recovers_from_persisted_backups(self):
        writer = cli.atomic_write

        def interrupt_environment(path, content, mode):
            if path.name == "session.env":
                raise KeyboardInterrupt()
            return writer(path, content, mode)

        with mock.patch.object(cli, "atomic_write", side_effect=interrupt_environment):
            with self.assertRaises(KeyboardInterrupt):
                self.run_cli("install", "--apply")
        self.assertTrue(self.target.exists())
        self.assertEqual(self.run_cli("install", "--apply")[0], 1)
        code, output = self.run_cli("rollback", "--apply")
        self.assertEqual(code, 0, output)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.run_cli("install", "--apply")[0], 0)

    def test_doctor_warns_on_legacy_without_mutating(self):
        config = self.home / ".config"
        files = {
            "environment.d/95-qt-style.conf": 'QT_STYLE_OVERRIDE="darkly"\n',
            "systemd/user/niri.service.d/override.conf": '[Service]\nExecStopPost=/usr/bin/systemctl --user unset-environment QT_QPA_PLATFORMTHEME=qtengine\nExecStartPost=%h/.local/bin/kate-theme-helper\n',
            "kdeglobals": '[KDE]\nwidgetStyle=darkly\n[General]\nColorScheme=DankMatugenDark\nkey:with:colons=100% literal\n',
        }
        for name, text in files.items():
            path = config / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        helper = self.home / ".local/share/kate-balanced-glass/plugin/balancedglassplugin.cpp"
        helper.parent.mkdir(parents=True)
        helper.write_text("// old helper")
        before = {name: (config / name).read_bytes() for name in files}
        with mock.patch.object(cli.shutil, "which", return_value="/fake/bin"):
            code, output = self.run_cli("doctor")
        self.assertEqual(code, 0, output)
        for phrase in ("legacy userwide environment", "systemctl unset-environment NAME=value", "KDE/widgetStyle",
                       "General/ColorScheme=DankMatugen", "unconditional Kate"):
            self.assertIn(phrase, output)
        self.assertIn(str(helper), output)
        self.assertEqual(helper.read_text(), "// old helper")
        self.assertEqual(before, {name: (config / name).read_bytes() for name in files})
        self.assertFalse((config / "niri-dms-theme").exists())

    def test_doctor_unset_environment_native_directive_is_valid(self):
        override = self.home / ".config/systemd/user/niri.service.d/override.conf"
        override.parent.mkdir(parents=True)
        override.write_text('[Service]\nUnsetEnvironment=QT_STYLE_OVERRIDE=darkly\n'
                            'ExecStopPost=/usr/bin/systemctl --user unset-environment QT_STYLE_OVERRIDE\n'
                            '# ExecStopPost=/usr/bin/systemctl --user unset-environment IGNORED=value\n')
        with mock.patch.object(cli.shutil, "which", return_value="/fake/bin"):
            code, output = self.run_cli("doctor")
        self.assertEqual(code, 0, output)
        self.assertNotIn("NAME=value", output)
        self.assertNotIn("WARNING", output)

    def test_doctor_dankmatugen_light_and_quoted_unset_arguments(self):
        config = self.home / ".config"
        override = config / "systemd/user/niri.service.d/override.conf"
        override.parent.mkdir(parents=True)
        override.write_text('[Service]\nExecStopPost=-/usr/bin/systemctl --user unset-environment "QT_STYLE_OVERRIDE=darkly"\n')
        (config / "kdeglobals").write_text('[General]\nColorScheme=DankMatugenLight\n')
        with mock.patch.object(cli.shutil, "which", return_value="/fake/bin"):
            code, output = self.run_cli("doctor")
        self.assertEqual(code, 0, output)
        self.assertIn("systemctl unset-environment NAME=value", output)
        self.assertIn("General/ColorScheme=DankMatugen", output)

    def test_lazy_session_dispatch(self):
        fake = types.ModuleType("themekit.session")
        fake.main = mock.Mock(return_value=7)
        with mock.patch.dict(sys.modules, {"themekit.session": fake}):
            self.assertEqual(cli.main(["session", "--help"]), 7)
        fake.main.assert_called_once_with(["--help"])


if __name__ == "__main__":
    unittest.main()

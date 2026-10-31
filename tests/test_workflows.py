"""CLI workflows use temporary homes and fake modules, never the live desktop."""
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

from themekit import app
from themekit.paths import context

ROOT = Path(__file__).resolve().parents[1]


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="themekit-tests-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        shutil.copytree(ROOT / "assets", self.repo / "assets")
        for name, (_, _, artifact, _) in app.PLUGINS.items():
            target = self.repo / artifact
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((name + " fake module").encode())
        self.home = self.root / "home"
        self.repo_patch = patch.object(app, "REPO", self.repo)
        self.repo_patch.start()
        self.addCleanup(self.repo_patch.stop)
        self.backdrop_patch = patch.object(app, "backdrop", return_value=contextlib.nullcontext())
        self.backdrop_patch.start()
        self.addCleanup(self.backdrop_patch.stop)
        self.output = io.StringIO()
        self.capture = contextlib.redirect_stdout(self.output)
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)

    def seed_niri(self):
        niri = self.home / ".config/niri/config.kdl"
        niri.parent.mkdir(parents=True)
        niri.write_text('input { keyboard { xkb { layout "us"; }; }; }\n')

    def test_install_integrates_by_default_and_restore_preserves_foreign_data(self):
        self.seed_niri()
        preference = self.home / ".config/unrelated/preferences"
        preference.parent.mkdir(parents=True)
        preference.write_text("keep me")
        with patch.object(app.subprocess, "run") as run:
            self.assertEqual(app.main(["install", "--home", str(self.home), "--mode", "light"]), 0)
            run.assert_not_called()
        ctx = context(str(self.home))
        self.assertTrue((Path(ctx["PROFILE_CONFIG"]) / "session.env").is_file())
        self.assertTrue((self.home / ".config/niri/config.kdl").is_file())
        palette = Path(ctx["PROFILE_DATA"]) / "generated/DankMatugenTranslucent.colors"
        self.assertIn("237,246,255,26", palette.read_text())
        self.assertEqual(app.main(["restore", "--home", str(self.home)]), 0)
        self.assertEqual(preference.read_text(), "keep me")

    def test_install_restore_summaries_and_dry_run_paths(self):
        self.seed_niri()
        self.assertEqual(app.main(["install", "--home", str(self.home), "--mode", "dark"]), 0)
        ctx = context(str(self.home))
        backup = Path(ctx["STATE_HOME"]) / "niri-dms-theme/backup.json"
        self.assertIn("Installed:", self.output.getvalue())
        self.assertIn(str(backup), self.output.getvalue())
        self.assertIn("Reopen Kate, Dolphin and Drawy once", self.output.getvalue())
        self.assertIn("no live services changed", self.output.getvalue())
        self.output.seek(0)
        self.output.truncate()
        before = {p.relative_to(self.home): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        self.assertEqual(app.main(["restore", "--dry-run", "--home", str(self.home)]), 0)
        after = {p.relative_to(self.home): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertIn("Dry-run restore:", self.output.getvalue())
        self.assertIn(str(Path(ctx["PROFILE_CONFIG"]) / "session.env"), self.output.getvalue())
        self.output.seek(0)
        self.output.truncate()
        self.assertEqual(app.main(["restore", "--home", str(self.home)]), 0)
        self.assertIn("Restored:", self.output.getvalue())

    def test_restore_without_backup_reports_nothing_and_skips_services(self):
        for options in ([], ["--dry-run"]):
            with self.subTest(options=options), patch.object(app.integrate, "restore") as restore:
                self.assertEqual(app.main(["restore", "--home", str(self.home), *options]), 0)
                restore.assert_not_called()
        self.assertIn("Nothing to restore", self.output.getvalue())
        self.assertNotIn("Restored:", self.output.getvalue())
        self.assertFalse(self.home.exists())

    def test_executable_preview_command_launches_fake_kate_with_isolated_environment(self):
        package = self.repo / "themekit"
        package.mkdir()
        for filename in ("__init__.py", "app.py", "paths.py", "integrate.py", "palette.py", "preview.py"):
            shutil.copy2(ROOT / "themekit" / filename, package / filename)
        binaries = self.repo / "bin"
        binaries.mkdir()
        launcher = binaries / "themekit"
        shutil.copy2(ROOT / "bin/themekit", launcher)
        fake_kate = binaries / "kate"
        fake_kate.write_text(f"#!{sys.executable}\nimport json, os, sys\n"
                             "from pathlib import Path\n"
                             "Path(os.environ['HOME'], 'observed.json').write_text("
                             "json.dumps({'argv': sys.argv[1:], 'env': dict(os.environ)}))\n")
        fake_kate.chmod(0o700)
        env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ.get("PATH", ""),
                   PYTHONDONTWRITEBYTECODE="1", XDG_CONFIG_HOME="/foreign/config")
        env.pop("NIRI_SOCKET", None)
        result = subprocess.run([str(launcher), "preview", "kate", "--home", str(self.home),
                                 "--mode", "light"], env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads((self.home / "observed.json").read_text())
        sample = Path(context(str(self.home))["PROFILE_DATA"]) / "preview.cpp"
        self.assertEqual(observed["argv"], ["--desktopfile", "org.kde.kate.niri-glass-preview",
                                            "--block", "--new", "--startanon", str(sample)])
        self.assertIn("--block", observed["argv"])
        self.assertEqual(sample.read_bytes(), (self.repo / "assets/kate/preview.cpp").read_bytes())
        self.assertEqual(observed["env"]["HOME"], str(self.home))
        for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
            self.assertTrue(Path(observed["env"][key]).is_relative_to(self.home))
        self.assertEqual(observed["env"]["QT_QPA_PLATFORMTHEME"], "qtengine")
        self.assertIn("Preview ready", result.stdout)
        self.assertFalse((self.home / ".config/systemd").exists())

    def test_install_live_only_without_explicit_home(self):
        with patch.object(app.integrate, "apply") as apply:
            self.assertEqual(app.main(["install", "--mode", "dark", "--home", str(self.home)]), 0)
            self.assertFalse(apply.call_args.kwargs["live"])
            self.assertFalse(apply.call_args.kwargs["dry_run"])
            self.assertEqual(app.main(["install", "--mode", "dark"]), 0)
            self.assertTrue(apply.call_args.kwargs["live"])

    def test_dry_run_reports_missing_artifacts_without_build_or_writes(self):
        self.seed_niri()
        before = {p.relative_to(self.home): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        (self.repo / app.PLUGINS["kate"][2]).unlink()
        (self.repo / app.PLUGINS["glass"][2]).unlink()
        with patch.object(app.subprocess, "run") as run:
            self.assertEqual(app.main(["install", "--dry-run", "--home", str(self.home), "--mode", "dark"]), 0)
            run.assert_not_called()
        after = {p.relative_to(self.home): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertIn("Would build kate", self.output.getvalue())
        self.assertIn("Would build glass", self.output.getvalue())
        self.assertIn("Qt6", self.output.getvalue())
        self.assertIn("Dry-run install:", self.output.getvalue())
        self.assertIn(str(self.home / ".config/niri-dms-theme/session.env"), self.output.getvalue())
        self.assertIn("Backup would be:", self.output.getvalue())

    def test_preview_kate_stages_resources_and_execs_without_integration(self):
        host = {"WAYLAND_DISPLAY": "wayland-99", "XDG_RUNTIME_DIR": "/run/user/fake",
                "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/fake/bus",
                "XDG_CONFIG_HOME": "/foreign/config", "XDG_DATA_DIRS": "/foreign/data",
                "QT_PLUGIN_PATH": "/foreign/plugins"}
        with patch.dict(os.environ, host), patch.object(app.integrate, "apply") as apply, \
                patch.object(app, "build_plugins") as build, patch.object(app, "wait_for_app", return_value=0) as execute:
            self.assertEqual(app.main(["preview", "kate", "--home", str(self.home), "--mode", "light"]), 0)
            build.assert_called_once_with(("glass", "kate"))
            apply.assert_not_called()
            arguments, env = execute.call_args.args
            command = arguments[0]
        sample = Path(context(str(self.home))["PROFILE_DATA"]) / "preview.cpp"
        self.assertEqual((command, arguments), ("kate", ["kate", "--desktopfile", "org.kde.kate.niri-glass-preview",
                                                         "--block", "--new", "--startanon", str(sample)]))
        self.assertEqual(sample.read_bytes(), (self.repo / "assets/kate/preview.cpp").read_bytes())
        for key, default in (("CONFIG", ".config"), ("DATA", ".local/share"),
                             ("STATE", ".local/state"), ("CACHE", ".cache")):
            self.assertEqual(env[f"XDG_{key}_HOME"], str(self.home / default))
        self.assertEqual(env["HOME"], str(self.home))
        self.assertEqual(env["WAYLAND_DISPLAY"], "wayland-99")
        self.assertEqual(env["DBUS_SESSION_BUS_ADDRESS"], host["DBUS_SESSION_BUS_ADDRESS"])
        self.assertNotIn("/foreign", env["QT_PLUGIN_PATH"])
        self.assertNotIn("/foreign", env["XDG_DATA_DIRS"])
        session = self.home / ".local/share/kate/anonymous.katesession"
        self.assertIn("katebalancedglassplugin=true", session.read_text())
        self.assertIn("lspclientplugin=false", session.read_text())
        self.assertIn("Auto Color Theme Selection=true", (self.home / ".config/katerc").read_text())
        self.assertTrue(self.home.exists())
        self.assertIn("Preview ready", self.output.getvalue())
        self.assertIn("no live DMS connection", self.output.getvalue())

    def test_preview_dolphin_uses_shared_glass_and_preserves_sample_edits(self):
        with patch.object(app, "build_plugins") as build, \
                patch.object(app, "wait_for_app", return_value=0) as execute:
            self.assertEqual(app.main(["preview", "dolphin", "--home", str(self.home), "--mode", "dark"]), 0)
            build.assert_called_once_with(("glass",))
            argv, env = execute.call_args.args
            sample = Path(context(str(self.home))["PROFILE_DATA"]) / "preview-files"
            self.assertEqual(argv, ["dolphin", "--desktopfile", "org.kde.dolphin.niri-glass-preview",
                                    "--new-window", str(sample)])
            self.assertEqual(env["QT_STYLE_OVERRIDE"], "NiriGlass")
            self.assertEqual(len(list(sample.iterdir())), 3)
            (sample / "Notes.txt").write_text("keep my edits")
            self.assertEqual(app.main(["preview", "dolphin", "--home", str(self.home), "--mode", "light"]), 0)
            self.assertEqual((sample / "Notes.txt").read_text(), "keep my edits")
            self.assertFalse((self.home / ".config/systemd").exists())

    def test_preview_propagates_child_exit_status(self):
        with patch.object(app, "wait_for_app", return_value=7):
            self.assertEqual(app.main(["preview", "kate", "--home", str(self.home), "--mode", "dark"]), 7)

    def test_preview_drawy_builds_only_its_missing_plugin_then_execs_owned_wrapper(self):
        (self.repo / app.PLUGINS["glass"][2]).unlink()
        (self.repo / app.PLUGINS["kate"][2]).unlink()
        def fake_cmake(command, **kwargs):
            if "--build" in command:
                artifact = self.repo / app.PLUGINS["glass"][2]
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_bytes(b"built drawy module")
            return subprocess.CompletedProcess(command, 0)
        with patch.object(app.subprocess, "run", side_effect=fake_cmake) as run, \
                patch.object(app.shutil, "which", return_value="/fake/cmake"), \
                patch.object(app, "wait_for_app", return_value=0) as execute:
            self.assertEqual(app.main(["preview", "drawy", "--home", str(self.home), "--mode", "dark"]), 0)
        self.assertEqual(run.call_count, 2)
        self.assertTrue(all("kate-balanced-glass" not in " ".join(c.args[0]) for c in run.call_args_list))
        argv, env = execute.call_args.args
        executable = argv[0]
        ctx = context(str(self.home))
        self.assertEqual(executable, str(Path(ctx["PROFILE_DATA"]) / "bin/drawy-glass"))
        self.assertEqual(argv, [executable, "--desktopfile", "org.kde.drawy.niri-glass-preview"])
        self.assertTrue(os.access(executable, os.X_OK))
        self.assertEqual(env["NIRI_DMS_THEME_PROFILE"], "niri-dms-glass")
        self.assertFalse((self.home / ".config/systemd").exists())

    def test_rebuilds_stale_selected_plugin_inputs_and_bounds_parallelism(self):
        source = self.repo / app.PLUGINS["glass"][0]
        source.mkdir(parents=True)
        artifact = self.repo / app.PLUGINS["glass"][2]
        for filename in ("style.cpp", "style.h", "style.hpp", "style.json", "CMakeLists.txt", "extra.cmake"):
            with self.subTest(filename=filename):
                changed = source / filename
                changed.write_text("changed source")
                stamp = artifact.stat().st_mtime_ns + 1_000_000_000
                os.utime(changed, ns=(stamp, stamp))
                with patch.object(app.subprocess, "run") as run:
                    app.build_plugins(("glass",), dry_run=True)
                    run.assert_not_called()
                self.assertIn("outdated", self.output.getvalue())
                with patch.object(app.subprocess, "run") as run, \
                        patch.object(app.shutil, "which", return_value="/fake/cmake"):
                    app.build_plugins(("glass",))
                self.assertEqual(run.call_count, 2)
                self.assertIn(str(source), run.call_args_list[0].args[0])
                self.assertEqual(run.call_args_list[1].args[0][-2:], ["--parallel", "2"])
                changed.unlink()

    def test_preview_reuse_keeps_drawy_and_shared_preferences_byte_for_byte(self):
        with patch.object(app, "wait_for_app", return_value=0):
            self.assertEqual(app.main(["preview", "drawy", "--home", str(self.home), "--mode", "dark"]), 0)
            config = Path(context(str(self.home))["PROFILE_CONFIG"])
            preferences = {
                config / "apps/drawy/drawyrc": b"# edited in Drawy\n[KDE]\nwidgetStyle=Custom\n[Canvas]\nBackground=custom\n[Tools]\nPenSize=17\n",
                config / "apps/drawy/darklyrc": b"[Common]\nCornerRadius=11\nCustomFlag=true\n",
                config / "shared/darklyrc": b"[Common]\nCornerRadius=9\n",
                config / "shared/katebalancedglassrc": b"[Themes]\nLight=My Theme\nDark=My Dark Theme\n",
            }
            for path, data in preferences.items():
                path.write_bytes(data)
            self.assertEqual(app.main(["preview", "drawy", "--home", str(self.home), "--mode", "light"]), 0)
        for path, data in preferences.items():
            self.assertEqual(path.read_bytes(), data)

    def test_preview_omitted_home_creates_temporary_home_and_keeps_it(self):
        generated = self.root / "generated-preview"
        generated.mkdir()
        with patch.object(app.tempfile, "mkdtemp", return_value=str(generated)), \
                patch.object(app, "wait_for_app", return_value=0) as execute:
            self.assertEqual(app.main(["preview", "kate", "--mode", "dark"]), 0)
        self.assertEqual(execute.call_args.args[1]["HOME"], str(generated))
        self.assertTrue((generated / ".themekit-preview").exists())
        self.assertIn(str(generated), self.output.getvalue())

    def test_preview_reuses_home_and_preserves_session_contents(self):
        with patch.object(app, "wait_for_app", return_value=0):
            self.assertEqual(app.main(["preview", "kate", "--home", str(self.home), "--mode", "dark"]), 0)
            session = self.home / ".local/share/kate/anonymous.katesession"
            session.write_text(session.read_text() + "\n[Open Documents]\nCount=3\n")
            drawing = self.home / "drawing.png"
            drawing.write_bytes(b"keep drawing")
            self.assertEqual(app.main(["preview", "kate", "--home", str(self.home), "--mode", "light"]), 0)
        self.assertIn("Count=3", session.read_text())
        self.assertEqual(drawing.read_bytes(), b"keep drawing")

    def test_kate_preview_preserves_edited_sample_and_explicit_lsp_preference(self):
        with patch.object(app, "wait_for_app", return_value=0) as execute:
            self.assertEqual(app.main(["preview", "kate", "--home", str(self.home), "--mode", "dark"]), 0)
            sample = Path(context(str(self.home))["PROFILE_DATA"]) / "preview.cpp"
            sample.write_text("// my edited sample\nint answer = 42;\n")
            session = self.home / ".local/share/kate/anonymous.katesession"
            session.write_text(session.read_text().replace("lspclientplugin=false", "lspclientplugin=true"))
            self.assertEqual(app.main(["preview", "kate", "--home", str(self.home), "--mode", "light"]), 0)
        self.assertEqual(sample.read_text(), "// my edited sample\nint answer = 42;\n")
        self.assertIn("lspclientplugin=true", session.read_text())
        self.assertEqual(execute.call_args.args[0][-1], str(sample))

    def test_preview_accepts_old_owned_install_home(self):
        self.seed_niri()
        self.assertEqual(app.main(["install", "--home", str(self.home), "--mode", "dark"]), 0)
        self.assertFalse((self.home / ".themekit-preview").exists())
        with patch.object(app, "wait_for_app", return_value=0) as execute:
            self.assertEqual(app.main(["preview", "kate", "--home", str(self.home), "--mode", "dark"]), 0)
            execute.assert_called_once()

    def test_preview_refuses_foreign_home_symlink_and_traversal(self):
        self.home.mkdir()
        user_file = self.home / "precious"
        user_file.write_text("untouched")
        with self.assertRaises(ValueError):
            app.preview_home(str(self.home))
        self.assertEqual(user_file.read_text(), "untouched")
        symlink = self.root / "link"
        symlink.symlink_to(self.home, target_is_directory=True)
        with self.assertRaises(ValueError):
            app.preview_home(str(symlink))
        with self.assertRaises(ValueError):
            app.preview_home(str(self.root / "a/../b"))
        with self.assertRaises(ValueError):
            app.preview_home(str(Path.home()))

    def test_mode_reads_dms_once_with_timeout_and_falls_back(self):
        for output, mode in (("light", "light"), ('{"mode":"dark"}', "dark"),
                             ("Mode: light", "light"), ("unexpected", "dark")):
            with self.subTest(output=output), patch.object(app.subprocess, "run", return_value=
                    subprocess.CompletedProcess([], 0, stdout=output)) as run:
                self.assertEqual(app.current_mode(), mode)
                self.assertEqual(run.call_args.args[0], ["dms", "ipc", "call", "theme", "getMode"])
                self.assertEqual(run.call_args.kwargs["timeout"], 2)
        with patch.object(app.subprocess, "run", side_effect=subprocess.TimeoutExpired("dms", 2)):
            self.assertEqual(app.current_mode(), "dark")
        with patch.object(app.subprocess, "run", side_effect=FileNotFoundError):
            self.assertEqual(app.current_mode(), "dark")

    def test_explicit_mode_never_calls_dms(self):
        with patch.object(app, "current_mode", side_effect=AssertionError("must not call DMS")), \
                patch.object(app, "wait_for_app", return_value=0):
            self.assertEqual(app.main(["preview", "kate", "--home", str(self.home), "--mode", "light"]), 0)

    def test_resource_map_is_fixed_and_contains_activation_and_both_modules(self):
        ctx = context(str(self.home))
        items = app.resources(ctx, "dark")
        paths = {str(item.path) for item in items}
        self.assertEqual(len(paths), len(items))
        self.assertFalse(any("theme-session" in p or "/lib/themekit" in p for p in paths))
        for name in app.PLUGINS:
            self.assertIn(str(Path(ctx["PLUGIN_ROOT"]) / app.PLUGINS[name][3]), paths)
        config = next(i.data for i in items if str(i.path).endswith("/qtengine.json"))
        self.assertEqual(json.loads(config)["theme"]["style"], "NiriGlass")
        env = app.environment(ctx)
        self.assertEqual(env["QT_QPA_PLATFORMTHEME"], "qtengine")
        self.assertEqual(env["XDG_CURRENT_DESKTOP"], "niri")


if __name__ == "__main__":
    unittest.main()

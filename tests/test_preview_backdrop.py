"""Backdrop tests stage their own host config and Unix socket; no live desktop."""
import contextlib
import io
import os
from pathlib import Path
import re
import signal
import socket
import stat
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from themekit import preview


class BackdropTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="themekit-backdrop-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "original"
        self.config = self.home / ".config/niri/config.kdl"
        self.config.parent.mkdir(parents=True)
        self.original = '// unrelated host settings\ninput { keyboard { xkb { layout "us"; }; }; }\n'
        self.config.write_text(self.original)
        self.sock = socket.socket(socket.AF_UNIX)
        self.addCleanup(self.sock.close)
        self.socket_path = self.root / "niri.sock"
        self.sock.bind(str(self.socket_path))
        self.origin = {"HOME": str(self.home), "XDG_CURRENT_DESKTOP": "niri",
                       "NIRI_SOCKET": str(self.socket_path)}
        self.preview = self.root / "preview"
        self.preview.mkdir()

    def runtime_socket(self, name, runtime=None):
        runtime = runtime or (self.root / "runtime")
        runtime.mkdir(parents=True, exist_ok=True)
        path = runtime / name
        sock = socket.socket(socket.AF_UNIX)
        self.addCleanup(sock.close)
        sock.bind(str(path))
        return path

    def test_exact_app_rule_optional_include_and_cleanup_preserve_other_edits(self):
        for app in ("kate", "dolphin", "drawy"):
            with self.subTest(app=app):
                self.config.write_text(self.original)
                with preview.backdrop(self.preview, app, self.origin):
                    current = self.config.read_text()
                    self.assertIn(' optional=true\n', current)
                    rules = list(self.preview.glob(".niri-preview-*.kdl"))
                    self.assertEqual(len(rules), 1)
                    rule = rules[0].read_text()
                    self.assertEqual(rule.count("window-rule"), 1)
                    self.assertIn("popups {", rule)
                    self.assertEqual(rule.count("opacity 1.0"), 2)
                    self.assertIn("draw-border-with-background false", rule)
                    import json
                    pattern = json.loads(rule.split("match app-id=", 1)[1].splitlines()[0])
                    self.assertTrue(re.fullmatch(pattern, preview.desktop_id(app)))
                    self.assertFalse(re.fullmatch(pattern, "org.kde.otherapp"))
                    self.assertFalse(re.fullmatch(pattern, f"org.kde.{app}"))
                    self.assertFalse(re.fullmatch(pattern, preview.desktop_id(app) + ".other"))
                    self.assertNotIn("saturation", rule)
                    for value in ("blur true", "xray false", "noise 0.008"):
                        self.assertIn(value, rule)
                    with self.config.open("a") as stream:
                        stream.write('// user edit while preview runs\n')
                self.assertEqual(self.config.read_text(), self.original + '// user edit while preview runs\n')
                self.assertFalse(list(self.preview.glob(".niri-preview-*.kdl")))

    def test_installed_material_leaves_saturation_to_compositor(self):
        material = Path(__file__).resolve().parents[1] / "assets/niri/material.kdl"
        self.assertNotRegex(material.read_text(), r"(?m)^\s*saturation\s")

    def test_overlapping_previews_remove_only_their_own_markers(self):
        with preview.backdrop(self.preview, "kate", self.origin):
            kate_config = self.config.read_text()
            with preview.backdrop(self.preview, "dolphin", self.origin):
                self.assertEqual(self.config.read_text().count("include "), 2)
            self.assertEqual(self.config.read_text(), kate_config)
        self.assertEqual(self.config.read_text(), self.original)

    def test_atomic_update_rejects_concurrent_editor_change(self):
        def edit_during_transform(current):
            self.config.write_text(self.original + "// concurrent edit\n")
            return current + "// would overwrite edit\n"
        with self.assertRaisesRegex(OSError, "changed during preview update"):
            preview._update_config(self.config, edit_during_transform)
        self.assertEqual(self.config.read_text(), self.original + "// concurrent edit\n")
        self.assertFalse(list(self.config.parent.glob(".themekit-preview-*")))

    def test_lock_rejects_foreign_owner_or_non_regular_file(self):
        for mode, uid in ((stat.S_IFREG | 0o600, os.getuid() + 1),
                          (stat.S_IFIFO | 0o600, os.getuid())):
            with self.subTest(mode=mode, uid=uid), \
                    patch.object(preview.os, "fstat", return_value=SimpleNamespace(st_mode=mode, st_uid=uid)):
                with self.assertRaisesRegex(OSError, "unsafe preview lock"):
                    preview._update_config(self.config, lambda current: current + "changed")
                self.assertEqual(self.config.read_text(), self.original)

    def test_cleanup_does_not_follow_rule_replaced_with_external_symlink(self):
        external = self.root / "unrelated.kdl"
        external.write_text("keep unrelated file")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            with preview.backdrop(self.preview, "kate", self.origin):
                rule, = self.preview.glob(".niri-preview-*.kdl")
                self.assertEqual(rule.resolve().parent, self.preview.resolve())
                rule.unlink()
                rule.symlink_to(external)
            self.assertIn("outside preview root", output.getvalue())
        self.assertEqual(external.read_text(), "keep unrelated file")
        self.assertEqual(self.config.read_text(), self.original)

    def test_exception_still_cleans_exact_marker(self):
        with self.assertRaisesRegex(RuntimeError, "app failed"):
            with preview.backdrop(self.preview, "kate", self.origin):
                raise RuntimeError("app failed")
        self.assertEqual(self.config.read_text(), self.original)

    def test_original_xdg_config_home_wins_over_home(self):
        self.origin["HOME"] = str(self.root / "wrong-home")
        self.origin["XDG_CONFIG_HOME"] = str(self.home / ".config")
        with preview.backdrop(self.preview, "dolphin", self.origin):
            self.assertIn(" optional=true", self.config.read_text())
        self.assertEqual(self.config.read_text(), self.original)

    def test_missing_socket_non_niri_and_missing_config_skip_without_writes(self):
        for changes in ({"NIRI_SOCKET": ""}, {"NIRI_SOCKET": str(self.config)},
                        {"XDG_CURRENT_DESKTOP": "KDE"},
                        {"XDG_CONFIG_HOME": str(self.root / "missing")}):
            with self.subTest(changes=changes), contextlib.redirect_stdout(io.StringIO()) as output:
                with preview.backdrop(self.preview, "kate", dict(self.origin, **changes)):
                    self.assertEqual(self.config.read_text(), self.original)
                self.assertIn("skipped", output.getvalue())
                self.assertFalse(list(self.preview.iterdir()))

    def test_discovers_exact_runtime_socket_when_niri_socket_is_unset(self):
        runtime = self.root / "runtime"
        self.runtime_socket("niri.wayland-77.4242.sock", runtime)
        self.runtime_socket("niri.wayland-770.9.sock", runtime)
        for changes in ({}, {"NIRI_SOCKET": ""}):
            with self.subTest(changes=changes), contextlib.redirect_stdout(io.StringIO()) as output:
                origin = {"HOME": str(self.home), "XDG_CURRENT_DESKTOP": "niri",
                          "XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-77",
                          **changes}
                with preview.backdrop(self.preview, "kate", origin):
                    current = self.config.read_text()
                    self.assertIn(" optional=true\n", current)
                    self.assertEqual(len(list(self.preview.glob(".niri-preview-*.kdl"))), 1)
                self.assertIn("Preview backdrop active", output.getvalue())
                self.assertEqual(self.config.read_text(), self.original)
                self.assertFalse(list(self.preview.glob(".niri-preview-*.kdl")))

    def test_discovery_refuses_ambiguous_or_wrong_display_sockets_without_writes(self):
        runtime = self.root / "runtime"
        self.runtime_socket("niri.wayland-77.1.sock", runtime)
        self.runtime_socket("niri.wayland-77.2.sock", runtime)
        origin = {"HOME": str(self.home), "XDG_CURRENT_DESKTOP": "niri",
                  "XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-77"}
        with contextlib.redirect_stdout(io.StringIO()) as output:
            with preview.backdrop(self.preview, "kate", origin):
                self.assertEqual(self.config.read_text(), self.original)
        self.assertIn("ambiguous", output.getvalue())
        self.assertIn("niri.wayland-77.1.sock", output.getvalue())
        self.assertIn("niri.wayland-77.2.sock", output.getvalue())
        self.assertFalse(list(self.preview.iterdir()))

    def test_explicit_niri_socket_error_is_not_hidden_by_fallback(self):
        runtime = self.root / "runtime"
        self.runtime_socket("niri.wayland-77.4242.sock", runtime)
        origin = {"HOME": str(self.home), "XDG_CURRENT_DESKTOP": "niri",
                  "NIRI_SOCKET": str(self.config),
                  "XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-77"}
        with contextlib.redirect_stdout(io.StringIO()) as output:
            with preview.backdrop(self.preview, "kate", origin):
                self.assertEqual(self.config.read_text(), self.original)
        message = output.getvalue()
        self.assertIn(f"NIRI_SOCKET={self.config}", message)
        self.assertIn("not a Unix domain socket", message)
        self.assertNotIn("ambiguous", message)
        self.assertFalse(list(self.preview.iterdir()))

    def test_missing_runtime_or_display_skips_without_guessing(self):
        runtime = self.root / "runtime"
        self.runtime_socket("niri.wayland-77.4242.sock", runtime)
        for changes in ({"XDG_RUNTIME_DIR": str(runtime)},
                        {"WAYLAND_DISPLAY": "wayland-77"}):
            with self.subTest(changes=changes), contextlib.redirect_stdout(io.StringIO()) as output:
                origin = {"HOME": str(self.home), "XDG_CURRENT_DESKTOP": "niri", **changes}
                with preview.backdrop(self.preview, "kate", origin):
                    self.assertEqual(self.config.read_text(), self.original)
                self.assertIn("skipped", output.getvalue())
                self.assertFalse(list(self.preview.iterdir()))

    def test_discovered_symlink_socket_is_refused(self):
        runtime = self.root / "runtime"
        target = self.runtime_socket("target.sock", runtime)
        (runtime / "niri.wayland-88.1.sock").symlink_to(target)
        origin = {"HOME": str(self.home), "XDG_CURRENT_DESKTOP": "niri",
                  "XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-88"}
        with contextlib.redirect_stdout(io.StringIO()) as output:
            with preview.backdrop(self.preview, "kate", origin):
                self.assertEqual(self.config.read_text(), self.original)
        self.assertIn("symbolic link", output.getvalue())
        self.assertFalse(list(self.preview.iterdir()))

    def test_socket_must_be_owned_by_this_user(self):
        with patch.object(preview.os, "getuid", return_value=os.getuid() + 1):
            self.assertEqual(preview._socket_problem(self.socket_path),
                             "socket is not owned by this user")

    def test_real_child_that_detaches_without_block_is_held_by_block(self):
        script = self.root / "fake-kate"
        script.write_text(
            f"#!{sys.executable}\n"
            "import os, sys, time\n"
            "from pathlib import Path\n"
            "marker = Path(os.environ['FAKE_KATE_MARKER'])\n"
            "marker.write_text(' '.join(sys.argv[1:]))\n"
            "if '--block' not in sys.argv:\n"
            "    if os.fork() > 0:\n"
            "        os._exit(0)\n"
            "time.sleep(0.4)\n"
            "Path(str(marker) + '.done').write_text('done')\n")
        script.chmod(0o700)
        detached = self.root / "detached"
        isolated = {"HOME": str(self.root / "fake-home"),
                    "XDG_CONFIG_HOME": str(self.root / "fake-home/.config")}
        env = dict(os.environ, **isolated, FAKE_KATE_MARKER=str(detached))
        self.assertEqual(preview.wait_for_app([str(script), "--new"], env), 0)
        self.assertFalse(Path(str(detached) + ".done").exists())
        deadline = time.monotonic() + 5
        while not Path(str(detached) + ".done").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(Path(str(detached) + ".done").exists())
        blocked = self.root / "blocked"
        self.assertEqual(preview.wait_for_app(
            [str(script), "--block", "--new"],
            dict(os.environ, **isolated, FAKE_KATE_MARKER=str(blocked))), 0)
        self.assertTrue(Path(str(blocked) + ".done").exists())

    def test_wait_forwards_signals_and_restores_handlers(self):
        installed = {}
        def install(signum, handler):
            installed[signum] = handler
            return signal.SIG_DFL
        with patch.object(preview.subprocess, "Popen") as popen, \
                patch.object(preview.signal, "signal", side_effect=install) as handlers:
            child = popen.return_value
            child.poll.return_value = None
            def wait():
                installed[signal.SIGTERM](signal.SIGTERM, None)
                return 0
            child.wait.side_effect = wait
            self.assertEqual(preview.wait_for_app(["fake-kate"], {"HOME": "isolated"}), 0)
            child.send_signal.assert_called_once_with(signal.SIGTERM)
            self.assertEqual(handlers.call_count, 6)
            self.assertTrue(all(handler == signal.SIG_DFL for handler in installed.values()))


if __name__ == "__main__":
    unittest.main()

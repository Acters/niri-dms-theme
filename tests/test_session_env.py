# SPDX-License-Identifier: MIT
"""Tests for the one-shot Niri session environment helper, with no live manager."""
from __future__ import annotations

import contextlib
import fcntl
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from themekit import session_env


def completed(args, stdout="", stderr=""):
    return subprocess.CompletedProcess(args, 0, stdout, stderr)


MANAGER_CALL = [
    "busctl", "--user", "--json=short", "get-property",
    "org.freedesktop.systemd1", "/org/freedesktop/systemd1",
    "org.freedesktop.systemd1.Manager", "Environment",
]


class FakeRunner:
    """A tiny systemd/D-Bus model; it never starts a process."""

    def __init__(self, manager):
        self.manager = manager
        self.calls = []
        self.dbus = {}
        self.fail_dbus_once = False
        self.fail_restore_once = False
        self.fail_set_contains = None
        self.timeout_dbus_once = False
        self.busctl_output = None
        self.niri_active = True

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        expected = {"capture_output": True, "text": True, "check": True,
                    "timeout": session_env.COMMAND_TIMEOUT}
        if kwargs != expected:
            raise AssertionError(f"unexpected runner keywords: {kwargs}")
        command = args[0]
        if command == "systemctl":
            if args[1] != "--user" or len(args) < 3:
                raise AssertionError(f"unexpected systemctl call: {args}")
            operation = args[2]
            if operation == "is-active":
                if not self.niri_active:
                    raise subprocess.CalledProcessError(3, args)
                return completed(args, "active\n")
            if operation == "set-environment":
                if self.fail_restore_once:
                    self.fail_restore_once = False
                    raise subprocess.CalledProcessError(1, args, stderr="temporary failure")
                if (self.fail_set_contains is not None
                        and self.fail_set_contains in args[3:]):
                    self.fail_set_contains = None
                    raise subprocess.CalledProcessError(1, args, stderr="temporary failure")
                for assignment in args[3:]:
                    key, value = assignment.split("=", 1)
                    self.manager[key] = value
                return completed(args)
            if operation == "unset-environment":
                if self.fail_restore_once:
                    self.fail_restore_once = False
                    raise subprocess.CalledProcessError(1, args, stderr="temporary failure")
                for key in args[3:]:
                    self.manager.pop(key, None)
                return completed(args)
        if command == "busctl":
            if self.busctl_output is not None:
                return completed(args, self.busctl_output)
            entries = [f"{key}={value}" for key, value in self.manager.items()]
            return completed(args, json.dumps({"type": "as", "data": entries}) + "\n")
        if command == "dbus-update-activation-environment":
            if self.timeout_dbus_once:
                self.timeout_dbus_once = False
                raise subprocess.TimeoutExpired(args, session_env.COMMAND_TIMEOUT)
            if self.fail_dbus_once:
                self.fail_dbus_once = False
                raise subprocess.CalledProcessError(1, args, stderr="temporary failure")
            for assignment in args[1:]:
                key, value = assignment.split("=", 1)
                self.dbus[key] = value
            return completed(args)
        raise AssertionError(f"unexpected command: {args}")


class SessionEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="niri-session-env-")
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.runtime = root / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.theme = root / "theme"
        self.manager = {
            "PATH": "/usr/bin:/bin",
            "QT_PLUGIN_PATH": "/manager/plugins:/shared/plugins",
            "XDG_CONFIG_DIRS": "/manager/config:/etc/xdg",
            "XDG_DATA_DIRS": "/manager/share:/usr/share",
            "QT_STYLE_OVERRIDE": "OldStyle",
            "UNRELATED_SECRET": "leave-me-alone",
        }
        self.runner = FakeRunner(self.manager)
        self.env = {
            "XDG_RUNTIME_DIR": str(self.runtime),
            "XDG_CURRENT_DESKTOP": "niri",
            "QT_QPA_PLATFORM": "wayland",
            "QT_QPA_PLATFORMTHEME": "qtengine",
            "QT_QPA_PLATFORMTHEME_QT6": "qtengine",
            "QT_STYLE_OVERRIDE": "NiriGlass",
            "QTENGINE_CONFIG": str(self.theme / "qtengine.json"),
            "QT_PLUGIN_PATH": f"{self.theme}/qt-plugins:/manager/plugins",
            "XDG_CONFIG_DIRS": f"{self.theme}/config:/etc/xdg",
            "XDG_DATA_DIRS": f"{self.theme}/share:/usr/local/share:/usr/share",
            "NIRI_DMS_THEME_PROFILE": "niri-dms-glass",
            "NIRI_DMS_THEME_CONFIG_HOME": str(self.theme / "config-home"),
            "NIRI_DMS_THEME_DATA_HOME": str(self.theme / "data-home"),
        }
        self.state = self.runtime / "niri-dms-theme" / "session-env.json"
        real_run = patch.object(
            session_env.subprocess, "run",
            side_effect=AssertionError("tests must inject the fake runner"),
        )
        real_run.start()
        self.addCleanup(real_run.stop)

    def activate(self, environment=None, **kwargs):
        return session_env.activate(self.env if environment is None else environment,
                                    self.runner, **kwargs)

    def prepare(self, environment=None, **kwargs):
        return session_env.prepare(self.env if environment is None else environment,
                                   self.runner, **kwargs)

    def deactivate(self, environment=None):
        return session_env.deactivate(self.env if environment is None else environment,
                                      self.runner)

    def state_document(self):
        return json.loads(self.state.read_text())

    def test_gate_rejects_non_niri_missing_token_and_wrong_marker(self):
        cases = [
            (None, "niri-dms-glass"),
            ("COSMIC", "niri-dms-glass"),
            ("GNOME", "niri-dms-glass"),
            ("niri", None),
            ("niri", "another-profile"),
        ]
        for desktop, marker in cases:
            environment = dict(self.env)
            if desktop is None:
                environment.pop("XDG_CURRENT_DESKTOP")
            else:
                environment["XDG_CURRENT_DESKTOP"] = desktop
            if marker is None:
                environment.pop("NIRI_DMS_THEME_PROFILE")
            else:
                environment["NIRI_DMS_THEME_PROFILE"] = marker
            with self.subTest(desktop=desktop, marker=marker):
                with self.assertRaises(session_env.Error):
                    self.activate(environment)
        self.assertEqual(self.runner.calls, [])
        self.assertFalse(self.state.exists())

    def test_profile_keys_are_complete_absolute_and_control_free(self):
        cases = []
        missing = dict(self.env)
        missing.pop("QT_QPA_PLATFORMTHEME_QT6")
        cases.append(missing)
        newline = dict(self.env)
        newline["QT_STYLE_OVERRIDE"] = "NiriGlass\nLEAK=yes"
        cases.append(newline)
        relative = dict(self.env)
        relative["QTENGINE_CONFIG"] = "relative/qtengine.json"
        cases.append(relative)
        empty_path = dict(self.env)
        empty_path["XDG_DATA_DIRS"] = f"{self.theme}/share::/usr/share"
        cases.append(empty_path)
        for environment in cases:
            with self.subTest(environment=environment):
                with self.assertRaises(session_env.Error):
                    self.activate(environment)
        self.assertEqual(self.runner.calls, [])
        self.assertFalse(self.state.exists())

    def test_one_shot_activation_and_deactivation_commands(self):
        self.assertTrue(self.activate(self.env))
        self.assertTrue(self.state.is_file())
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.state.parent.stat().st_mode), 0o700)

        manager_call = self.runner.calls[1]
        dbus_call = self.runner.calls[2]
        self.assertEqual(manager_call[:3], ["systemctl", "--user", "set-environment"])
        self.assertEqual(dbus_call[0], "dbus-update-activation-environment")
        self.assertEqual(self.runner.calls[0], MANAGER_CALL)
        for call in (manager_call, dbus_call):
            self.assertNotIn("--all", call)
            self.assertNotIn("--systemd", call)
            self.assertFalse(any(argument == "PATH=/usr/bin:/bin" for argument in call))
        self.assertIn("QT_PLUGIN_PATH=" + self.manager["QT_PLUGIN_PATH"], dbus_call)

        self.assertTrue(self.deactivate(self.env))
        self.assertFalse(self.state.exists())
        unset_call = next(call for call in self.runner.calls
                          if call[:3] == ["systemctl", "--user", "unset-environment"])
        self.assertIn("QT_QPA_PLATFORMTHEME", unset_call)
        self.assertFalse(any("=" in key for key in unset_call[3:]))
        dbus_cleanup = next(call for call in reversed(self.runner.calls)
                            if call[0] == "dbus-update-activation-environment")
        self.assertIn("QT_QPA_PLATFORMTHEME=", dbus_cleanup)
        self.assertEqual(self.manager["PATH"], "/usr/bin:/bin")
        self.assertEqual(self.manager["UNRELATED_SECRET"], "leave-me-alone")

    def test_state_records_only_owned_baseline_and_installed_values(self):
        self.activate()
        document = self.state_document()
        self.assertEqual(set(document),
                         {"version", "phase", "baseline", "installed", "pending"})
        self.assertEqual(document["phase"], "active")
        self.assertEqual(document["pending"], {"manager": [], "dbus": []})
        self.assertEqual(set(document["baseline"]), set(session_env.OWNED_KEYS))
        self.assertEqual(set(document["installed"]), set(session_env.OWNED_KEYS))
        self.assertNotIn("PATH", document["baseline"])
        self.assertNotIn("UNRELATED_SECRET", document["baseline"])
        self.assertNotIn("leave-me-alone", json.dumps(document))
        self.assertEqual(document["baseline"]["QT_STYLE_OVERRIDE"], "OldStyle")
        self.assertIsNone(document["baseline"]["QT_QPA_PLATFORM"])

    def test_activation_is_idempotent_and_keeps_initial_baseline(self):
        self.activate()
        original = self.state_document()["baseline"]
        self.activate()
        self.activate()
        self.assertEqual(self.state_document()["baseline"], original)
        self.assertEqual(original["QT_STYLE_OVERRIDE"], "OldStyle")
        self.assertIsNone(original["QT_QPA_PLATFORMTHEME_QT6"])
        self.assertEqual(self.manager["QT_STYLE_OVERRIDE"], "NiriGlass")
        self.deactivate()
        self.assertFalse(self.state.exists())
        self.assertEqual(self.manager["QT_STYLE_OVERRIDE"], "OldStyle")
        self.assertNotIn("QT_QPA_PLATFORMTHEME_QT6", self.manager)

    def test_paths_are_prefixed_deduped_and_preserve_manager_entries(self):
        self.activate()
        self.assertEqual(
            self.manager["QT_PLUGIN_PATH"],
            f"{self.theme}/qt-plugins:/manager/plugins:/shared/plugins",
        )
        self.assertEqual(
            self.manager["XDG_CONFIG_DIRS"],
            f"{self.theme}/config:/manager/config:/etc/xdg",
        )
        self.assertEqual(
            self.manager["XDG_DATA_DIRS"],
            f"{self.theme}/share:/manager/share:/usr/share:/usr/local/share",
        )
        self.activate()
        self.assertEqual(
            self.manager["XDG_DATA_DIRS"],
            f"{self.theme}/share:/manager/share:/usr/share:/usr/local/share",
        )

    def test_later_manager_changes_are_not_restored_or_unset(self):
        self.activate()
        after_activation = len(self.runner.calls)
        installed_plugin_path = self.manager["QT_PLUGIN_PATH"]
        self.manager["QT_QPA_PLATFORM"] = "xcb"
        self.manager["QT_PLUGIN_PATH"] = "/user/plugins:" + installed_plugin_path
        self.manager["QT_STYLE_OVERRIDE"] = "UserStyle"
        self.deactivate()
        self.assertEqual(self.manager["QT_QPA_PLATFORM"], "xcb")
        self.assertEqual(self.manager["QT_PLUGIN_PATH"],
                         "/user/plugins:" + installed_plugin_path)
        self.assertEqual(self.manager["QT_STYLE_OVERRIDE"], "UserStyle")
        cleanup = self.runner.calls[after_activation:]
        dbus_cleanup = next(call for call in cleanup
                            if call[0] == "dbus-update-activation-environment")
        self.assertNotIn("QT_QPA_PLATFORM=xcb", dbus_cleanup)
        self.assertNotIn("QT_PLUGIN_PATH=/user/plugins:", "".join(dbus_cleanup))
        self.assertNotIn("QT_STYLE_OVERRIDE=", dbus_cleanup)
        self.assertFalse(self.state.exists())

    def test_deactivate_needs_runtime_but_not_desktop_or_marker(self):
        self.activate()
        environment = {"XDG_RUNTIME_DIR": str(self.runtime)}
        self.assertTrue(self.deactivate(environment))
        self.assertFalse(self.state.exists())
        self.assertEqual(self.manager["QT_STYLE_OVERRIDE"], "OldStyle")

    def test_partial_activation_failure_rolls_back_and_retains_baseline(self):
        before = dict(self.manager)
        self.runner.fail_dbus_once = True
        with self.assertRaisesRegex(session_env.Error, "D-Bus"):
            self.activate()
        self.assertTrue(self.state.exists())
        self.assertEqual(self.state_document()["baseline"]["QT_STYLE_OVERRIDE"], "OldStyle")
        self.assertEqual(self.state_document()["pending"]["manager"], [])
        self.assertEqual(set(self.state_document()["pending"]["dbus"]),
                         set(session_env.OWNED_KEYS))
        self.assertEqual(self.manager, before)

        self.activate()
        self.assertEqual(self.state_document()["baseline"]["QT_STYLE_OVERRIDE"], "OldStyle")
        self.assertEqual(self.manager["QT_STYLE_OVERRIDE"], "NiriGlass")
        self.deactivate()
        self.assertEqual(self.manager, before)

    def test_transient_cleanup_failure_retains_state_then_retries(self):
        self.activate()
        self.runner.fail_restore_once = True
        with self.assertRaisesRegex(session_env.Error, "restore"):
            self.deactivate()
        self.assertTrue(self.state.exists())
        self.assertEqual(self.manager["QT_STYLE_OVERRIDE"], "NiriGlass")
        pending = self.state_document()["pending"]
        self.assertEqual(set(pending["manager"]), set(session_env.OWNED_KEYS))
        self.assertEqual(set(pending["dbus"]), set(session_env.OWNED_KEYS))
        self.assertTrue(self.deactivate())
        self.assertFalse(self.state.exists())
        self.assertEqual(self.manager["QT_STYLE_OVERRIDE"], "OldStyle")
        self.assertNotIn("QT_QPA_PLATFORMTHEME_QT6", self.manager)

    def test_corrupt_state_fails_closed_without_commands(self):
        self.state.parent.mkdir(mode=0o700)
        self.state.write_text("{not json\n")
        os.chmod(self.state, 0o600)
        with self.assertRaisesRegex(session_env.Error, "corrupt"):
            self.activate()
        with self.assertRaisesRegex(session_env.Error, "corrupt"):
            self.deactivate()
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.state.read_text(), "{not json\n")

    def test_invalid_state_types_fail_closed(self):
        self.state.parent.mkdir(mode=0o700)
        documents = [
            ({"version": 3, "phase": "prepared", "baseline": [], "installed": {},
              "pending": {"manager": [], "dbus": []}}, "baseline"),
            ({"version": 3, "phase": "active",
              "baseline": {key: None for key in session_env.OWNED_KEYS},
              "installed": {key: "x" for key in session_env.OWNED_KEYS},
              "pending": {"manager": [{}], "dbus": []}}, "pending manager"),
        ]
        for document, message in documents:
            with self.subTest(message=message):
                self.state.write_text(json.dumps(document))
                os.chmod(self.state, 0o600)
                with self.assertRaisesRegex(session_env.Error, message):
                    self.activate()
        self.assertEqual(self.runner.calls, [])

    def test_state_symlink_is_rejected_and_target_is_untouched(self):
        self.state.parent.mkdir(mode=0o700)
        target = Path(self.temporary.name) / "outside.json"
        target.write_text("outside\n")
        self.state.symlink_to(target)
        with self.assertRaisesRegex(session_env.Error, "symlink"):
            self.activate()
        self.assertEqual(self.runner.calls, [])
        self.assertTrue(self.state.is_symlink())
        self.assertEqual(target.read_text(), "outside\n")

    def test_command_timeout_rolls_back_and_keeps_state_for_retry(self):
        before = dict(self.manager)
        self.runner.timeout_dbus_once = True
        with self.assertRaisesRegex(session_env.Error, "timed out"):
            self.activate()
        self.assertTrue(self.state.exists())
        self.assertEqual(self.state_document()["baseline"]["QT_STYLE_OVERRIDE"], "OldStyle")
        self.assertEqual(self.manager, before)
        self.activate()
        self.deactivate()
        self.assertEqual(self.manager, before)

    def test_cleanup_dbus_timeout_journals_pending_after_manager_restore(self):
        self.activate()
        self.runner.timeout_dbus_once = True
        with self.assertRaisesRegex(session_env.Error, "timed out"):
            self.deactivate()
        self.assertTrue(self.state.exists())
        self.assertEqual(self.manager["QT_STYLE_OVERRIDE"], "OldStyle")
        pending = self.state_document()["pending"]
        self.assertEqual(pending["manager"], [])
        self.assertEqual(set(pending["dbus"]), set(session_env.OWNED_KEYS))
        self.assertTrue(self.deactivate())
        self.assertFalse(self.state.exists())

    def test_cleanup_dbus_failure_retries_pending_with_manager_already_baseline(self):
        self.activate()
        after_activation = len(self.runner.calls)
        self.runner.fail_dbus_once = True
        with self.assertRaisesRegex(session_env.Error, "D-Bus"):
            self.deactivate()
        self.assertEqual(self.state_document()["pending"]["manager"], [])
        self.assertEqual(set(self.state_document()["pending"]["dbus"]),
                         set(session_env.OWNED_KEYS))
        self.assertEqual(self.manager["QT_STYLE_OVERRIDE"], "OldStyle")
        self.assertTrue(self.deactivate())
        self.assertFalse(self.state.exists())
        cleanup = self.runner.calls[after_activation:]
        retried = [call for call in cleanup
                   if call[0] == "dbus-update-activation-environment"]
        self.assertEqual(len(retried), 2)
        self.assertEqual(len(retried[-1]) - 1, len(session_env.OWNED_KEYS))

    def test_require_active_is_checked_under_the_helper_lock(self):
        self.runner.niri_active = False
        with self.assertRaisesRegex(session_env.Error, "niri.service"):
            self.activate(self.env, require_active=True)
        self.assertTrue(self.runner.calls)
        self.assertEqual(self.runner.calls[0][:3], ["systemctl", "--user", "is-active"])
        self.assertFalse(self.state.exists())
        self.assertIn("QT_STYLE_OVERRIDE", self.manager)
        self.assertEqual(self.manager["QT_STYLE_OVERRIDE"], "OldStyle")

        self.runner.calls.clear()
        self.runner.niri_active = True
        self.assertTrue(self.activate(self.env, require_active=True))
        self.assertEqual(self.runner.calls[0][:3], ["systemctl", "--user", "is-active"])
        self.assertEqual(self.runner.calls[1], MANAGER_CALL)
        self.deactivate()

    def test_cli_passes_require_active_flag(self):
        with patch.object(session_env, "activate", return_value=True) as activation:
            self.assertEqual(session_env.main(["activate", "--require-active"]), 0)
        activation.assert_called_once_with(require_active=True)

    def test_malformed_manager_json_fails_closed_without_mutation(self):
        self.runner.busctl_output = "{not json\n"
        with self.assertRaisesRegex(session_env.Error, "malformed JSON"):
            self.activate()
        self.assertEqual(self.runner.calls, [MANAGER_CALL])
        self.assertFalse(self.state.exists())
        self.assertEqual(self.manager["QT_STYLE_OVERRIDE"], "OldStyle")

    def test_invalid_manager_json_shape_fails_closed(self):
        for payload in (
                json.dumps({"type": "aas", "data": [["QT_STYLE_OVERRIDE=x"]]}),
                json.dumps({"type": "as", "data": [{"bad": "shape"}]}),
                json.dumps({"type": "as", "data": ["NO_EQUALS_SIGN"]}),
        ):
            with self.subTest(payload=payload):
                self.runner.calls.clear()
                self.runner.busctl_output = payload
                with self.assertRaises(session_env.Error):
                    self.activate()
                self.assertEqual(self.runner.calls, [MANAGER_CALL])
                self.assertFalse(self.state.exists())

    def test_busctl_wrapped_array_form_is_accepted(self):
        entries = [f"{key}={value}" for key, value in self.manager.items()]
        self.runner.busctl_output = json.dumps({"type": "as", "data": [entries]})
        self.assertTrue(self.activate())
        self.assertEqual(self.manager["QT_STYLE_OVERRIDE"], "NiriGlass")
        self.assertTrue(self.deactivate())

    def test_gate_accepts_uppercase_niri_desktop_token(self):
        environment = dict(self.env)
        environment["XDG_CURRENT_DESKTOP"] = "NIRI:COSMIC"
        self.assertTrue(self.activate(environment))
        self.assertTrue(self.deactivate())
        self.assertFalse(self.state.exists())

    def test_manager_quotes_backslashes_spaces_and_empty_restore_exactly(self):
        original = {
            "QT_QPA_PLATFORM": 'wayland "quoted" \\backslash with spaces',
            "QT_STYLE_OVERRIDE": "",
        }
        self.manager.update(original)
        self.activate()
        baseline = self.state_document()["baseline"]
        self.assertEqual(baseline["QT_QPA_PLATFORM"], original["QT_QPA_PLATFORM"])
        self.assertEqual(baseline["QT_STYLE_OVERRIDE"], "")
        self.assertEqual(self.manager["QT_QPA_PLATFORM"], "wayland")
        self.assertEqual(self.manager["QT_STYLE_OVERRIDE"], "NiriGlass")
        self.deactivate()
        self.assertEqual(self.manager["QT_QPA_PLATFORM"], original["QT_QPA_PLATFORM"])
        self.assertEqual(self.manager["QT_STYLE_OVERRIDE"], "")

    def test_group_or_world_writable_runtime_dir_is_rejected(self):
        os.chmod(self.runtime, 0o775)
        with self.assertRaisesRegex(session_env.Error, "writable"):
            self.activate()
        self.assertEqual(self.runner.calls, [])
        self.assertFalse(self.state.exists())

        os.chmod(self.runtime, 0o755)
        self.assertTrue(self.activate())
        self.assertTrue(self.deactivate())

        os.chmod(self.runtime, 0o777)
        with self.assertRaisesRegex(session_env.Error, "writable"):
            self.activate()

    def test_lock_wait_is_bounded_without_commands_or_state(self):
        self.state.parent.mkdir(mode=0o700)
        lock_path = self.state.parent / "session-env.lock"
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            started = time.monotonic()
            with patch.object(session_env, "LOCK_TIMEOUT", 0.1):
                with self.assertRaisesRegex(session_env.Error, "lock"):
                    self.activate()
            self.assertLess(time.monotonic() - started, 1.0)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        self.assertEqual(self.runner.calls, [])
        self.assertFalse(self.state.exists())

    def test_cli_whole_operation_budget_returns_nonzero(self):
        def stuck(**kwargs):
            time.sleep(0.5)

        stderr = io.StringIO()
        with patch.object(session_env, "CLI_TIMEOUT", 0.05), \
                patch.object(session_env, "activate", side_effect=stuck), \
                contextlib.redirect_stderr(stderr):
            self.assertEqual(session_env.main(["activate"]), 1)
        self.assertIn("timed out", stderr.getvalue())

    def test_prepare_captures_baseline_before_generator_unset_and_restores_it(self):
        self.manager["QT_QPA_PLATFORMTHEME_QT6"] = "qtengine"
        before = dict(self.manager)
        self.assertTrue(self.prepare())
        document = self.state_document()
        self.assertEqual(document["phase"], "prepared")
        self.assertEqual(document["installed"], {})
        self.assertEqual(document["pending"], {"manager": [], "dbus": []})
        self.assertEqual(document["baseline"]["QT_QPA_PLATFORMTHEME_QT6"], "qtengine")
        self.assertEqual(self.runner.calls, [MANAGER_CALL])
        self.assertEqual(self.manager, before)

        # A generator mutates the manager after the baseline capture.
        self.manager.pop("QT_QPA_PLATFORMTHEME_QT6")
        calls = len(self.runner.calls)
        self.assertTrue(self.prepare())
        self.assertEqual(len(self.runner.calls), calls)
        self.assertEqual(self.state_document()["baseline"]["QT_QPA_PLATFORMTHEME_QT6"],
                         "qtengine")

        self.activate()
        self.assertEqual(self.manager["QT_QPA_PLATFORMTHEME_QT6"], "qtengine")
        self.deactivate()
        self.assertEqual(self.manager["QT_QPA_PLATFORMTHEME_QT6"], "qtengine")
        self.assertEqual(self.manager, before)

    def test_prepared_failed_install_deactivate_has_no_environment_effect(self):
        before = dict(self.manager)
        self.prepare()
        calls = len(self.runner.calls)
        self.assertTrue(self.deactivate())
        self.assertFalse(self.state.exists())
        self.assertEqual(len(self.runner.calls), calls)
        self.assertEqual(self.manager, before)

    def test_prepare_then_failed_activation_deactivate_leaves_manager_untouched(self):
        before = dict(self.manager)
        self.prepare()
        self.runner.fail_set_contains = "QT_STYLE_OVERRIDE=NiriGlass"
        with self.assertRaisesRegex(session_env.Error, "set user systemd"):
            self.activate()
        self.assertEqual(self.manager, before)
        self.assertTrue(self.deactivate())
        self.assertFalse(self.state.exists())
        self.assertEqual(self.manager, before)

    def test_prepare_preserves_existing_active_installed_and_pending(self):
        self.activate()
        self.runner.fail_dbus_once = True
        with self.assertRaisesRegex(session_env.Error, "D-Bus"):
            self.deactivate()
        before_state = self.state_document()
        calls = len(self.runner.calls)
        self.assertTrue(self.prepare())
        self.assertEqual(self.state_document(), before_state)
        self.assertEqual(len(self.runner.calls), calls)
        self.assertTrue(self.deactivate())
        self.assertFalse(self.state.exists())

    def test_prepare_require_active_fails_before_capture(self):
        self.runner.niri_active = False
        with self.assertRaisesRegex(session_env.Error, "niri.service"):
            self.prepare(require_active=True)
        self.assertEqual(self.runner.calls[0][:3], ["systemctl", "--user", "is-active"])
        self.assertFalse(self.state.exists())
        self.assertEqual(self.manager["QT_STYLE_OVERRIDE"], "OldStyle")

    def test_cli_prepare_passes_require_active_flag(self):
        with patch.object(session_env, "prepare", return_value=True) as preparation:
            self.assertEqual(session_env.main(["prepare", "--require-active"]), 0)
        preparation.assert_called_once_with(require_active=True)

    def test_public_state_helpers_are_read_only(self):
        self.assertEqual(session_env.LAUNCHER, "niri-theme-session-env")
        self.assertEqual(session_env.STATE_NAME, "session-env.json")
        self.assertEqual(session_env.state_path(self.env), self.state)
        self.assertFalse(session_env.is_active(self.env))
        self.assertFalse(self.state.parent.exists())
        self.activate()
        self.assertTrue(session_env.state_path(self.env).is_file())
        self.assertTrue(session_env.is_active(self.env))
        self.deactivate()
        self.assertFalse(session_env.is_active(self.env))

    def test_reinstall_cleans_a_before_b_set_failure_and_deactivate_clears(self):
        before = dict(self.manager)
        self.activate()
        environment_b = dict(self.env)
        environment_b["QT_STYLE_OVERRIDE"] = "BGlass"
        environment_b["QT_QPA_PLATFORM"] = "xcb"
        self.runner.fail_set_contains = "QT_STYLE_OVERRIDE=BGlass"
        with self.assertRaisesRegex(session_env.Error, "set user systemd"):
            self.activate(environment_b)
        # Previous A was cleaned to the initial baseline before B's failed set.
        self.assertEqual(self.manager, before)
        document = self.state_document()
        self.assertEqual(document["installed"]["QT_STYLE_OVERRIDE"], "BGlass")
        self.assertEqual(document["baseline"]["QT_STYLE_OVERRIDE"], "OldStyle")
        self.assertTrue(self.deactivate())
        self.assertFalse(self.state.exists())
        self.assertEqual(self.manager, before)

    def test_reactivation_failure_preserves_prior_pending_dbus_obligation(self):
        self.activate()
        self.runner.fail_dbus_once = True
        with self.assertRaisesRegex(session_env.Error, "D-Bus"):
            self.deactivate()
        before_state = self.state_document()
        before_manager = dict(self.manager)
        self.assertTrue(before_state["pending"]["dbus"])

        environment_b = dict(self.env)
        environment_b["QT_STYLE_OVERRIDE"] = "BGlass"
        self.runner.fail_dbus_once = True
        with self.assertRaisesRegex(session_env.Error, "D-Bus"):
            self.activate(environment_b)
        # Cleanup failed: the old journal must be intact, not replaced by B.
        self.assertEqual(self.state_document(), before_state)
        self.assertEqual(self.manager, before_manager)
        self.assertNotEqual(self.manager.get("QT_STYLE_OVERRIDE"), "BGlass")

        self.assertTrue(self.deactivate())
        self.assertFalse(self.state.exists())

    def test_manager_search_priority_survives_installer_default_roots(self):
        session_env.activate(self.env,self.runner)
        self.assertEqual(self.manager['XDG_DATA_DIRS'],
                         f'{self.theme}/share:/manager/share:/usr/share:/usr/local/share')
        self.assertEqual(self.manager['XDG_CONFIG_DIRS'],
                         f'{self.theme}/config:/manager/config:/etc/xdg')
        session_env.deactivate(self.env,self.runner)
        self.assertEqual(self.manager['XDG_DATA_DIRS'],'/manager/share:/usr/share')


if __name__ == "__main__":
    unittest.main()

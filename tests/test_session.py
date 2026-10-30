"""Hermetic tests: the user manager and exec are always mocked."""
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

from themekit import session


class FakeManager:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.calls = []
        self.failures = []

    def fail(self, operation, *, after=0):
        self.failures.append((operation, after))

    def __call__(self, arguments):
        self.calls.append(list(arguments))
        operation, *items = arguments
        failure = None
        if self.failures and self.failures[0][0] == operation:
            _, failure = self.failures.pop(0)
        if failure == 0:
            raise session.SessionError("injected manager failure")
        if operation == "show-environment":
            return "".join(f"{k}={shlex.quote(v)}\n" for k, v in sorted(self.values.items()))
        if operation not in {"set-environment", "unset-environment"}:
            raise AssertionError(arguments)
        for index, item in enumerate(items, 1):
            if operation == "set-environment":
                name, sep, value = item.partition("=")
                assert sep
                self.values[name] = value
            else:
                assert "=" not in item, "unset-environment requires bare names"
                self.values.pop(item, None)
            if failure == index:
                raise session.SessionError("injected partial manager failure")
        return ""


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.env_file = self.root / "profile.env"
        self.env_file.write_text('QT_QPA_PLATFORMTHEME="qt6ct"\nNIRI_DMS_THEME_PROFILE="dark"\n', encoding="utf-8")
        self.environment = mock.patch.dict(os.environ, {
            "XDG_RUNTIME_DIR": str(self.root), "XDG_CURRENT_DESKTOP": "GNOME:niri",
            "INVOCATION_ID": "session-a", "PATH": "/usr/bin", "DISPLAY": ":42",
        }, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.manager = FakeManager()
        self.runner = mock.patch.object(session, "run_manager", self.manager)
        self.runner.start()
        self.addCleanup(self.runner.stop)

    @property
    def state_path(self):
        return self.root / "niri-dms-theme" / "manager-state.json"

    def write_env(self, text):
        self.env_file.write_text(text, encoding="utf-8")

    def enter(self, **kwargs):
        return session.manager_enter(str(self.env_file), **kwargs)

    def test_parser_literals_and_quotes(self):
        self.write_env('# comment\n\nKEY="literal $HOME $(touch /no) `whoami` ; &"\n'
                       'EMPTY=""\nQUOTES="a\\"b\\\\c"\nHASH="# value"\n')
        self.assertEqual(session.parse_env_file(self.env_file), {
            "KEY": "literal $HOME $(touch /no) `whoami` ; &", "EMPTY": "",
            "QUOTES": 'a"b\\c', "HASH": "# value",
        })
        self.assertFalse(self.manager.calls)

    def test_parser_rejects_unsafe_or_ambiguous_records(self):
        for text in ['1BAD="x"', 'BAD-NAME="x"', 'export GOOD="x"', 'GOOD=x',
                     'GOOD="x"; touch /no', 'GOOD="x" # inline',
                     'GOOD="a\nb"', 'GOOD="a\rb"', 'GOOD="a\x00b"',
                     'GOOD="x"\nGOOD="y"', 'GOOD="x"$(echo nope)', 'GOOD="unterminated']:
            with self.subTest(text=text):
                self.write_env(text)
                with self.assertRaises(session.SessionError):
                    session.parse_env_file(self.env_file)

    def test_parser_rejects_missing_directory_invalid_utf8_and_large_files(self):
        for path in [self.root / "missing", self.root]:
            with self.assertRaises(session.SessionError):
                session.parse_env_file(path)
        self.env_file.write_bytes(b'KEY="\xff"')
        with self.assertRaises(session.SessionError):
            session.parse_env_file(self.env_file)
        self.env_file.write_bytes(b"#" * (session._MAX_FILE + 1))
        with self.assertRaises(session.SessionError):
            session.parse_env_file(self.env_file)

    def test_parser_rejects_fifo_without_blocking(self):
        fifo = self.root / "fifo"
        os.mkfifo(fifo, 0o600)
        with self.assertRaises(session.SessionError):
            session.parse_env_file(fifo)

    def test_exec_scopes_environment_and_preserves_argv(self):
        before = os.environ.copy()
        command = ["application", "argument with spaces", "$(not-a-shell)"]
        with mock.patch.object(session.os, "execvpe") as execute:
            self.assertEqual(session.main(["exec", "--env-file", str(self.env_file), "--", *command]), 0)
        executable, argv, environment = execute.call_args.args
        self.assertEqual(executable, "application")
        self.assertEqual(argv, command)
        self.assertEqual(environment["QT_QPA_PLATFORMTHEME"], "qt6ct")
        self.assertEqual(environment["DISPLAY"], ":42")
        self.assertEqual(os.environ, before)
        self.assertFalse(self.manager.calls)

    def test_exec_requires_current_niri_not_file_claim(self):
        os.environ["XDG_CURRENT_DESKTOP"] = "GNOME"
        self.write_env('XDG_CURRENT_DESKTOP="niri"\n')
        with mock.patch.object(session.os, "execvpe") as execute:
            with self.assertRaises(session.SessionError):
                session.exec_session(str(self.env_file), ["app"])
            execute.assert_not_called()
            session.exec_session(str(self.env_file), ["app"], allow_other_session=True)
            execute.assert_called_once()

    def test_desktop_is_colon_delimited_not_substring(self):
        for desktop, expected in [("niri", True), ("NIRI:GNOME", True),
                                  ("notniri", False), ("niri-other", False), ("", False)]:
            os.environ["XDG_CURRENT_DESKTOP"] = desktop
            self.assertEqual(session.in_niri_session(), expected)

    def test_exec_requires_separator_and_command(self):
        with mock.patch.object(session.os, "execvpe") as execute, contextlib.redirect_stderr(io.StringIO()):
            for tail in [["app"], ["--"], []]:
                self.assertEqual(session.main(["exec", "--env-file", str(self.env_file), *tail]), 1)
            execute.assert_not_called()

    def test_status_never_calls_manager(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(session.main(["status"]), 0)
        self.assertTrue(json.loads(output.getvalue())["niri_session"])
        self.assertFalse(self.manager.calls)

    def test_enter_leave_restores_values_and_unset_with_bare_names(self):
        self.manager.values = {"QT_QPA_PLATFORMTHEME": "old theme 'quoted' $HOME", "DISPLAY": ":7"}
        original = self.manager.values.copy()
        self.enter()
        self.assertEqual(self.manager.values[session.OWNER_KEY], "session-a")
        self.assertEqual(self.manager.values["QT_QPA_PLATFORMTHEME"], "qt6ct")
        state = json.loads(self.state_path.read_text())
        self.assertIsNone(state["before"]["NIRI_DMS_THEME_PROFILE"])
        self.assertEqual(state["before"]["QT_QPA_PLATFORMTHEME"], original["QT_QPA_PLATFORMTHEME"])
        session.manager_leave()
        self.assertEqual(self.manager.values, original)
        self.assertFalse(self.state_path.exists())
        for call in self.manager.calls:
            if call[0] == "unset-environment":
                self.assertTrue(all("=" not in name for name in call[1:]))

    def test_bridge_allowlist_excludes_desktop_display_and_arbitrary_variables(self):
        self.write_env('DISPLAY=":999"\nXDG_CURRENT_DESKTOP="GNOME"\n'
                       'MALICIOUS="ignored"\nQT_QPA_PLATFORMTHEME="qt6ct"\n'
                       'QTENGINE_CONFIG="/tmp/settings"\nQT_PLUGIN_PATH="/tmp/plugins"\n'
                       'QT_STYLE_OVERRIDE="kvantum"\nXDG_DATA_DIRS="/one:/two"\n')
        self.manager.values = {"DISPLAY": ":7", "XDG_CURRENT_DESKTOP": "niri"}
        self.enter()
        self.assertEqual(self.manager.values["DISPLAY"], ":7")
        self.assertEqual(self.manager.values["XDG_CURRENT_DESKTOP"], "niri")
        self.assertNotIn("MALICIOUS", self.manager.values)
        self.assertEqual(self.manager.values["QTENGINE_CONFIG"], "/tmp/settings")
        self.assertEqual(self.manager.values["QT_PLUGIN_PATH"], "/tmp/plugins")
        self.assertEqual(self.manager.values["XDG_DATA_DIRS"], "/one:/two")

    def test_repeated_enter_is_idempotent_preserves_original_snapshot_and_drift(self):
        self.manager.values["QT_QPA_PLATFORMTHEME"] = "original"
        self.enter()
        original = self.state_path.read_bytes()
        self.manager.values["QT_QPA_PLATFORMTHEME"] = "foreign-edit"
        self.manager.calls.clear()
        self.assertTrue(self.enter()["already_active"])
        self.assertEqual(self.state_path.read_bytes(), original)
        self.assertEqual(self.manager.values["QT_QPA_PLATFORMTHEME"], "foreign-edit")
        self.assertEqual(self.manager.calls, [["show-environment"]])

    def test_repeated_owner_cannot_replace_original_with_new_environment(self):
        self.enter()
        original = self.state_path.read_bytes()
        self.write_env('QT_QPA_PLATFORMTHEME="other"\n')
        with self.assertRaises(session.SessionError):
            self.enter()
        self.assertEqual(self.state_path.read_bytes(), original)

    def test_foreign_enter_and_leave_refuse_without_mutation(self):
        self.enter()
        original = self.manager.values.copy()
        state = self.state_path.read_bytes()
        for action in [lambda: self.enter(owner="other-session"),
                       lambda: session.manager_leave(owner="other-session")]:
            with self.assertRaises(session.SessionError):
                action()
            self.assertEqual(self.manager.values, original)
            self.assertEqual(self.state_path.read_bytes(), state)

    def test_foreign_manager_marker_refuses_even_for_same_snapshot_owner(self):
        self.enter()
        self.manager.values[session.OWNER_KEY] = "other-session"
        original = self.manager.values.copy()
        for action in [self.enter, session.manager_leave]:
            with self.assertRaises(session.SessionError):
                action()
            self.assertEqual(self.manager.values, original)
        self.assertTrue(self.state_path.exists())

    def test_orphan_manager_marker_refuses(self):
        self.manager.values[session.OWNER_KEY] = "foreign-session"
        with self.assertRaises(session.SessionError):
            self.enter()
        with self.assertRaises(session.SessionError):
            session.manager_leave()
        self.assertEqual(self.manager.values, {session.OWNER_KEY: "foreign-session"})

    def test_leave_preserves_drift_and_foreign_unsets(self):
        self.manager.values["QT_QPA_PLATFORMTHEME"] = "original"
        self.enter()
        self.manager.values["QT_QPA_PLATFORMTHEME"] = "foreign-value"
        self.manager.values.pop("NIRI_DMS_THEME_PROFILE")
        result = session.manager_leave()
        self.assertEqual(result["preserved"], ["NIRI_DMS_THEME_PROFILE", "QT_QPA_PLATFORMTHEME"])
        self.assertEqual(self.manager.values, {"QT_QPA_PLATFORMTHEME": "foreign-value"})

    def test_leave_is_idempotent_without_state(self):
        self.assertFalse(session.manager_leave()["active"])
        self.assertFalse(session.manager_leave()["active"])

    def test_manager_requires_niri_even_with_owner(self):
        os.environ["XDG_CURRENT_DESKTOP"] = "GNOME"
        for action in [lambda: self.enter(owner="explicit"),
                       lambda: session.manager_leave(owner="explicit")]:
            with self.assertRaises(session.SessionError):
                action()
        self.assertFalse(self.manager.calls)

    def test_owner_required_and_validated(self):
        os.environ.pop("INVOCATION_ID")
        for token in [None, "", "bad\nowner", "bad owner", "x" * 257]:
            with self.assertRaises(session.SessionError):
                self.enter(owner=token)
        self.enter(owner="explicit:owner-1")
        self.assertEqual(self.manager.values[session.OWNER_KEY], "explicit:owner-1")

    def test_runtime_modes(self):
        self.enter()
        for path, expected in [(self.state_path.parent, 0o700), (self.state_path, 0o600),
                               (self.state_path.parent / "manager.lock", 0o600)]:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), expected)

    def test_refuse_symlinked_runtime_directory(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        os.environ["XDG_RUNTIME_DIR"] = str(alias)
        with self.assertRaises(session.SessionError):
            self.enter()
        self.assertFalse(self.manager.calls)

    def test_refuse_symlinked_state_and_lock_without_touching_targets(self):
        directory = self.root / "niri-dms-theme"
        directory.mkdir(mode=0o700)
        victim = self.root / "victim"
        victim.write_text("untouched")
        for name in ["manager.lock", "manager-state.json"]:
            with self.subTest(name=name):
                path = directory / name
                path.symlink_to(victim)
                with self.assertRaises(session.SessionError):
                    self.enter()
                self.assertEqual(victim.read_text(), "untouched")
                self.assertTrue(path.is_symlink())
                # Test fixture cleanup only, after confirming its exact target.
                self.assertEqual(path.resolve(), victim)
                path.unlink()

    def test_refuse_nonprivate_runtime_directory_and_state(self):
        self.root.chmod(0o755)
        with self.assertRaises(session.SessionError):
            self.enter()
        self.root.chmod(0o700)
        self.enter()
        self.state_path.chmod(0o644)
        with self.assertRaises(session.SessionError):
            session.manager_leave()

    def test_enter_failed_marker_acquisition_cleans_snapshot(self):
        self.manager.fail("set-environment")
        with self.assertRaisesRegex(session.SessionError, "rolled back"):
            self.enter()
        self.assertEqual(self.manager.values, {})
        self.assertFalse(self.state_path.exists())

    def test_enter_partial_import_rolls_back_original_values(self):
        self.manager.values = {"NIRI_DMS_THEME_PROFILE": "old", "QT_QPA_PLATFORMTHEME": "old-qt"}
        original = self.manager.values.copy()
        # Marker succeeds, import applies the first sorted key and then fails.
        original_runner = self.manager
        # Fail only the first multi-key set, not rollback.
        armed = [True]
        def once(args):
            if armed[0] and args[0] == "set-environment" and len(args) > 2:
                armed[0] = False
                self.manager.fail("set-environment", after=1)
            return original_runner(args)
        with mock.patch.object(session, "run_manager", once):
            with self.assertRaisesRegex(session.SessionError, "rolled back"):
                self.enter()
        self.assertEqual(self.manager.values, original)
        self.assertFalse(self.state_path.exists())

    def test_failed_rollback_retains_recoverable_owned_snapshot(self):
        original_runner = self.manager
        armed = [True]
        def runner(args):
            if armed[0] and args[0] == "set-environment" and len(args) > 2:
                armed[0] = False
                self.manager.fail("set-environment", after=1)
                self.manager.fail("unset-environment")
            return original_runner(args)
        with mock.patch.object(session, "run_manager", runner):
            with self.assertRaisesRegex(session.SessionError, "rollback incomplete"):
                self.enter()
        self.assertTrue(self.state_path.exists())
        self.assertEqual(self.manager.values[session.OWNER_KEY], "session-a")
        with self.assertRaisesRegex(session.SessionError, "incomplete"):
            self.enter()
        session.manager_leave()
        self.assertEqual(self.manager.values, {})
        self.assertFalse(self.state_path.exists())

    def test_failed_leave_set_retains_state_for_retry(self):
        self.manager.values = {"QT_QPA_PLATFORMTHEME": "original"}
        self.enter()
        self.manager.fail("set-environment")
        with self.assertRaises(session.SessionError):
            session.manager_leave()
        self.assertTrue(self.state_path.exists())
        self.assertEqual(self.manager.values[session.OWNER_KEY], "session-a")
        session.manager_leave()
        self.assertEqual(self.manager.values, {"QT_QPA_PLATFORMTHEME": "original"})

    def test_failed_leave_unset_retains_state_for_retry(self):
        self.enter()
        self.manager.fail("unset-environment", after=1)
        with self.assertRaises(session.SessionError):
            session.manager_leave()
        self.assertTrue(self.state_path.exists())
        self.assertEqual(self.manager.values[session.OWNER_KEY], "session-a")
        session.manager_leave()
        self.assertEqual(self.manager.values, {})

    def test_marker_unset_applied_then_failed_can_finish_cleanup(self):
        self.enter()
        original_runner = self.manager
        def runner(args):
            if args == ["unset-environment", session.OWNER_KEY]:
                self.manager.fail("unset-environment", after=1)
            return original_runner(args)
        with mock.patch.object(session, "run_manager", runner):
            with self.assertRaises(session.SessionError):
                session.manager_leave()
        self.assertEqual(self.manager.values, {})
        self.assertEqual(json.loads(self.state_path.read_text())["phase"], "restored")
        session.manager_leave()
        self.assertFalse(self.state_path.exists())
        self.assertEqual(self.manager.values, {})

    def test_show_failure_does_not_mutate(self):
        self.manager.fail("show-environment")
        with self.assertRaises(session.SessionError):
            self.enter()
        self.assertFalse(self.state_path.exists())
        self.assertEqual(self.manager.values, {})

    def test_invalid_state_cannot_inject_unset_names(self):
        self.enter()
        state = json.loads(self.state_path.read_text())
        state["installed"]["DISPLAY"] = "bad"
        state["before"]["DISPLAY"] = None
        self.state_path.write_text(json.dumps(state))
        original = self.manager.values.copy()
        with self.assertRaises(session.SessionError):
            session.manager_leave()
        self.assertEqual(self.manager.values, original)

    def test_invalid_utf8_snapshot_refuses_without_mutation(self):
        self.enter()
        self.state_path.write_bytes(b"\\xff")
        original = self.manager.values.copy()
        with self.assertRaises(session.SessionError):
            session.manager_leave()
        self.assertEqual(self.manager.values, original)

    def test_subprocess_boundary_uses_argv_no_shell(self):
        self.runner.stop()
        completed = subprocess.CompletedProcess([], 0, stdout="KEY=value\n", stderr="")
        with mock.patch.object(session.subprocess, "run", return_value=completed) as run:
            self.assertEqual(session.run_manager(["set-environment", "KEY=$(danger) ; x"]), "KEY=value\n")
        argv = run.call_args.args[0]
        self.assertEqual(argv, ["systemctl", "--user", "set-environment", "KEY=$(danger) ; x"])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_subprocess_failure_is_session_error(self):
        self.runner.stop()
        with mock.patch.object(session.subprocess, "run", side_effect=FileNotFoundError("no systemctl")):
            with self.assertRaises(session.SessionError):
                session.run_manager(["show-environment"])


if __name__ == "__main__":
    unittest.main()

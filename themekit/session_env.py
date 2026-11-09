#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""One-shot Niri-session Qt environment activation.

This file is deliberately standalone: the installer copies it to
``bin/niri-theme-session-env`` and it must not import the themekit package.

Deactivation restores only owned values that still equal the installed values,
so later manager changes survive.  A private per-store journal records pending
manager and D-Bus restores, allowing retries even after the manager already
matches its baseline.  ``dbus-update-activation-environment`` has no query or
unset operation: originally-unset keys are restored with an empty value, not
removed, and an old activation environment can persist until logout or reboot.
Exact D-Bus baseline restoration is therefore not promised.  The private
runtime state file is removed only after cleanup commands succeed; the runtime
state directory, lock and all application data are left alone.  Reactivation
first finishes any prior cleanup under the same lock, avoiding a new journal
that would misclassify old installed values; this briefly restores the initial
baseline during an explicit reinstall.  `prepare` is the read-only capture used
before installer writes or generator reload; a prepared journal is discarded
without touching either store, and activation consumes its captured baseline.

Manager state is read as structured busctl JSON from Manager.Environment, so
shell and ANSI-C quoting are never parsed.  The lock, individual commands, and
the CLI as a whole are deadline-bounded.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time

OWNED_KEYS = (
    "QT_QPA_PLATFORM",
    "QT_QPA_PLATFORMTHEME",
    "QT_QPA_PLATFORMTHEME_QT6",
    "QT_STYLE_OVERRIDE",
    "QTENGINE_CONFIG",
    "QT_PLUGIN_PATH",
    "XDG_CONFIG_DIRS",
    "XDG_DATA_DIRS",
    "NIRI_DMS_THEME_PROFILE",
    "NIRI_DMS_THEME_CONFIG_HOME",
    "NIRI_DMS_THEME_DATA_HOME",
)
PREFIXED_KEYS = frozenset(("QT_PLUGIN_PATH", "XDG_CONFIG_DIRS", "XDG_DATA_DIRS"))
ABSOLUTE_VALUE_KEYS = frozenset((
    "QTENGINE_CONFIG", "NIRI_DMS_THEME_CONFIG_HOME", "NIRI_DMS_THEME_DATA_HOME",
))
PROFILE_MARKER = "niri-dms-glass"
LAUNCHER = "niri-theme-session-env"
STATE_DIRNAME = "niri-dms-theme"
STATE_FILENAME = "session-env.json"
STATE_NAME = STATE_FILENAME
STATE_VERSION = 3
LOCK_FILENAME = "session-env.lock"
MAX_STATE_BYTES = 64 * 1024
LOCK_TIMEOUT = 2.0
COMMAND_TIMEOUT = 3.0
CLI_TIMEOUT = 10.0
_LOCK = threading.Lock()


class Error(Exception):
    """A refused or failed activation/cleanup operation."""


class _CliDeadline(Error):
    """The whole CLI budget expired; leave durable state for a retry."""


def _euid():
    return os.geteuid() if hasattr(os, "geteuid") else os.getuid()


def _bad_value(value):
    return not isinstance(value, str) or any(char in value for char in "\r\n\x00")


def _absolute_path(value, label):
    if not isinstance(value, str) or not value or _bad_value(value):
        raise Error(f"{label} must be a non-empty absolute path")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise Error(f"{label} must be a non-empty absolute path without '..'")
    return path


def _path_list(value, label):
    if not isinstance(value, str) or not value or _bad_value(value):
        raise Error(f"{label} must be a colon-separated list of absolute paths")
    entries = value.split(":")
    if any(not entry for entry in entries):
        raise Error(f"{label} contains an empty path")
    for entry in entries:
        _absolute_path(entry, label)
    return entries


def _validate_desired(environment):
    desktop = environment.get("XDG_CURRENT_DESKTOP")
    if not isinstance(desktop, str) or "niri" not in desktop.lower().split(":"):
        raise Error("activate requires an XDG_CURRENT_DESKTOP token of 'niri'")
    if environment.get("NIRI_DMS_THEME_PROFILE") != PROFILE_MARKER:
        raise Error(f"activate requires NIRI_DMS_THEME_PROFILE={PROFILE_MARKER}")
    desired = {}
    for key in OWNED_KEYS:
        if key not in environment:
            raise Error(f"missing required environment key: {key}")
        value = environment[key]
        if _bad_value(value):
            raise Error(f"invalid environment value for {key}")
        if not value:
            raise Error(f"environment value for {key} cannot be empty")
        if key in ABSOLUTE_VALUE_KEYS:
            _absolute_path(value, key)
        elif key in PREFIXED_KEYS:
            _path_list(value, key)
        desired[key] = value
    return desired


def _runtime_dir(environment):
    raw = environment.get("XDG_RUNTIME_DIR")
    runtime = _absolute_path(raw, "XDG_RUNTIME_DIR")
    try:
        info = os.lstat(runtime)
    except OSError as exc:
        raise Error(f"XDG_RUNTIME_DIR is unavailable: {runtime}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise Error("XDG_RUNTIME_DIR must be a real directory, not a symlink")
    if info.st_uid != _euid():
        raise Error("XDG_RUNTIME_DIR is not owned by the current user")
    if info.st_mode & 0o022:
        raise Error("XDG_RUNTIME_DIR must not be group- or world-writable")
    return runtime


def _state_dir(environment, create):
    directory = _runtime_dir(environment) / STATE_DIRNAME
    try:
        if create:
            try:
                os.mkdir(directory, 0o700)
                os.chmod(directory, 0o700)
            except FileExistsError:
                pass
        elif not os.path.lexists(directory):
            return None
        info = os.lstat(directory)
    except OSError as exc:
        raise Error(f"cannot inspect state directory: {directory}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise Error("state path must be a real directory, not a symlink or node")
    if info.st_uid != _euid():
        raise Error("state directory is owned by another user")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise Error("state directory must have mode 0700")
    return directory


def _state_path(environment, create):
    directory = _state_dir(environment, create)
    return None if directory is None else directory / STATE_FILENAME


def state_path(environment=None):
    """Return the owned state path without creating its directory."""
    environment = os.environ if environment is None else environment
    directory = _state_dir(environment, create=False)
    if directory is None:
        directory = _runtime_dir(environment) / STATE_DIRNAME
    return directory / STATE_FILENAME


def is_active(environment=None):
    """Return whether owned activation state exists, without reading or changing it."""
    path = state_path(environment)
    return path is not None and os.path.lexists(path)


@contextlib.contextmanager
def _locked(directory):
    deadline = time.monotonic() + LOCK_TIMEOUT
    if not _LOCK.acquire(timeout=max(0.0, LOCK_TIMEOUT)):
        raise Error("timed out waiting for state lock")
    fd = None
    flocked = False
    try:
        lock_path = directory / LOCK_FILENAME
        try:
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600)
        except OSError as exc:
            raise Error("cannot open state lock") from exc
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != _euid():
            raise Error("state lock must be an owned regular file")
        os.fchmod(fd, 0o600)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                flocked = True
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Error("timed out waiting for state lock")
                time.sleep(min(0.05, remaining))
        yield
    finally:
        if fd is not None:
            try:
                if flocked:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
        _LOCK.release()


def _state_stat(path):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise Error("cannot inspect session environment state") from exc
    if stat.S_ISLNK(info.st_mode):
        raise Error("session environment state cannot be a symlink")
    if not stat.S_ISREG(info.st_mode):
        raise Error("session environment state must be a regular file")
    if info.st_uid != _euid():
        raise Error("session environment state is owned by another user")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise Error("session environment state must have mode 0600")
    if info.st_nlink != 1:
        raise Error("session environment state must not be hard-linked")
    return info


def _state_mapping(value, label, *, installed):
    if not isinstance(value, dict) or set(value) != set(OWNED_KEYS):
        raise Error(f"invalid {label} in session environment state")
    for key in OWNED_KEYS:
        item = value[key]
        if item is not None and _bad_value(item):
            raise Error(f"invalid {label} value for {key}")
        if installed and (not isinstance(item, str) or not item):
            raise Error(f"invalid installed value for {key}")
    return {key: value[key] for key in OWNED_KEYS}


def _pending_mapping(value):
    if not isinstance(value, dict) or set(value) != {"manager", "dbus"}:
        raise Error("invalid pending stores in session environment state")
    pending = {}
    for store in ("manager", "dbus"):
        keys = value[store]
        if (not isinstance(keys, list)
                or any(not isinstance(key, str) or key not in OWNED_KEYS for key in keys)
                or len(set(keys)) != len(keys)):
            raise Error(f"invalid pending {store} keys in session environment state")
        pending[store] = [key for key in OWNED_KEYS if key in set(keys)]
    return pending


def _load_state(path):
    info = _state_stat(path)
    if info is None:
        return None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise Error("cannot read session environment state") from exc
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise Error("session environment state changed while being opened")
        if opened.st_size > MAX_STATE_BYTES:
            raise Error("session environment state is too large")
        with os.fdopen(fd, "rb") as stream:
            fd = None
            raw = stream.read(MAX_STATE_BYTES + 1)
    finally:
        if fd is not None:
            os.close(fd)
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Error("session environment state is corrupt") from exc
    if (not isinstance(document, dict)
            or set(document) != {"version", "phase", "baseline", "installed", "pending"}):
        raise Error("invalid session environment state document")
    if type(document["version"]) is not int or document["version"] != STATE_VERSION:
        raise Error("unsupported session environment state version")
    phase = document["phase"]
    if phase not in ("prepared", "active"):
        raise Error("invalid phase in session environment state")
    pending = _pending_mapping(document["pending"])
    if phase == "prepared":
        if document["installed"] != {} or any(pending.values()):
            raise Error("prepared session environment state must have no installed values")
        installed = {}
    else:
        installed = _state_mapping(document["installed"], "installed", installed=True)
    return {
        "version": STATE_VERSION,
        "phase": phase,
        "baseline": _state_mapping(document["baseline"], "baseline", installed=False),
        "installed": installed,
        "pending": pending,
    }


def _fsync_directory(directory):
    try:
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_state(path, document):
    payload = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(payload) > MAX_STATE_BYTES:
        raise Error("session environment state is too large")
    try:
        fd, temporary = tempfile.mkstemp(prefix=".session-env-", dir=path.parent)
    except OSError as exc:
        raise Error("cannot create session environment state") from exc
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            fd = None
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if os.path.lexists(path):
            _state_stat(path)
        os.replace(temporary, path)
        temporary = None
        _fsync_directory(path.parent)
    except OSError as exc:
        raise Error("cannot write session environment state") from exc
    finally:
        if fd is not None:
            os.close(fd)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _failure_detail(error):
    if isinstance(error, subprocess.TimeoutExpired):
        return f"timed out after {error.timeout} seconds"
    text = getattr(error, "stderr", None) or getattr(error, "stdout", None) or str(error)
    text = str(text).strip().splitlines()
    return text[0][:240] if text else error.__class__.__name__


def _run(runner, arguments, action):
    try:
        result = runner(arguments, capture_output=True, text=True, check=True,
                        timeout=COMMAND_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Error(f"{action} failed: {_failure_detail(exc)}") from exc
    code = getattr(result, "returncode", 0)
    if code not in (0, None):
        raise Error(f"{action} failed: {_failure_detail(result)}")
    return result


def _output_text(result, action):
    output = result.stdout or ""
    if isinstance(output, bytes):
        output = output.decode("utf-8", "replace")
    if not isinstance(output, str):
        raise Error(f"{action} failed: invalid output")
    return output


def _manager_entries(document):
    if (not isinstance(document, dict) or set(document) != {"type", "data"}
            or document["type"] != "as"):
        raise Error("invalid Manager.Environment JSON")
    data = document["data"]
    if isinstance(data, list) and all(isinstance(item, str) for item in data):
        return data
    # busctl returns a flat array for type "as"; also accept its single wrapped form.
    if (isinstance(data, list) and len(data) == 1 and isinstance(data[0], list)
            and all(isinstance(item, str) for item in data[0])):
        return data[0]
    raise Error("invalid Manager.Environment JSON")


def _manager_values(entries):
    values = {}
    for entry in entries:
        if "=" not in entry:
            raise Error("invalid Manager.Environment entry")
        key, value = entry.split("=", 1)
        if key in OWNED_KEYS:
            if _bad_value(value):
                raise Error(f"invalid manager environment value for {key}")
            values[key] = value
    return values


def _read_manager(runner):
    result = _run(runner, [
        "busctl", "--user", "--json=short", "get-property",
        "org.freedesktop.systemd1", "/org/freedesktop/systemd1",
        "org.freedesktop.systemd1.Manager", "Environment",
    ], "read user systemd environment")
    output = _output_text(result, "read user systemd environment")
    try:
        document = json.loads(output)
    except ValueError as exc:
        raise Error("read user systemd environment failed: malformed JSON") from exc
    return _manager_values(_manager_entries(document))


def _merged(desired, manager):
    final = {}
    for key in OWNED_KEYS:
        if key in PREFIXED_KEYS:
            entries = []
            current = manager.get(key)
            owned, *defaults = desired[key].split(":")
            # Preserve manager search order behind the owned prefix, before
            # adding any remaining installer-time default roots.
            for value in (owned, current or "", ":".join(defaults)):
                for entry in value.split(":"):
                    if entry and entry not in entries:
                        entries.append(entry)
            final[key] = ":".join(entries)
        else:
            final[key] = desired[key]
    return final


def _set_manager(runner, values, action):
    assignments = [f"{key}={values[key]}" for key in OWNED_KEYS if key in values]
    if assignments:
        _run(runner, ["systemctl", "--user", "set-environment", *assignments], action)


def _set_dbus(runner, values, action):
    assignments = [f"{key}={values[key]}" for key in OWNED_KEYS if key in values]
    if assignments:
        _run(runner, ["dbus-update-activation-environment", *assignments], action)


def _restore_manager(runner, keys, baseline):
    selected = [key for key in OWNED_KEYS if key in keys]
    to_set = [key for key in selected if baseline[key] is not None]
    to_unset = [key for key in selected if baseline[key] is None]
    if to_set:
        assignments = [f"{key}={baseline[key]}" for key in to_set]
        _run(runner, ["systemctl", "--user", "set-environment", *assignments],
             "restore user systemd environment")
    if to_unset:
        _run(runner, ["systemctl", "--user", "unset-environment", *to_unset],
             "restore user systemd environment")


def _restore_dbus(runner, keys, baseline):
    selected = [key for key in OWNED_KEYS if key in keys]
    if not selected:
        return
    assignments = [f"{key}={baseline[key] if baseline[key] is not None else ''}"
                   for key in selected]
    _run(runner, ["dbus-update-activation-environment", *assignments],
         "restore D-Bus activation environment")


def _rollback(runner, installed, baseline):
    current = _read_manager(runner)
    ours = {key for key in OWNED_KEYS if current.get(key) == installed[key]}
    _restore_manager(runner, ours, baseline)


def _require_niri_active(runner):
    try:
        _run(runner, ["systemctl", "--user", "is-active", "--quiet", "niri.service"],
             "check Niri service")
    except Error as exc:
        raise Error(f"activation requires active niri.service: {exc}") from exc


def _remove_state(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise Error("cannot remove session environment state") from exc
    _fsync_directory(path.parent)


def _locked_cleanup(path, state, runner):
    """Finish cleanup for a previously loaded active state.

    The caller holds the state lock.  Each successful store is journaled
    before the next begins, and the state file is removed only after both
    stores finish.  Raise without removing state on any failure.
    """
    if state["phase"] != "active":
        raise Error("cleanup requires active session environment state")
    manager = _read_manager(runner)
    installed = state["installed"]
    baseline = state["baseline"]
    pending = {store: set(state["pending"][store]) for store in ("manager", "dbus")}
    for key in OWNED_KEYS:
        current = manager.get(key)
        if current == installed[key]:
            pending["manager"].add(key)
            pending["dbus"].add(key)
        elif current == baseline[key]:
            pending["manager"].discard(key)
        else:
            # A later manager change is a conflict: never overwrite it or D-Bus.
            pending["manager"].discard(key)
            pending["dbus"].discard(key)
    previous = state["pending"]
    state["pending"] = {
        store: [key for key in OWNED_KEYS if key in pending[store]]
        for store in ("manager", "dbus")
    }
    if state["pending"] != previous:
        _write_state(path, state)
    if state["pending"]["manager"]:
        _restore_manager(runner, state["pending"]["manager"], baseline)
        state["pending"]["manager"] = []
        _write_state(path, state)
    if state["pending"]["dbus"]:
        _restore_dbus(runner, state["pending"]["dbus"], baseline)
        state["pending"]["dbus"] = []
        _write_state(path, state)
    _remove_state(path)


def prepare(environment=None, runner=None, require_active=False):
    """Capture the pre-mutation manager baseline without changing any store.

    Repeated calls and calls made while an active plan exists preserve the
    existing baseline, installed values and pending journal.  A prepared state
    has no installed values and can only be discarded, never applied.
    """
    environment = os.environ if environment is None else environment
    _validate_desired(environment)
    runner = subprocess.run if runner is None else runner
    path = _state_path(environment, create=True)
    with _locked(path.parent):
        if require_active:
            _require_niri_active(runner)
        if _load_state(path) is not None:
            return True
        manager = _read_manager(runner)
        document = {
            "version": STATE_VERSION,
            "phase": "prepared",
            "baseline": {key: manager.get(key) for key in OWNED_KEYS},
            "installed": {},
            "pending": {"manager": [], "dbus": []},
        }
        _write_state(path, document)
    return True


def activate(environment=None, runner=None, require_active=False):
    """Activate the fixed Niri Qt profile, returning True on success.

    A previous activation is cleaned to its initial baseline under the same
    lock before any new transition state is written.  If that cleanup fails,
    reactivation aborts and the old journal remains intact for retry.
    """
    environment = os.environ if environment is None else environment
    desired = _validate_desired(environment)
    runner = subprocess.run if runner is None else runner
    path = _state_path(environment, create=True)
    with _locked(path.parent):
        if require_active:
            _require_niri_active(runner)
        previous = _load_state(path)
        baseline = dict(previous["baseline"]) if previous is not None else None
        if previous is not None and previous["phase"] == "active":
            _locked_cleanup(path, previous, runner)
        manager = _read_manager(runner)
        if baseline is None:
            baseline = {key: manager.get(key) for key in OWNED_KEYS}
        installed = _merged(desired, manager)
        document = {
            "version": STATE_VERSION,
            "phase": "active",
            "baseline": baseline,
            "installed": installed,
            "pending": {"manager": list(OWNED_KEYS), "dbus": []},
        }
        # Durable per-store journal, written before either store is changed.
        _write_state(path, document)
        try:
            _set_manager(runner, installed, "set user systemd environment")
        except _CliDeadline:
            raise
        except Error:
            try:
                _rollback(runner, installed, baseline)
                document["pending"]["manager"] = []
                _write_state(path, document)
            except Error:
                pass
            raise
        document["pending"] = {"manager": [], "dbus": list(OWNED_KEYS)}
        _write_state(path, document)
        try:
            _set_dbus(runner, installed, "set D-Bus activation environment")
        except _CliDeadline:
            raise
        except Error:
            try:
                _rollback(runner, installed, baseline)
            except Error:
                pass
            raise
        document["pending"]["dbus"] = []
        _write_state(path, document)
    return True


def deactivate(environment=None, runner=None):
    """Restore owned installed values, journaling each store for retries.

    A prepared-only state has no applied values, so it is discarded without
    touching the manager or D-Bus.  Manager conflicts are preserved and never
    receive a D-Bus baseline write.
    Each successful store is cleared in the journal before the next begins.
    No exact D-Bus baseline is promised; originally-unset keys become empty.
    """
    environment = os.environ if environment is None else environment
    runner = subprocess.run if runner is None else runner
    path = _state_path(environment, create=False)
    if path is None:
        return False
    with _locked(path.parent):
        state = _load_state(path)
        if state is None:
            return False
        if state["phase"] == "prepared":
            _remove_state(path)
        else:
            _locked_cleanup(path, state, runner)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="niri-theme-session-env",
        description="One-shot Niri session Qt environment activation.",
    )
    parser.add_argument("action", choices=("prepare", "activate", "deactivate"))
    parser.add_argument("--require-active", action="store_true",
                        help="prepare/activate only while niri.service is active")
    args = parser.parse_args(argv)
    if args.require_active and args.action == "deactivate":
        parser.error("--require-active does not apply to deactivate")

    def expire(_signum, _frame):
        raise _CliDeadline("operation timed out")

    armed = False
    previous = None
    if hasattr(signal, "setitimer") and threading.current_thread() is threading.main_thread():
        previous = signal.signal(signal.SIGALRM, expire)
        signal.setitimer(signal.ITIMER_REAL, CLI_TIMEOUT)
        armed = True
    try:
        if args.action == "prepare":
            prepare(require_active=args.require_active)
        elif args.action == "activate":
            activate(require_active=args.require_active)
        else:
            deactivate()
    except Error as exc:
        print(f"niri-theme-session-env: {exc}", file=sys.stderr)
        return 1
    finally:
        if armed:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

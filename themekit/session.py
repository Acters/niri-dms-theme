"""Process-local theme environment, with an opt-in legacy user-manager bridge.

Only the explicit manager-* commands mutate the systemd user manager.  Nothing
in this module imports a D-Bus activation environment or evaluates shell code.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tempfile
from typing import Iterator

MANAGER_KEYS = frozenset({
    "QT_QPA_PLATFORMTHEME", "QT_QPA_PLATFORMTHEME_QT5", "QT_QPA_PLATFORMTHEME_QT6",
    "QTENGINE_CONFIG", "QT_PLUGIN_PATH", "QT_STYLE_OVERRIDE",
    "NIRI_DMS_THEME_PROFILE", "XDG_DATA_DIRS",
})
OWNER_KEY = "NIRI_DMS_THEME_MANAGER_OWNER"
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_ASSIGNMENT = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)=("(?:[^"\\]|\\.)*")\Z')
_MAX_FILE = 1024 * 1024
_MAX_STATE = 16 * _MAX_FILE  # Original + installed values, including JSON escaping.


class SessionError(RuntimeError):
    """An invalid environment or an unsafe/failed manager operation."""


def _value(value: object) -> str:
    if not isinstance(value, str) or any(c in value for c in "\x00\r\n"):
        raise SessionError("environment values must be strings without NUL or newlines")
    return value


def parse_env_file(filename: str | os.PathLike[str]) -> dict[str, str]:
    """Read KEY=\"literal\" records with shlex, without variable expansion.

    Empty lines and whole-line comments are allowed.  Duplicate keys, unquoted
    assignments, shell syntax outside the quoted value, and multiline values
    are rejected.  Dollar signs and backticks inside a value are just data.
    """
    path = Path(filename)
    try:
        # O_NONBLOCK prevents a FIFO masquerading as an env file from hanging.
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise SessionError("environment file must be a regular file")
            raw = stream.read(_MAX_FILE + 1)
        if len(raw) > _MAX_FILE:
            raise SessionError("environment file is too large")
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise SessionError(f"cannot read environment file {path}: {exc}") from exc
    if "\x00" in text or "\r" in text:
        raise SessionError("environment file contains NUL or carriage return")
    result: dict[str, str] = {}
    for number, raw_line in enumerate(text.split("\n"), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ASSIGNMENT.fullmatch(line)
        if not match:
            raise SessionError(f"invalid quoted assignment at line {number}")
        name = match[1]
        if name in result:
            raise SessionError(f"duplicate environment name at line {number}: {name}")
        try:
            words = shlex.split(line, comments=False, posix=True)
        except ValueError as exc:
            raise SessionError(f"invalid quoting at line {number}: {exc}") from exc
        if len(words) != 1 or not words[0].startswith(name + "="):
            raise SessionError(f"invalid assignment at line {number}")
        result[name] = _value(words[0][len(name) + 1:])
    return result


def in_niri_session() -> bool:
    """XDG_CURRENT_DESKTOP is a colon-delimited desktop identifier list."""
    return "niri" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":")


def _require_niri() -> None:
    if not in_niri_session():
        raise SessionError("requires XDG_CURRENT_DESKTOP to include niri")


def exec_session(env_file: str, command: list[str], *, allow_other_session: bool = False) -> None:
    if not allow_other_session:
        _require_niri()
    if not command or not command[0]:
        raise SessionError("exec requires a command after --")
    environment = os.environ.copy()
    environment.update(parse_env_file(env_file))
    # Process-local only: no manager, activation bus, shell, or child daemon.
    os.execvpe(command[0], command, environment)


def run_manager(arguments: list[str]) -> str:
    """Single injectable subprocess boundary; arguments never pass through a shell."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", *arguments], check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        raise SessionError(f"systemd user manager operation failed: {detail.strip()}") from exc
    return result.stdout


def _manager_environment() -> dict[str, str]:
    result = {}
    for line in run_manager(["show-environment"]).splitlines():
        name, sep, _ = line.partition("=")
        if sep and (name in MANAGER_KEYS or name == OWNER_KEY):
            # systemctl shell-quotes values containing whitespace/metacharacters.
            # Parse those quotes, but never evaluate the resulting text.
            try:
                words = shlex.split(line, comments=False, posix=True)
            except ValueError as exc:
                raise SessionError(f"invalid manager environment quoting for {name}") from exc
            if len(words) != 1 or not words[0].startswith(name + "="):
                raise SessionError(f"invalid manager environment assignment for {name}")
            result[name] = _value(words[0][len(name) + 1:])
    return result


def _set_values(values: dict[str, str]) -> None:
    if values:
        run_manager(["set-environment", *[f"{k}={v}" for k, v in sorted(values.items())]])


def _unset_names(names: list[str]) -> None:
    if names:
        # systemctl unset-environment takes NAMES, not NAME=value assignments.
        run_manager(["unset-environment", *sorted(names)])


def _owner(explicit: str | None) -> str:
    token = explicit if explicit is not None else os.environ.get("INVOCATION_ID", "")
    if not token or len(token) > 256 or not re.fullmatch(r"[A-Za-z0-9_.:-]+", token):
        raise SessionError("provide --owner TOKEN or a valid INVOCATION_ID")
    return token


def _private_directory(path: Path) -> None:
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700 or path.resolve() != path):
        raise SessionError(f"runtime directory must be owned, non-symlink, mode 0700: {path}")


class _StateStore:
    def __init__(self) -> None:
        runtime = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime or not Path(runtime).is_absolute():
            raise SessionError("XDG_RUNTIME_DIR must be an absolute private runtime directory")
        base = Path(runtime)
        _private_directory(base)
        self.directory = base / "niri-dms-theme"
        try:
            self.directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
        _private_directory(self.directory)
        self.path = self.directory / "manager-state.json"
        self.lock_path = self.directory / "manager.lock"

    def _target(self, path: Path, *, missing_ok: bool = False) -> None:
        # Validate the resolved absolute target before every replace/unlink.
        _private_directory(self.directory)
        if path.parent != self.directory or path.resolve() != path:
            raise SessionError(f"unsafe runtime state path: {path}")
        try:
            info = path.lstat()
        except FileNotFoundError:
            if missing_ok:
                return
            raise
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise SessionError(f"runtime state must be an owned regular mode-0600 file: {path}")

    @contextlib.contextmanager
    def locked(self) -> Iterator[None]:
        self._target(self.lock_path, missing_ok=True)
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            self._target(self.lock_path)
            fcntl.flock(fd, fcntl.LOCK_EX)
            self._target(self.lock_path)
            yield
        finally:
            os.close(fd)

    def read(self) -> dict | None:
        self._target(self.path, missing_ok=True)
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, "rb") as stream:
            content = stream.read(_MAX_STATE + 1)
        if len(content) > _MAX_STATE:
            raise SessionError("runtime snapshot is too large")
        try:
            state = json.loads(content.decode("utf-8"))
            if (state["version"] != 1 or state["phase"] not in {"entering", "active", "restored"}
                    or not isinstance(state["owner"], str) or not state["owner"]
                    or not isinstance(state["before"], dict) or not isinstance(state["installed"], dict)
                    or state["before"].keys() != state["installed"].keys()
                    or not set(state["installed"]).issubset(MANAGER_KEYS)):
                raise ValueError("invalid snapshot structure")
            _value(state["owner"])
            for value in state["installed"].values():
                _value(value)
            for value in state["before"].values():
                if value is not None:
                    _value(value)
        except (ValueError, TypeError, KeyError) as exc:
            raise SessionError(f"invalid runtime snapshot: {exc}") from exc
        return state

    def write(self, state: dict) -> None:
        self._target(self.path, missing_ok=True)
        content = json.dumps(state, sort_keys=True) + "\n"
        if len(content.encode("utf-8")) > _MAX_STATE:
            raise SessionError("runtime snapshot is too large")
        fd, name = tempfile.mkstemp(prefix=".manager-state-", dir=self.directory)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            self._target(temporary)
            self._target(self.path, missing_ok=True)
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                self._target(temporary)
                temporary.unlink()

    def remove(self) -> None:
        self._target(self.path)
        self.path.unlink()


def _restore(store: _StateStore, state: dict, current: dict[str, str]) -> dict:
    """Restore only our still-installed values; retain state on any failure."""
    token = state["owner"]
    marker = current.get(OWNER_KEY)
    if state["phase"] == "restored" and marker is None:
        store.remove()  # Recovery after marker removal succeeded but cleanup failed.
        return {"restored": [], "preserved": []}
    if marker != token:
        raise SessionError("manager ownership does not match; refusing to restore another session")
    restore, unset, preserved = {}, [], []
    for key, installed in state["installed"].items():
        if current.get(key) != installed:
            preserved.append(key)
        elif state["before"][key] is None:
            unset.append(key)
        else:
            restore[key] = state["before"][key]
    _set_values(restore)
    _unset_names(unset)
    # Keep the snapshot until both restore operations and marker removal succeed.
    state["phase"] = "restored"
    store.write(state)
    # Recheck the marker to avoid removing a replacement session's ownership.
    if _manager_environment().get(OWNER_KEY) != token:
        raise SessionError("manager ownership changed during restoration; snapshot retained")
    _unset_names([OWNER_KEY])
    store.remove()
    return {"restored": sorted([*restore, *unset]), "preserved": sorted(preserved)}


def manager_enter(env_file: str, *, owner: str | None = None) -> dict:
    _require_niri()
    token = _owner(owner)
    values = {key: value for key, value in parse_env_file(env_file).items() if key in MANAGER_KEYS}
    store = _StateStore()
    with store.locked():
        state = store.read()
        current = _manager_environment()
        marker = current.get(OWNER_KEY)
        if state is not None:
            if state["owner"] != token or marker != token:
                raise SessionError("existing bridge belongs to another owner or needs recovery with manager-leave")
            if state["phase"] != "active":
                raise SessionError("incomplete bridge transaction; run manager-leave with the same owner")
            if state["installed"] != values:
                raise SessionError("owner already entered with a different environment; leave first")
            return {"owner": token, "already_active": True, "keys": sorted(values)}
        if marker is not None:
            raise SessionError("manager has an ownership marker without our snapshot; refusing to overwrite")
        state = {"version": 1, "phase": "entering", "owner": token,
                 "before": {key: current.get(key) for key in values}, "installed": values}
        store.write(state)
        try:
            _set_values({OWNER_KEY: token})
            _set_values(values)
            state["phase"] = "active"
            store.write(state)
        except Exception as exc:
            try:
                now = _manager_environment()
                if now.get(OWNER_KEY) == token:
                    _restore(store, state, now)
                elif now.get(OWNER_KEY) is None:
                    # No values were imported if acquiring the marker failed.
                    # If ownership disappeared later, retain the snapshot instead.
                    if all(now.get(k) == current.get(k) for k in values):
                        store.remove()
                    else:
                        raise SessionError("ownership vanished; recovery snapshot retained")
                else:
                    raise SessionError("ownership changed; recovery snapshot retained")
            except Exception as rollback:
                raise SessionError(f"manager-enter failed: {exc}; rollback incomplete: {rollback}") from exc
            raise SessionError(f"manager-enter failed and was rolled back: {exc}") from exc
        return {"owner": token, "already_active": False, "keys": sorted(values)}


def manager_leave(*, owner: str | None = None) -> dict:
    _require_niri()
    token = _owner(owner)
    store = _StateStore()
    with store.locked():
        state = store.read()
        current = _manager_environment()
        if state is None:
            if OWNER_KEY in current:
                raise SessionError("manager ownership marker exists without a recovery snapshot")
            return {"owner": token, "active": False}
        if state["owner"] != token:
            raise SessionError("snapshot belongs to another owner; refusing to restore")
        return {"owner": token, **_restore(store, state, current)}


def status() -> dict:
    """Report this process's environment; deliberately do not contact the manager."""
    return {"niri_session": in_niri_session(),
            "desktop": os.environ.get("XDG_CURRENT_DESKTOP", ""),
            "environment": {k: os.environ[k] for k in sorted(MANAGER_KEYS) if k in os.environ},
            "manager_owner_in_process": os.environ.get(OWNER_KEY),
            "scope": "process-local (manager bridge is explicit opt-in)"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    execute = commands.add_parser("exec", help="exec COMMAND with process-local theme values")
    execute.add_argument("--env-file", required=True)
    execute.add_argument("--allow-other-session", action="store_true",
                         help="allow exec outside niri for tests or an explicit one-off launch")
    execute.add_argument("command", nargs=argparse.REMAINDER)
    commands.add_parser("status", help="show current process environment (no manager query)")
    enter = commands.add_parser("manager-enter", help="explicit optional legacy manager bridge")
    enter.add_argument("--env-file", required=True)
    enter.add_argument("--owner")
    leave = commands.add_parser("manager-leave", help="restore an owned legacy bridge")
    leave.add_argument("--owner")
    args = parser.parse_args(argv)
    try:
        if args.action == "exec":
            if not args.command or args.command[0] != "--":
                raise SessionError("syntax: exec --env-file FILE [--allow-other-session] -- COMMAND [ARG ...]")
            exec_session(args.env_file, args.command[1:], allow_other_session=args.allow_other_session)
        elif args.action == "manager-enter":
            print(json.dumps(manager_enter(args.env_file, owner=args.owner), sort_keys=True))
        elif args.action == "manager-leave":
            print(json.dumps(manager_leave(owner=args.owner), sort_keys=True))
        else:
            print(json.dumps(status(), indent=2, sort_keys=True))
    except (SessionError, OSError) as exc:
        print(f"themekit.session: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

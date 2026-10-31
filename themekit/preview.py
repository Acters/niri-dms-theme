"""Temporary, exact-app preview backdrop; never a compositor/service manager."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import tempfile
import os
from pathlib import Path
import signal
import stat
import subprocess
import uuid


def desktop_id(app):
    return f"org.kde.{app}.niri-glass-preview"


def _socket_problem(socket):
    """Return why a Niri IPC socket is unusable, or None if it is safe to use."""
    try:
        metadata = socket.lstat()
    except OSError as error:
        return error.strerror or str(error)
    if stat.S_ISLNK(metadata.st_mode):
        return "symbolic link is not accepted"
    if not stat.S_ISSOCK(metadata.st_mode):
        return "not a Unix domain socket"
    if metadata.st_uid != os.getuid():
        return "socket is not owned by this user"
    return None


def _explicit_socket(origin):
    """Validate NIRI_SOCKET itself so its error is never hidden by a fallback."""
    value = origin.get("NIRI_SOCKET")
    if not value:
        return None
    try:
        socket = Path(value)
    except (TypeError, ValueError):
        return None, f"NIRI_SOCKET={value!r} is not a path"
    if not socket.is_absolute():
        return None, f"NIRI_SOCKET={value!r} is not an absolute path"
    problem = _socket_problem(socket)
    if problem:
        return None, f"NIRI_SOCKET={value}: {problem}"
    return socket, None


def _discovered_socket(origin):
    """Find the one current niri.<WAYLAND_DISPLAY>.*.sock without guessing."""
    runtime = origin.get("XDG_RUNTIME_DIR")
    display = origin.get("WAYLAND_DISPLAY")
    if not runtime or not display:
        return None, "NIRI_SOCKET is unset and XDG_RUNTIME_DIR/WAYLAND_DISPLAY are unavailable"
    if os.sep in display or "\x00" in display or display in (".", ".."):
        return None, f"WAYLAND_DISPLAY={display!r} is not a plain socket name"
    try:
        runtime_path = Path(runtime).resolve(strict=True)
        metadata = runtime_path.stat()
    except OSError as error:
        return None, f"XDG_RUNTIME_DIR={runtime} is unavailable: {error.strerror or error}"
    if not stat.S_ISDIR(metadata.st_mode):
        return None, f"XDG_RUNTIME_DIR={runtime} is not a directory"
    if metadata.st_uid != os.getuid():
        return None, f"XDG_RUNTIME_DIR={runtime} is not owned by this user"
    prefix, suffix = f"niri.{display}.", ".sock"
    try:
        candidates = sorted(path for path in runtime_path.iterdir()
                            if path.name.startswith(prefix) and path.name.endswith(suffix)
                            and len(path.name) >= len(prefix) + len(suffix))
    except OSError as error:
        return None, f"cannot scan XDG_RUNTIME_DIR={runtime}: {error.strerror or error}"
    if not candidates:
        return None, f"no Niri IPC socket matching {runtime_path}/niri.{display}.*.sock"
    usable, problems = [], []
    for candidate in candidates:
        problem = _socket_problem(candidate)
        if problem:
            problems.append(f"{candidate.name}: {problem}")
        else:
            usable.append(candidate)
    if len(usable) == 1:
        return usable[0], None
    if len(usable) > 1:
        names = ", ".join(path.name for path in usable[:5])
        more = f" (+{len(usable) - 5} more)" if len(usable) > 5 else ""
        return None, f"ambiguous Niri IPC sockets matching niri.{display}.*.sock: {names}{more}"
    return None, (f"no usable Niri IPC socket matching niri.{display}.*.sock: "
                  + "; ".join(problems[:5]))


def _niri_socket(origin):
    explicit = _explicit_socket(origin)
    if explicit is not None:
        return explicit
    return _discovered_socket(origin)


def _niri_config(origin):
    home = origin.get("HOME")
    config_home = origin.get("XDG_CONFIG_HOME") or (str(Path(home) / ".config") if home else None)
    if not config_home:
        return None, "HOME/XDG_CONFIG_HOME is unavailable"
    config = Path(config_home) / "niri/config.kdl"
    try:
        if config.is_symlink():
            return None, f"{config} is a symlink"
        if not config.is_file():
            return None, f"{config} is not a regular file"
    except OSError as error:
        return None, f"{config}: {error.strerror or error}"
    return config, None


def _update_config(config, transform):
    """Serialize preview writers, atomically replace, and reject stale editor reads."""
    digest = hashlib.sha256(os.fsencode(str(config.resolve()))).hexdigest()[:24]
    lockpath = Path(tempfile.gettempdir()) / f"themekit-niri-{os.getuid()}-{digest}.lock"
    fd = os.open(lockpath, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    metadata = os.fstat(fd)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
        os.close(fd)
        raise OSError("unsafe preview lock: expected a regular file owned by this user")
    with os.fdopen(fd, "r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if config.is_symlink():
            raise OSError("Niri config became a symlink")
        before = config.read_bytes()
        after = transform(before.decode()).encode()
        if before == after:
            return
        mode = stat.S_IMODE(config.stat().st_mode)
        fd, name = tempfile.mkstemp(prefix=".themekit-preview-", dir=config.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), mode)
                stream.write(after)
                stream.flush()
                os.fsync(stream.fileno())
            if config.is_symlink() or config.read_bytes() != before:
                raise OSError("Niri config changed during preview update; left untouched")
            os.replace(temporary, config)
        finally:
            temporary.unlink(missing_ok=True)


@contextmanager
def backdrop(root, app, origin):
    """Append an optional include to the original config, removing only our block."""
    desktop = (origin.get("XDG_CURRENT_DESKTOP") or "").lower().split(":")
    if "niri" not in desktop:
        print(f"Preview backdrop skipped: XDG_CURRENT_DESKTOP={origin.get('XDG_CURRENT_DESKTOP')!r} "
              "is not Niri; style preview remains active.", flush=True)
        yield
        return
    socket, socket_problem = _niri_socket(origin)
    if socket is None:
        print(f"Preview backdrop skipped: {socket_problem}; style preview remains active.", flush=True)
        yield
        return
    config, config_problem = _niri_config(origin)
    if config is None:
        print(f"Preview backdrop skipped: {config_problem}; style preview remains active.", flush=True)
        yield
        return

    preview_root = Path(root).resolve()
    token = uuid.uuid4().hex
    rule = preview_root / f".niri-preview-{token}.kdl"
    # Anchors and escaped dots ensure this cannot affect another application.
    exact = "^" + desktop_id(app).replace(".", r"\.") + "$"
    effect = ("background-effect {\n        blur true\n        xray false\n"
              "        noise 0.008\n    }\n")
    rule.write_text("window-rule {\n    match app-id=" + json.dumps(exact) + "\n"
                    "    opacity 1.0\n    draw-border-with-background false\n    " + effect
                    + "    popups {\n        opacity 1.0\n        "
                    + effect.replace("\n", "\n    ").rstrip() + "\n    }\n}\n")
    rule.chmod(0o600)
    block = (f"\n// BEGIN themekit-preview-{token}\ninclude "
             + json.dumps(str(rule)) + f" optional=true\n// END themekit-preview-{token}\n")
    installed = False
    try:
        try:
            _update_config(config, lambda current: current + block)
            installed = True
            print(f"Preview backdrop active for {desktop_id(app)}: compositor saturation unchanged, noise 0.008.", flush=True)
        except OSError as error:
            print(f"Preview backdrop skipped: {error}; style preview remains active.", flush=True)
        yield
    finally:
        if installed:
            try:
                # Read the latest bytes, preserving all edits outside our exact marker.
                _update_config(config, lambda current:
                               current.replace(block, "", 1) if current.count(block) == 1 else current)
            except OSError as error:
                print(f"Preview backdrop cleanup: {error}", flush=True)
        # optional=true makes even a retained include safe if the temp home disappears.
        if rule.resolve().parent == preview_root:
            rule.unlink(missing_ok=True)
        else:
            print("Preview backdrop cleanup: rule left untouched outside preview root.", flush=True)


def wait_for_app(command, env):
    """Wait so context cleanup runs, forwarding termination to the child gracefully.

    Callers must launch apps in a mode that keeps the real window process in the
    foreground; Kate in particular daemonizes by default unless --block is set.
    """
    child = subprocess.Popen(command, env=env)
    previous = {}

    def forward(signum, _frame):
        if child.poll() is None:
            child.send_signal(signum)

    try:
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            previous[signum] = signal.signal(signum, forward)
        return child.wait()
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)

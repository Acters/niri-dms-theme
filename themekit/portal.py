# SPDX-License-Identifier: MIT
"""One-shot, desktop-gated environment for the D-Bus-activated KDE picker."""
import os
from pathlib import Path
import shutil

LAUNCHER = "kde-portal-glass"
UNIT = "plasma-xdg-desktop-portal-kde.service"


def find_backend():
    candidates = [shutil.which("xdg-desktop-portal-kde"),
                  "/usr/lib/xdg-desktop-portal-kde",
                  "/usr/libexec/xdg-desktop-portal-kde"]
    for value in candidates:
        if value and Path(value).is_absolute() and Path(value).is_file() and os.access(value, os.X_OK):
            return str(Path(value).resolve())
    return None


def launcher(ctx, environment, backend):
    """Generate a standalone exec wrapper, not a daemon or manager import."""
    fixed = {key: value for key, value in environment.items()
             if key not in {"XDG_CURRENT_DESKTOP", "XDG_DATA_DIRS", "XDG_CONFIG_DIRS", "QT_PLUGIN_PATH"}}
    prefixes = {"XDG_DATA_DIRS": (ctx["PROFILE_SHARE"], "/usr/local/share:/usr/share"),
                "XDG_CONFIG_DIRS": (str(Path(ctx["PROFILE_CONFIG"]) / "shared"), "/etc/xdg"),
                "QT_PLUGIN_PATH": (ctx["PLUGIN_ROOT"], "")}
    return ("#!/usr/bin/env python3\n# SPDX-License-Identifier: MIT\n"
            "# Generated; never changes the systemd manager environment.\n"
            "import os, sys\n"
            "desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').lower().split(':')\n"
            "if 'niri' in desktop:\n"
            f"    os.environ.update({fixed!r})\n"
            f"    for key, (prefix, default) in {prefixes!r}.items():\n"
            "        values = [prefix, *os.environ.get(key, default).split(':')]\n"
            "        os.environ[key] = ':'.join(dict.fromkeys(v for v in values if v))\n"
            f"backend = {str(backend)!r}\n"
            "os.execv(backend, [backend, *sys.argv[1:]])\n").encode()


def exec_argument(value):
    """Quote a systemd Exec argument, including its variable/specifier escapes."""
    value = str(value)
    if any(char in value for char in "\n\r\x00"):
        raise ValueError("launcher path cannot contain newline or NUL")
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$') + '"'


def service_dropin(wrapper):
    return ("[Service]\nExecStart=\nExecStart=" + exec_argument(wrapper) + "\n").encode()

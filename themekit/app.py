"""Small, fixed Niri/DMS theme installer and isolated application previews."""
from __future__ import annotations

import argparse
import configparser
import io
import json
import shlex
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from . import integrate
from .integrate import Resource
from .palette import render_palette
from .paths import context, render
from .preview import backdrop, desktop_id, wait_for_app

REPO = Path(__file__).resolve().parent.parent
PLUGINS = {
    "kate": ("plugins/kate-balanced-glass", "build/kate",
             "build/kate/katebalancedglassplugin.so", "kf6/ktexteditor/katebalancedglassplugin.so"),
    "glass": ("plugins/glass-style", "build/glass",
              "build/glass/plugins/styles/niriglassstyle.so", "styles/niriglassstyle.so"),
}
# Source, owned destination, render tokens. No manifest or runtime Python installation.
FILES = (
    ("assets/niri/material.kdl", "@PROFILE_CONFIG@/niri/material.kdl", False),
    ("assets/dms/blue-black.json", "@PROFILE_CONFIG@/dms/blue-black.json", False),
    ("assets/qt/qtengine.json.in", "@PROFILE_CONFIG@/qtengine.json", True),
    ("assets/qt/translucent.colors.in", "@PROFILE_CONFIG@/matugen/translucent.colors.in", False),
    ("assets/darkly/darklyrc", "@PROFILE_CONFIG@/shared/darklyrc", False),
    ("assets/kate/katebalancedglassrc", "@PROFILE_CONFIG@/shared/katebalancedglassrc", False),
    *((f"assets/kate/{name}.theme", f"@PROFILE_SHARE@/org.kde.syntax-highlighting/themes/{name}.theme", False)
      for name in ("BalancedGlassLight", "BalancedGlassDark", "TomorrowNightBright")),
    ("assets/drawy/drawyrc", "@PROFILE_CONFIG@/apps/drawy/drawyrc", False),
    ("assets/drawy/darklyrc", "@PROFILE_CONFIG@/apps/drawy/darklyrc", False),
    ("assets/drawy/drawy-glass", "@PROFILE_DATA@/bin/drawy-glass", False),
)


def current_mode():
    """Read DMS once, without starting it or changing its mode."""
    try:
        result = subprocess.run(["dms", "ipc", "call", "theme", "getMode"],
                                capture_output=True, text=True, timeout=2, check=True)
        value = result.stdout.strip()
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = value
        if isinstance(parsed, dict):
            parsed = parsed.get("mode", parsed.get("result"))
        if parsed in ("light", "dark"):
            return parsed
        # Some DMS versions print a labelled IPC response instead of JSON.
        match = re.fullmatch(r"(?:[Mm]ode:\s*)?(light|dark)", value)
        if match:
            return match[1]
    except (OSError, subprocess.SubprocessError):
        pass
    return "dark"


def environment(ctx):
    values = {
        "XDG_CURRENT_DESKTOP": "niri", "QT_QPA_PLATFORM": "wayland",
        "QT_QPA_PLATFORMTHEME": "qtengine", "QT_QPA_PLATFORMTHEME_QT6": "qtengine",
        "QT_STYLE_OVERRIDE": "NiriGlass", "QTENGINE_CONFIG": "@PROFILE_CONFIG@/qtengine.json",
        "QT_PLUGIN_PATH": "@PLUGIN_ROOT@", "XDG_DATA_DIRS": "@MERGED_DATA_DIRS@",
        "XDG_CONFIG_DIRS": "@MERGED_CONFIG_DIRS@", "NIRI_DMS_THEME_PROFILE": "niri-dms-glass",
        "NIRI_DMS_THEME_CONFIG_HOME": "@PROFILE_CONFIG@",
        "NIRI_DMS_THEME_DATA_HOME": "@PROFILE_DATA@",
    }
    return {key: render(value, ctx) for key, value in values.items()}


def build_plugins(names, *, dry_run=False):
    def stale(name):
        source, _, artifact, _ = PLUGINS[name]
        target = REPO / artifact
        if not target.is_file():
            return True
        stamp = target.stat().st_mtime_ns
        return any(path.stat().st_mtime_ns > stamp for path in (REPO / source).rglob("*")
                   if path.is_file() and (path.name == "CMakeLists.txt"
                   or path.suffix in (".cpp", ".h", ".hpp", ".json", ".cmake")))
    needed = [name for name in names if stale(name)]
    if not needed:
        return
    if dry_run:
        for name in needed:
            reason = "outdated" if (REPO / PLUGINS[name][2]).is_file() else "missing"
            print(f"Would build {name}: {reason} {PLUGINS[name][2]}")
        absent = [tool for tool in ("cmake", "c++") if not shutil.which(tool)]
        if absent:
            print("Missing build prerequisites: " + ", ".join(absent))
        print("Build requires Qt6 Widgets development files; Kate also requires KF6 TextEditor, CoreAddons and Config.")
        return
    if not shutil.which("cmake"):
        raise ValueError("missing build prerequisite: cmake (also requires C++/Qt6 development packages)")
    for name in needed:
        source, build, artifact, _ = PLUGINS[name]
        subprocess.run(["cmake", "-S", str(REPO / source), "-B", str(REPO / build),
                        "-DCMAKE_BUILD_TYPE=Release"], check=True)
        subprocess.run(["cmake", "--build", str(REPO / build), "--parallel", "2"], check=True)
        if not (REPO / artifact).is_file():
            raise ValueError(f"build did not produce {artifact}")


def resources(ctx, mode, names=("glass", "kate"), *, dry_run=False):
    result = []
    for source, target, substitute in FILES:
        data = (REPO / source).read_bytes()
        if substitute:
            data = render(data.decode(), ctx).encode()
        result.append(Resource(Path(render(target, ctx)), data,
                               0o700 if source == "assets/drawy/drawy-glass" else 0o600))
    for name in names:
        _, _, artifact, target = PLUGINS[name]
        path = REPO / artifact
        # Empty bytes describe the target only in a no-write dry-run; never deploy them.
        data = path.read_bytes() if path.is_file() else None
        if data is None and not dry_run:
            raise ValueError(f"missing plugin artifact: {artifact}")
        result.append(Resource(Path(ctx["PLUGIN_ROOT"]) / target,
                               data if data is not None else b"", 0o700))
    palette = render_palette(json.loads((REPO / "assets/dms/blue-black.json").read_text()),
                             (REPO / "assets/qt/translucent.colors.in").read_text(), mode)
    result.append(Resource(Path(ctx["PROFILE_DATA"]) / "generated/DankMatugenTranslucent.colors",
                           palette.encode(), generated=True))
    env = environment(ctx)
    # systemd EnvironmentFile quoting, not shell commands or a session helper.
    def quote(value):
        if any(c in value for c in "\n\r\x00"):
            raise ValueError("environment paths cannot contain newlines or NUL")
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    text = "# Generated by themekit; EnvironmentFile syntax.\n"
    text += "".join(f"{key}={quote(value)}\n" for key, value in env.items())
    result.append(Resource(Path(ctx["PROFILE_CONFIG"]) / "session.env", text.encode(), generated=True))
    return result


def safe_path(path, root):
    """Preview writes reject traversal, symlinks and non-regular targets."""
    path, root = Path(path), Path(root)
    if not path.is_absolute() or ".." in path.parts or not path.is_relative_to(root):
        raise ValueError(f"path outside preview home: {path}")
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError(f"symlink not allowed: {item}")
        if item != path and item.exists() and not item.is_dir():
            raise ValueError(f"non-directory ancestor: {item}")
    if path.exists() and not path.is_file():
        raise ValueError(f"not a regular file: {path}")
    return path


def atomic_write(resource, root):
    path = safe_path(resource.path, root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    safe_path(path, root)
    fd, temporary = tempfile.mkstemp(prefix=".themekit-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), resource.mode)
            stream.write(resource.data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def old_preview_home(root):
    ctx = context(str(root))
    path = safe_path(Path(ctx["PROFILE_CONFIG"]) / "session.env", root)
    if not path.is_file():
        return False
    try:
        values = dict(shlex.split(line, comments=True)[0].split("=", 1)
                      for line in path.read_text().splitlines()
                      if line.strip() and not line.lstrip().startswith("#"))
    except (ValueError, IndexError):
        return False
    expected = environment(ctx)
    return all(values.get(key) == expected[key] for key in (
        "NIRI_DMS_THEME_PROFILE", "NIRI_DMS_THEME_CONFIG_HOME",
        "NIRI_DMS_THEME_DATA_HOME", "QTENGINE_CONFIG"))


def preview_home(home):
    if home is None:
        root = Path(tempfile.mkdtemp(prefix="themekit-preview-"))
    else:
        root = Path(os.path.abspath(os.path.expanduser(home)))
        if ".." in Path(home).parts:
            raise ValueError("preview home cannot contain '..'")
        if root.resolve() == Path.home().resolve():
            raise ValueError("preview must not use your real home")
        # Never turn a normal populated home into a preview, even if explicitly supplied.
        safe_path(root / ".themekit-preview", root)
        if (root.exists() and any(root.iterdir()) and not (root / ".themekit-preview").is_file()
                and not old_preview_home(root)):
            raise ValueError("preview --home must be empty or a previously created themekit preview")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker = Resource(root / ".themekit-preview", b"themekit isolated preview\n")
    if marker.path.exists() and marker.path.read_bytes() != marker.data:
        raise ValueError("invalid preview home marker")
    atomic_write(marker, root)
    return root


def preview_setting(path, section, key, value, root, *, only_if_missing=False):
    """Keep preview preferences/session data while setting just our activation flags."""
    path = safe_path(path, root)
    config = configparser.RawConfigParser(strict=False)
    config.optionxform = str
    if path.exists():
        config.read_string(path.read_text())
    if only_if_missing and config.has_option(section, key):
        return
    if not config.has_section(section):
        config.add_section(section)
    config.set(section, key, value)
    output = io.StringIO()
    config.write(output, space_around_delimiters=False)
    atomic_write(Resource(path, output.getvalue().encode()), root)


def preview(app, home, mode):
    origin = os.environ.copy()
    dependencies = ("glass", "kate") if app == "kate" else ("glass",)
    build_plugins(dependencies)
    root = preview_home(home)
    print(f"Preview home (kept on exit): {root}", flush=True)
    print(f"Static {mode} preview; no live DMS connection before installation.", flush=True)
    ctx = context(str(root))
    for item in resources(ctx, mode, dependencies):
        path = safe_path(item.path, root)
        # First-run defaults only: keep preferences edited in a reusable preview.
        if path.exists() and path.name in ("drawyrc", "darklyrc", "katebalancedglassrc"):
            continue
        atomic_write(item, root)
    for key in ("CONFIG_HOME", "DATA_HOME", "STATE_HOME", "CACHE_HOME"):
        path = Path(ctx[key])
        safe_path(path / ".directory-check", root)
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if app == "kate":
        session = Path(ctx["DATA_HOME"]) / "kate/anonymous.katesession"
        preview_setting(session, "Kate Plugins", "katebalancedglassplugin", "true", root)
        preview_setting(session, "Kate Plugins", "lspclientplugin", "false", root, only_if_missing=True)
        preview_setting(Path(ctx["CONFIG_HOME"]) / "katerc", "KTextEditor Renderer",
                        "Auto Color Theme Selection", "true", root)
        sample = safe_path(Path(ctx["PROFILE_DATA"]) / "preview.cpp", root)
        if not sample.exists():
            atomic_write(Resource(sample, (REPO / "assets/kate/preview.cpp").read_bytes()), root)
        # Kate daemonizes via daemon(1, 0) unless --block is present; keep it the waited child.
        command = ["kate", "--desktopfile", desktop_id(app), "--block", "--new",
                   "--startanon", str(sample)]
    elif app == "dolphin":
        sample = Path(ctx["PROFILE_DATA"]) / "preview-files"
        safe_path(sample / ".directory-check", root)
        sample.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name, data in (("Welcome.txt", b"Isolated NiriGlass preview files.\n"),
                           ("Notes.txt", b"These samples are safe to edit.\n"),
                           ("Example.cpp", b"int main() { return 0; }\n")):
            target = safe_path(sample / name, root)
            if not target.exists():
                atomic_write(Resource(target, data), root)
        command = ["dolphin", "--desktopfile", desktop_id(app), "--new-window", str(sample)]
    else:
        command = [str(Path(ctx["PROFILE_DATA"]) / "bin/drawy-glass"),
                   "--desktopfile", desktop_id(app)]
    env = os.environ.copy()  # Retain Wayland/X11 sockets, runtime directory and session bus.
    env.update(environment(ctx))
    env["HOME"] = ctx["HOME"]
    for key in ("CONFIG_HOME", "DATA_HOME", "STATE_HOME", "CACHE_HOME"):
        env["XDG_" + key] = ctx[key]
    # Never inherit host Qt search overrides which could load unrelated user plugins/settings.
    for key in ("QT_QPA_PLATFORM_PLUGIN_PATH", "QT6_PLUGIN_PATH", "KDEHOME"):
        env.pop(key, None)
    print(f"Preview ready: launching {app} with isolated HOME={root}", flush=True)
    with backdrop(root, app, origin):
        return wait_for_app(command, env)


def report(command, changes, ctx, dry_run, isolated):
    if dry_run:
        print(f"Dry-run {command}: {len(changes)} affected file(s)")
        for path in changes:
            print(f"  {path}")
    else:
        print(f"{'Installed' if command == 'install' else 'Restored'}: {len(changes)} changed file(s)")
    if command == "install":
        backup = Path(ctx["STATE_HOME"]) / "niri-dms-theme/backup.json"
        print(f"{'Backup would be' if dry_run else 'Backup'}: {backup}")
        if not dry_run:
            print("Reopen Kate, Dolphin and Drawy once to load the installed plugins.")
    if isolated:
        print("Alternate home: no live services changed.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("install", "preview", "restore"):
        sub = commands.add_parser(name)
        if name == "preview":
            sub.add_argument("app", choices=("drawy", "kate", "dolphin"))
        else:
            sub.add_argument("--dry-run", action="store_true")
        sub.add_argument("--home", help="alternate home (preview: empty or reusable isolated home)")
        if name != "restore":
            sub.add_argument("--mode", choices=("light", "dark"))
    args = parser.parse_args(argv)
    try:
        if args.command == "restore":
            ctx = context(args.home)
            backup = Path(ctx["STATE_HOME"]) / "niri-dms-theme/backup.json"
            if not backup.exists():
                print("Nothing to restore: no theme backup found.")
                return 0
            changes = integrate.restore(ctx, dry_run=args.dry_run, live=args.home is None)
            report("restore", changes, ctx, args.dry_run, args.home is not None)
        else:
            mode = args.mode or current_mode()
            if args.command == "preview":
                return preview(args.app, args.home, mode)
            else:
                build_plugins(("glass", "kate"), dry_run=args.dry_run)
                ctx = context(args.home)
                changes = integrate.apply(ctx, resources(ctx, mode, dry_run=args.dry_run), environment(ctx),
                                          dry_run=args.dry_run, live=args.home is None)
                report("install", changes, ctx, args.dry_run, args.home is not None)
        return 0
    except (OSError, ValueError, configparser.Error, subprocess.SubprocessError) as error:
        print(f"themekit: {error}", file=sys.stderr)
        return 1

"""Portable, opt-in deployment of the repository's private theme profile."""
from __future__ import annotations

import argparse
import base64
import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import stat
import subprocess
import sys
import tempfile

PROFILE = "niri-dms-theme"
TOKEN = re.compile(r"@[A-Z][A-Z0-9_]*@")


class Error(ValueError):
    pass


def absolute(path):
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def beneath(path, root):
    return path == root or root in path.parents


def safe_path(path):
    """Reject symlinks and non-directory ancestors without following them."""
    path = absolute(path)
    for part in reversed((path, *path.parents)):
        if part.is_symlink():
            raise Error(f"symlink is not allowed: {part}")
        if part != path and part.exists() and not part.is_dir():
            raise Error(f"non-directory ancestor: {part}")
    if path.exists() and not path.is_file():
        raise Error(f"target is not a regular file: {path}")
    return path


def context(home=None):
    explicit = home is not None
    home = absolute(home if explicit else Path.home())
    roots = {"HOME": str(home)}
    for key, default in (("CONFIG_HOME", ".config"), ("DATA_HOME", ".local/share"),
                         ("STATE_HOME", ".local/state"), ("CACHE_HOME", ".cache")):
        value = None if explicit else os.environ.get("XDG_" + key)
        # XDG only recognizes absolute root values.
        roots[key] = str(absolute(value) if value and Path(value).is_absolute() else home / default)
    roots["PROFILE_CONFIG"] = str(Path(roots["CONFIG_HOME"]) / PROFILE)
    roots["PROFILE_DATA"] = str(Path(roots["DATA_HOME"]) / PROFILE)
    roots["PLUGIN_ROOT"] = str(Path(roots["PROFILE_DATA"]) / "qt-plugins")
    roots["PROFILE_SHARE"] = str(Path(roots["PROFILE_DATA"]) / "share")
    dirs = "/usr/local/share:/usr/share" if explicit else os.environ.get("XDG_DATA_DIRS", "") or "/usr/local/share:/usr/share"
    roots["MERGED_DATA_DIRS"] = ":".join(dict.fromkeys([roots["PROFILE_SHARE"], *[p for p in dirs.split(":") if p and Path(p).is_absolute()]]))
    config_dirs = "/etc/xdg" if explicit else os.environ.get("XDG_CONFIG_DIRS", "") or "/etc/xdg"
    roots["MERGED_CONFIG_DIRS"] = ":".join(dict.fromkeys([
        str(Path(roots["PROFILE_CONFIG"]) / "shared"),
        *[p for p in config_dirs.split(":") if p and Path(p).is_absolute()]]))
    return roots


def render(text, ctx):
    if not isinstance(text, str):
        raise Error("rendered values must be strings")
    result = TOKEN.sub(lambda m: ctx.get(m[0][1:-1], m[0]), text)
    if TOKEN.search(result):
        raise Error(f"unresolved token: {result}")
    if "\x00" in result:
        raise Error("NUL is not allowed")
    return result


def owned_target(value, ctx):
    value = render(value, ctx)
    if ".." in Path(value).parts or not Path(value).is_absolute():
        raise Error(f"invalid target path: {value}")
    path = absolute(value)
    if not any(beneath(path, Path(ctx[key])) and path != Path(ctx[key])
               for key in ("PROFILE_CONFIG", "PROFILE_DATA")):
        raise Error(f"target outside owned profile: {path}")
    return safe_path(path)


def repo_path(repo, value, missing=False):
    if not isinstance(value, str) or Path(value).is_absolute() or ".." in Path(value).parts:
        raise Error(f"invalid repository-relative path: {value}")
    path = repo / value
    if not beneath(path.resolve(), repo.resolve()):
        raise Error(f"source escapes repository: {value}")
    if not missing and not path.is_file():
        raise Error(f"missing source: {path}")
    return path


def load_manifest(repo, manifest=None):
    path = absolute(manifest) if manifest else repo / "profile.json"
    with path.open(encoding="utf-8") as stream:
        data = json.load(stream)
    if data.get("schema", data.get("schema_version")) != 1 or data.get("id") != "niri-dms-glass":
        raise Error("expected manifest schema 1 and id niri-dms-glass")
    return data


def quote_env(value):
    if any(c in value for c in "\n\r\x00"):
        raise Error("environment values cannot contain newline or NUL")
    return '"' + re.sub(r'([\\"])', r'\\\1', value) + '"'


def make_plan(repo, manifest, ctx, mode="dark"):
    entries = []
    for spec in manifest.get("files", []):
        target = owned_target(spec["target"], ctx)
        source = repo_path(repo, spec["source"], missing=True)
        if source.exists() and not source.is_file():
            raise Error(f"source is not a regular file: {source}")
        content = None
        if source.is_file():
            content = source.read_bytes()
            if spec.get("render", False):
                content = render(content.decode("utf-8"), ctx).encode()
        entries.append({"target": target, "source": str(source), "content": content,
                        "mode": 0o700 if spec.get("executable", False) else 0o600})
    env = manifest.get("environment", {})
    rendered = {}
    for key, value in env.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise Error(f"invalid environment name: {key}")
        rendered[key] = render(value, ctx)
        quote_env(rendered[key])
    shell = "# Generated by themekit; EnvironmentFile syntax, not a shell script.\n" + "".join(f"{k}={quote_env(v)}\n" for k, v in rendered.items())
    kdl = "environment {\n" + "".join(f"    {json.dumps(k)} {json.dumps(v, ensure_ascii=False)}\n" for k, v in rendered.items()) + "}\n"
    for name, content in (("session.env", shell), ("niri/environment.kdl", kdl)):
        entries.append({"target": owned_target(ctx["PROFILE_CONFIG"] + "/" + name, ctx),
                        "source": "generated environment", "content": content.encode(), "mode": 0o600})
    palette = manifest.get("palette")
    if palette:
        theme = repo_path(repo, palette["theme_source"])
        template = repo_path(repo, palette["template_source"])
        from themekit.palette import render_palette
        content = render_palette(json.loads(theme.read_text(encoding="utf-8")),
                                 template.read_text(encoding="utf-8"), mode=mode)
        entries.append({"target": owned_target(palette["target"], ctx), "source": "generated palette",
                        "content": content.encode(), "mode": 0o600})
    targets = [str(entry["target"]) for entry in entries]
    if len(targets) != len(set(targets)):
        raise Error("duplicate deploy target")
    # Also forbid one target from being another target's parent.
    for target in map(Path, targets):
        if any(str(parent) in targets for parent in target.parents):
            raise Error("deploy target is an ancestor of another target")
    return entries


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, content, mode):
    safe_path(path)
    for parent in reversed(path.parents):
        if not parent.exists():
            parent.mkdir(mode=0o700)
    safe_path(path)
    fd, temporary = tempfile.mkstemp(prefix=".themekit-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def state_path(ctx):
    return safe_path(Path(ctx["STATE_HOME"]) / PROFILE / "transactions.json")


def read_state(path):
    if not path.exists():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise Error("invalid transaction state")
    for record in value:
        if not isinstance(record, dict) or record.get("status") not in ("pending", "complete") or not isinstance(record.get("changes"), list):
            raise Error("invalid transaction record")
        for change in record["changes"]:
            if not isinstance(change, dict) or not {"target", "before", "after", "mode"} <= change.keys():
                raise Error("invalid transaction change")
    return value


def save_state(path, state):
    atomic_write(path, (json.dumps(state, indent=2) + "\n").encode(), 0o600)


def previous(path):
    if not path.exists():
        return None
    return {"data": base64.b64encode(path.read_bytes()).decode("ascii"),
            "mode": stat.S_IMODE(path.stat().st_mode)}


def restore(path, before):
    safe_path(path)
    if before is None:
        if path.exists():
            path.unlink()
    else:
        atomic_write(path, base64.b64decode(before["data"], validate=True), before["mode"])


def install(entries, ctx, apply=False):
    # Complete preflight before writing even a state directory.
    statefile = state_path(ctx)
    history = read_state(statefile)
    if history and history[-1].get("status") != "complete":
        raise Error("interrupted transaction: run rollback --apply before installing")
    changes = []
    for entry in entries:
        path = safe_path(entry["target"])
        content = entry["content"]
        if content is None:
            raise Error(f"missing artifact: {entry['source']}; run build first")
        before = previous(path)
        if before and base64.b64decode(before["data"]) == content and before["mode"] == entry["mode"]:
            continue
        changes.append({"target": str(path), "before": before,
                        "after": digest(content), "mode": entry["mode"], "entry": entry})
    print(f"{'Applying' if apply else 'Dry-run:'} {len(changes)} changed file(s)")
    if not apply or not changes:
        return
    completed = []
    record = {"status": "pending", "changes": [
        {k: v for k, v in change.items() if k != "entry"} for change in changes]}
    # Persist originals before touching assets; a killed process can be rolled back.
    save_state(statefile, history + [record])
    try:
        for change in changes:
            entry = change["entry"]
            atomic_write(entry["target"], entry["content"], entry["mode"])
            completed.append(change)
        record["status"] = "complete"
        save_state(statefile, history + [record])
    except Exception:
        for change in reversed(completed):
            restore(Path(change["target"]), change["before"])
        save_state(statefile, history)
        raise


def rollback(ctx, apply=False):
    statefile = state_path(ctx)
    history = read_state(statefile)
    if not history:
        print("Nothing to roll back")
        return
    record = history[-1]
    changes = record["changes"]
    checked = []
    for change in changes:
        path = owned_target(change["target"], ctx)
        before = change["before"]
        if before is not None:
            base64.b64decode(before["data"], validate=True)
            if not isinstance(before["mode"], int) or not 0 <= before["mode"] <= 0o7777:
                raise Error("invalid backup file mode")
        current = previous(path)
        # A pending transaction can contain files not yet changed, or already
        # restored by an interrupted rollback. Never accept any other drift.
        if record["status"] == "pending" and current == before:
            continue
        if current is None or digest(base64.b64decode(current["data"])) != change["after"] or current["mode"] != change["mode"]:
            raise Error(f"refusing rollback: file drift: {path}")
        checked.append((path, before))
    print(f"{'Restoring' if apply else 'Dry-run rollback:'} {len(checked)} file(s)")
    if apply:
        record["status"] = "pending"
        save_state(statefile, history)
        for path, before in reversed(checked):
            restore(path, before)
        save_state(statefile, history[:-1])


def build(repo, manifest):
    for spec in manifest.get("builds", []):
        source = repo_path(repo, spec["source"], missing=True)
        directory = repo_path(repo, spec["build_dir"], missing=True)
        artifact = repo_path(repo, spec["artifact"], missing=True)
        root = repo / "build"
        if directory == root or not beneath(directory, root):
            raise Error("build_dir must be inside repo/build")
        if not beneath(artifact, root):
            raise Error("build artifact must be inside repo/build")
        # Reject symlinks even if they happen to resolve back into the repository.
        for item in (directory, artifact):
            for parent in (item, *item.parents):
                if parent == repo.parent:
                    break
                if parent.is_symlink():
                    raise Error(f"symlink in build path: {parent}")
        if not source.is_dir():
            raise Error(f"missing build source directory: {source}")
    for spec in manifest.get("builds", []):
        subprocess.run(["cmake", "-S", str(repo / spec["source"]), "-B", str(repo / spec["build_dir"]),
                        "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release"], check=True)
        subprocess.run(["cmake", "--build", str(repo / spec["build_dir"]), "-j2"], check=True)


def legacy_warnings(ctx):
    """Inspect legacy integration without loading services or changing files."""
    config = Path(ctx["CONFIG_HOME"])
    legacy = config / "environment.d"
    if legacy.is_dir():
        for path in sorted(legacy.glob("*.conf")):
            if path.name in ("95-qt-style.conf", "96-kate-balanced-glass.conf") or any(word in path.name.lower() for word in ("qt", "glass", "kate", "niri", "dms")):
                print(f"WARNING legacy userwide environment (not modified): {path}")
    override = config / "systemd/user/niri.service.d/override.conf"
    if override.is_file():
        text = override.read_text(encoding="utf-8", errors="replace")
        for line in text.replace("\\\n", " ").splitlines():
            if re.match(r"\s*ExecStopPost\s*=", line):
                try:
                    command = shlex.split(line.split("=", 1)[1])
                except ValueError:
                    command = []
                if "unset-environment" in command:
                    index = command.index("unset-environment")
                    if any(Path(arg.lstrip("-+!:@")).name == "systemctl" for arg in command[:index]) and any(
                            re.match(r"[A-Za-z_][A-Za-z0-9_]*=", arg) for arg in command[index + 1:]):
                        print(f"WARNING legacy systemctl unset-environment NAME=value in {override}; CLI requires bare names (not modified)")
            if not line.lstrip().startswith(("#", ";")) and "ExecStart" in line and re.search(r"kate", line, re.I):
                print(f"WARNING legacy unconditional Kate helper in {override} (not modified)")
    kdeglobals = config / "kdeglobals"
    if kdeglobals.is_file():
        settings = configparser.RawConfigParser(delimiters=("=",), strict=False)
        try:
            settings.read_string(kdeglobals.read_text(encoding="utf-8", errors="replace"))
            if settings.has_option("KDE", "widgetStyle"):
                print(f"WARNING legacy global KDE/widgetStyle in {kdeglobals} (not modified)")
            if settings.get("General", "ColorScheme", fallback="").strip().lower().startswith("dankmatugen"):
                print(f"WARNING legacy global General/ColorScheme=DankMatugen in {kdeglobals} (not modified)")
        except configparser.Error as exc:
            print(f"WARNING cannot parse legacy {kdeglobals}: {exc}")
    helpers = (
        Path(ctx["DATA_HOME"]) / "kate-balanced-glass/plugin/balancedglassplugin.cpp",
        Path(ctx["HOME"]) / ".local/lib/qt6/plugins/kf6/ktexteditor/katebalancedglassplugin.so",
    )
    for helper in helpers:
        if helper.is_file():
            print(f"WARNING legacy potentially unconditional Kate helper in {helper}; global QT_PLUGIN_PATH can expose it (not modified)")


def doctor(repo, manifest, ctx, mode):
    problems = 0
    tools = ["cmake", "ninja", "pkg-config", "c++", "niri", "dms"]
    tools.extend(manifest.get("binaries", []))
    for tool in dict.fromkeys(tools):
        found = shutil.which(tool)
        print(f"{'OK' if found else 'MISSING'} binary: {tool}")
        problems += not bool(found)
    try:
        entries = make_plan(repo, manifest, ctx, mode)
        for entry in entries:
            if entry["content"] is None:
                print(f"MISSING artifact: {entry['source']}")
                problems += 1
        print(f"OK profile configuration: {ctx['PROFILE_CONFIG']}")
    except (Error, OSError, ImportError, ValueError) as exc:
        print(f"ERROR unresolved configuration: {exc}")
        problems += 1
    legacy_warnings(ctx)
    return 1 if problems else 0


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    # Parent and child copies allow common options on either side of the command.
    def options(p, suppressed=False):
        default = argparse.SUPPRESS if suppressed else None
        p.add_argument("--home", default=default, help="relocate ALL XDG roots; ignore ambient XDG variables")
        p.add_argument("--repo", default=default, help="repository root (default: this package's parent)")
        p.add_argument("--manifest", default=default, help="manifest JSON path")
        p.add_argument("--mode", choices=("dark", "light"), default=argparse.SUPPRESS if suppressed else "dark")
    options(result)
    subs = result.add_subparsers(dest="command", required=True)
    for command in ("plan", "doctor", "build", "install", "rollback"):
        child = subs.add_parser(command)
        options(child, True)
        if command in ("install", "rollback"):
            child.add_argument("--apply", action="store_true", help="write changes (default is dry-run)")
    return result


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "session":
        from themekit.session import main as session_main
        return session_main(argv[1:])
    args = parser().parse_args(argv)
    try:
        repo = absolute(args.repo) if args.repo else Path(__file__).resolve().parent.parent
        ctx = context(args.home)
        if args.command == "rollback":
            rollback(ctx, args.apply)
            return 0
        manifest = load_manifest(repo, args.manifest)
        if args.command == "build":
            build(repo, manifest)
            return 0
        if args.command == "doctor":
            return doctor(repo, manifest, ctx, args.mode)
        entries = make_plan(repo, manifest, ctx, args.mode)
        if args.command == "plan":
            for entry in entries:
                status = "MISSING" if entry["content"] is None else "READY"
                print(f"{status} {entry['source']} -> {entry['target']}")
        else:
            if not args.apply:
                for entry in entries:
                    print(f"{'MISSING' if entry['content'] is None else 'PLAN'} {entry['source']} -> {entry['target']}")
                # A plan can be inspected before artifacts have been built.
                if any(e["content"] is None for e in entries):
                    print("Dry-run: missing artifacts; build before applying")
                    return 0
            install(entries, ctx, args.apply)
        return 0
    except (Error, OSError, ValueError, KeyError, TypeError, ImportError, subprocess.CalledProcessError) as exc:
        print(f"themekit: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

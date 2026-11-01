"""Small, private, reversible integration for the Niri/DMS profile.

Shared settings are restored by key, never by rolling back entire app configs.
The backup is deliberately private and contains original configuration bytes.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import tempfile
import warnings


class Error(ValueError):
    pass


_ABSENT = object()


@dataclass
class Resource:
    path: Path
    data: bytes
    mode: int = 0o600
    generated: bool = False


def _safe(path, ctx):
    path = Path(path)
    roots = [Path(ctx[k]) for k in ('CONFIG_HOME', 'DATA_HOME', 'STATE_HOME', 'CACHE_HOME')]
    if not path.is_absolute() or '..' in path.parts or not any(r in path.parents for r in roots):
        raise Error(f'target outside configured roots: {path}')
    for p in (path, *path.parents):
        if p.is_symlink():
            raise Error(f'symlink not allowed: {p}')
        if p != path and p.exists() and not p.is_dir():
            raise Error(f'non-directory ancestor: {p}')
    if path.exists() and not path.is_file():
        raise Error(f'not a regular file: {path}')
    if path.resolve() != path:
        raise Error(f'path escape: {path}')
    return path


def _write(path, data, mode, ctx):
    _safe(path, ctx)
    for parent in reversed(path.parents):
        if not parent.exists():
            parent.mkdir(mode=0o700)
    _safe(path, ctx)
    fd, temporary = tempfile.mkstemp(prefix='.niri-theme-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _safe(path, ctx)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _before(path):
    if not path.exists():
        return None
    return dict(data=base64.b64encode(path.read_bytes()).decode(), mode=stat.S_IMODE(path.stat().st_mode))


def _bytes(before):
    return b'' if before is None else base64.b64decode(before['data'], validate=True)


def _include(text, block, *, remove=False):
    begin, end = '// BEGIN niri-dms-theme', '// END niri-dms-theme'
    if begin in text or end in text:
        if text.count(begin) != 1 or text.count(end) != 1 or block not in text:
            raise Error('modified niri-dms-theme include block; repair it before restore/reinstall')
        return text.replace(block, '', 1) if remove else text
    if remove:
        return text
    return text + block


def _ini(text, values, section_name='Kate Plugins'):
    section = None
    seen = set()
    original = {}
    out = []
    for line in text.splitlines(keepends=True):
        header = re.match(r'^\s*\[([^\]]+)\]\s*$', line)
        if header:
            if section == section_name:
                for key in values.keys() - seen:
                    if values[key] is not None:
                        if out and not out[-1].endswith('\n'):
                            out[-1] += '\n'
                        out.append(values[key])
                    seen.add(key)
            section = header[1]
        match = re.match(r'^\s*([^=\s]+)\s*=', line)
        key = match[1] if match and section == section_name else None
        if key in values:
            if key in original:
                raise Error(f'duplicate owned INI key in [{section_name}]: {key}')
            original[key] = line
            seen.add(key)
            if values[key] is not None:
                out.append(values[key])
        else:
            out.append(line)
    missing = values.keys() - seen
    if missing and any(values[k] is not None for k in missing):
        if out and not out[-1].endswith('\n'):
            out[-1] += '\n'
        if section != section_name:
            out.append(f'\n[{section_name}]\n')
        for key in missing:
            if values[key] is not None:
                out.append(values[key])
    return ''.join(out), original


def _patch(data, kind, values):
    text = data.decode('utf-8')
    if kind == 'json':
        obj = json.loads(text or '{}')
        if not isinstance(obj, dict):
            raise Error('DMS settings must be a JSON object')
        old = {k: obj[k] for k in values if k in obj}
        for key, value in values.items():
            if value is _ABSENT:
                obj.pop(key, None)
            else:
                obj[key] = value
        return (json.dumps(obj, indent=2, ensure_ascii=False) + '\n').encode(), old
    section = {'kde': 'KDE', 'desktop': 'Desktop Entry'}.get(kind, 'Kate Plugins')
    result, old = _ini(text, values, section)
    return result.encode(), old


def _legacy(path, ctx):
    text = path.read_text() if path.exists() else ''
    removed = []
    out = []
    expected = {'QT_QPA_PLATFORMTHEME': 'qtengine', 'QT_QPA_PLATFORMTHEME_QT6': 'qtengine',
                'QT_STYLE_OVERRIDE': 'Darkly',
                'QT_PLUGIN_PATH': str(Path(ctx['HOME']) / '.local/lib/qt6/plugins'),
                'KATE_BALANCED_GLASS': '1', 'QT_QPA_PLATFORM': 'wayland',
                'XDG_CURRENT_DESKTOP': 'niri', 'XDG_SESSION_DESKTOP': 'niri'}
    chunks = []
    for line in text.splitlines(keepends=True):
        if chunks and chunks[-1].rstrip().endswith('\\'):
            chunks[-1] += line
        else:
            chunks.append(line)
    for line in chunks:
        drop = False
        if path.name == 'override.conf':
            if re.match(r'\s*Exec(?:Start|Stop)\w*\s*=', line):
                try:
                    words = shlex.split(line.split('=', 1)[1].replace('\\\n', ' '))
                except ValueError:
                    words = []
                if words and Path(words[0].lstrip('-+!:@')).name == 'systemctl':
                    commands = [i for i, w in enumerate(words) if w in ('set-environment', 'unset-environment', 'import-environment')]
                    if commands:
                        args = words[commands[0] + 1:]
                        qt_names = ('QT_QPA_PLATFORMTHEME', 'QT_QPA_PLATFORMTHEME_QT6', 'QT_STYLE_OVERRIDE', 'QT_PLUGIN_PATH')
                        drop = bool(args) and all(a.split('=')[0] in qt_names for a in args)
                        if words[commands[0]] == 'set-environment':
                            drop = drop and all('=' in a and a.split('=', 1)[1] == expected[a.split('=', 1)[0]] for a in args)
        else:
            match = re.match(r'^\s*([A-Z_]+)\s*=\s*(.*?)\s*$', line)
            if match:
                try:
                    value = shlex.split(match[2])
                except ValueError:
                    value = []
                key = match[1]
                drop = key in expected and value == [expected[key]]
                if path.name != '90-dms.conf' and key in ('QT_QPA_PLATFORM', 'XDG_CURRENT_DESKTOP', 'XDG_SESSION_DESKTOP'):
                    drop = False
        (removed if drop else out).append(line)
    return ''.join(out).encode(), removed


def _state(ctx):
    path = _safe(Path(ctx['STATE_HOME']) / 'niri-dms-theme/backup.json', ctx)
    state = json.loads(path.read_text()) if path.exists() else {'version': 1, 'records': []}
    if state.get('version') != 1 or not isinstance(state.get('records'), list):
        raise Error(f'invalid backup: {path}')
    return path, state


def _save(path, state, ctx):
    _safe(path, ctx)
    if path.parent.exists():
        path.parent.chmod(0o700)
    _write(path, (json.dumps(state, indent=2) + '\n').encode(), 0o600, ctx)


def _manager_environment():
    result = subprocess.run(['systemctl', '--user', 'show-environment'], check=True,
                            capture_output=True, text=True)
    values = {}
    for line in result.stdout.splitlines():
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        if len(parts) == 1 and '=' in parts[0]:
            key, value = parts[0].split('=', 1)
            values[key] = value
    return values


def _old_manager_values(ctx, values):
    expected = {'QT_QPA_PLATFORMTHEME': 'qtengine', 'QT_QPA_PLATFORMTHEME_QT6': 'qtengine',
                'QT_PLUGIN_PATH': str(Path(ctx['HOME']) / '.local/lib/qt6/plugins')}
    return {key: value for key, value in expected.items() if values.get(key) == value}


def _services(live):
    if not live:
        return
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    active = subprocess.run(['systemctl', '--user', 'is-active', '--quiet', 'dms.service'], check=False)
    if active.returncode == 0:
        subprocess.run(['systemctl', '--user', 'restart', 'dms.service'], check=True)


def apply(ctx, resources: list[Resource], environment: dict[str, str], *, dry_run=False, live=False):
    config, data, profile = (Path(ctx[k]) for k in ('CONFIG_HOME', 'DATA_HOME', 'PROFILE_CONFIG'))
    niri = _safe(config / 'niri/config.kdl', ctx)
    if not niri.exists():
        raise Error(f'missing Niri config: {niri}; create your Niri config before installing (preview does not require it)')
    for key, value in environment.items():
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key) or any(c in value for c in '\n\r\x00'):
            raise Error(f'invalid environment entry: {key}')
    statefile, state = _state(ctx)
    if state.get('pending'):
        raise Error(f'interrupted install; run restore first using {statefile}')
    specs = []
    for r in resources:
        if not isinstance(r.data, bytes) or not isinstance(r.mode, int) or not 0 <= r.mode <= 0o777:
            raise Error(f'invalid resource bytes or mode: {r.path}')
        p = _safe(r.path, ctx)
        if not any(Path(ctx[k]) in p.parents for k in ('PROFILE_CONFIG', 'PROFILE_DATA')):
            raise Error(f'resource is outside owned profile: {p}')
        specs.append((p, 'asset', r.data, r.mode, r.generated))
    envpath = profile / 'niri/environment.kdl'
    envtext = 'environment {\n' + ''.join(f'    {json.dumps(k)} {json.dumps(v)}\n' for k, v in environment.items()) + '}\n'
    specs.append((envpath, 'asset', envtext.encode(), 0o600, False))
    previous_include = next((r for r in state['records'] if r['kind'] == 'include'), None)
    if previous_include is None and any(marker in niri.read_text() for marker in ('// BEGIN niri-dms-theme', '// END niri-dms-theme')):
        raise Error('existing niri-dms-theme include marker has no backup; resolve it before installing')
    materialpath = profile / 'niri/material.kdl'
    includes = [envpath] + ([materialpath] if any(Path(r.path) == materialpath for r in resources) else [])
    prefix = ('\n' if previous_include['installed'].startswith('\n') else '') if previous_include else (
        '\n' if niri.read_bytes() and not niri.read_bytes().endswith(b'\n') else '')
    block = prefix + '// BEGIN niri-dms-theme\n' + ''.join(
        'include ' + json.dumps(str(path)) + '\n' for path in includes) + '// END niri-dms-theme\n'
    specs.append((niri, 'include', block, 0o600, False))
    specs.append((config / 'dms/settings.json', 'json', {
        'currentThemeName': 'custom', 'currentThemeCategory': 'custom',
        'customThemeFile': str(profile / 'dms/blue-black.json'), 'matugenTemplateQtengine': False}, 0o600, False))
    envfile = str(profile / 'session.env').replace('%', '%%')
    for unit in ('niri', 'dms'):
        content = ('[Unit]\nPartOf=niri.service\nRequisite=niri.service\nAfter=niri.service\n\n' if unit == 'dms' else '')
        content += f'[Service]\nEnvironmentFile={envfile}\n'
        specs.append((config / f'systemd/user/{unit}.service.d/50-niri-dms-theme.conf', 'asset', content.encode(), 0o600, False))
    toml = '[templates.niri_dms_glass]\n' + ''.join(f'{key} = {json.dumps(str(value))}\n' for key, value in (
        ('input_path', profile / 'matugen/translucent.colors.in'), ('output_path', Path(ctx['PROFILE_SHARE']) / 'color-schemes/DankMatugenTranslucent.colors')))
    specs.append((config / 'matugen/dms/configs/niri-dms-theme.toml', 'asset', toml.encode(), 0o600, False))
    wrapper = str(Path(ctx['PROFILE_DATA']) / 'bin/drawy-glass')
    desktop = '[Desktop Entry]\nType=Application\nName=Drawy Glass\nExec="' + wrapper.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '" %F\nIcon=drawy\nCategories=Graphics;\n'
    specs.append((data / 'applications/niri-dms-theme-drawy.desktop', 'asset', desktop.encode(), 0o600, False))
    # Shadow the normal launcher, changing only launch keys in an existing entry.
    # DBus activation must not bypass the per-process QML wrapper.
    filelight = _safe(data / 'applications/org.kde.filelight.desktop', ctx)
    wrapper = str(Path(ctx['PROFILE_DATA']) / 'bin/filelight-glass')
    quoted = wrapper.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
    launch = {'Exec': f'Exec="{quoted}" %u\n', 'DBusActivatable': 'DBusActivatable=false\n'}
    defaults = {key: f'{key}={value}\n' for key, value in {
        'Type': 'Application', 'Name': 'Filelight', 'Icon': 'filelight',
        'TryExec': 'filelight', 'MimeType': 'inode/directory;', 'Categories': 'Qt;KDE;Utility;'
    }.items()}
    _, present = _patch(filelight.read_bytes() if filelight.exists() else b'',
                        'desktop', {key: None for key in defaults})
    launch.update({key: line for key, line in defaults.items() if key not in present})
    specs.append((filelight, 'desktop', launch, 0o600, False))
    sessions = [data / 'kate/anonymous.katesession']
    sessiondir = data / 'kate/sessions'
    if sessiondir.exists():
        if sessiondir.is_symlink():
            raise Error(f'symlink not allowed: {sessiondir}')
        sessions.extend(sorted(sessiondir.glob('*.katesession')))
    for path in sessions:
        _safe(path, ctx)
        if path.exists() or path.name == 'anonymous.katesession':
            specs.append((path, 'ini', {'katebalancedglassplugin': 'katebalancedglassplugin=true\n'}, 0o600, False))
    kde = _safe(config / 'kdeglobals', ctx)
    if kde.exists():
        _, old = _ini(kde.read_text(), {'widgetStyle': None}, 'KDE')
        if old.get('widgetStyle', '').split('=', 1)[-1].strip() == 'Darkly':
            specs.append((kde, 'kde', {'widgetStyle': None}, 0o600, False))
    for name in ('environment.d/95-qt-style.conf', 'environment.d/96-kate-balanced-glass.conf', 'environment.d/90-dms.conf', 'systemd/user/niri.service.d/override.conf'):
        path = _safe(config / name, ctx)
        if path.exists():
            specs.append((path, 'legacy', None, 0o600, False))
    records = {r['path']: r for r in state['records']}
    changes = []
    seen = set()
    for path, kind, value, mode, generated in specs:
        path = _safe(path, ctx)
        if str(path) in seen:
            raise Error(f'duplicate target: {path}')
        seen.add(str(path))
        before = _before(path)
        current = _bytes(before)
        oldrecord = records.get(str(path))
        if kind == 'asset':
            if oldrecord and before is not None and not generated and _hash(current) != oldrecord['after']:
                if path.is_relative_to(Path(ctx['PROFILE_CONFIG']) / 'apps') and path.name in ('drawyrc', 'darklyrc'):
                    print(f'Keeping app preferences: {path}')
                    continue
                raise Error(f'owned asset changed: {path}; recover or move it aside before reinstall')
            result, original = value, None
        elif kind == 'include':
            previous = oldrecord['installed'] if oldrecord else value
            text = _include(current.decode(), previous)
            result, original = text.replace(previous, value, 1).encode(), None
        elif kind == 'legacy':
            result, original = _legacy(path, ctx)
        else:
            result, original = _patch(current, kind, value)
        record = oldrecord or dict(path=str(path), kind=kind, before=before, original=original,
                                   keys=list(value) if isinstance(value, dict) else [], generated=generated)
        if oldrecord and isinstance(value, dict):
            for key in value.keys() - set(record['keys']):
                record['keys'].append(key)
                if key in original:
                    record['original'][key] = original[key]
        if oldrecord and kind == 'desktop':
            value = {**record['installed'], **value}
        record['installed'] = value if kind == 'include' or isinstance(value, dict) else None
        record['after'] = _hash(result)
        records[str(path)] = record
        target_mode = mode if kind == 'asset' or before is None else before['mode']
        if result != current or before is None or before['mode'] != target_mode:
            changes.append((path, result, target_mode))
    # All parsing, symlink and drift checks happen before the backup or any asset write.
    if dry_run:
        return [str(p) for p, _, _ in changes]
    legacy_manager = _old_manager_values(ctx, _manager_environment()) if live else {}
    manager_baseline = state.setdefault('manager', {})
    for key, value in legacy_manager.items():
        manager_baseline.setdefault(key, value)
    state['records'] = list(records.values())
    state['pending'] = True
    _save(statefile, state, ctx)
    try:
        for path, content, mode in changes:
            _write(path, content, mode, ctx)
        if legacy_manager:
            # systemctl unset-environment takes bare names, never NAME=value.
            subprocess.run(['systemctl', '--user', 'unset-environment', *legacy_manager], check=True)
        state['pending'] = False
        _save(statefile, state, ctx)
    except Exception as exc:
        raise Error(f'install interrupted; originals saved in {statefile}; run restore: {exc}') from exc
    _services(live)
    return [str(p) for p, _, _ in changes]


def restore(ctx, *, dry_run=False, live=False):
    statefile, state = _state(ctx)
    if not statefile.exists():
        return []
    changes = []
    conflicts = []
    for record in reversed(state['records']):
        path = _safe(record['path'], ctx)
        current = _before(path)
        before = record['before']
        if current == before:
            continue
        raw = _bytes(current)
        kind = record['kind']
        if kind == 'asset':
            if not record['generated'] and _hash(raw) != record['after']:
                conflicts.append(record)
                warnings.warn(f'preserving modified asset {path}; backup retained in {statefile}', RuntimeWarning)
                continue
            result = _bytes(before) if before else None
        elif kind == 'include':
            result = _include(raw.decode(), record['installed'], remove=True).encode()
        elif kind == 'legacy':
            additions = ''.join(line for line in record['original'] if line not in raw.decode())
            result = raw + (b'\n' if additions and raw and not raw.endswith(b'\n') else b'') + additions.encode()
        else:
            missing = _ABSENT if kind == 'json' else None
            probe = {key: missing for key in record['keys']}
            _, present = _patch(raw, kind, probe)
            def value(mapping, key):
                item = mapping.get(key, missing)
                return item.split('=', 1)[-1].strip() if kind != 'json' and item is not None else item
            owned = [key for key in record['keys'] if value(present, key) == value(record['installed'], key)]
            changed = [key for key in record['keys'] if key not in owned and
                       value(present, key) != value(record['original'], key)]
            if changed:
                conflicts.append(dict(record, keys=changed))
                warnings.warn(f'preserving changed settings {changed} in {path}; backup retained in {statefile}', RuntimeWarning)
            values = {key: record['original'].get(key, missing) for key in owned}
            result, _ = _patch(raw, kind, values)
            # Avoid leaving a newly created JSON config when it has no other keys.
            if before is None and kind == 'json' and json.loads(result) == {}:
                result = None
            if before is None and kind == 'desktop':
                if result.strip() == b'[Desktop Entry]':
                    result = None
                elif result:
                    # Keep later user additions runnable without our removed wrapper.
                    defaults = {'Exec': 'Exec=filelight %u\n', 'Type': 'Type=Application\n',
                                'Name': 'Name=Filelight\n', 'Icon': 'Icon=filelight\n'}
                    _, present = _patch(result, 'desktop', {key: None for key in defaults})
                    result, _ = _patch(result, 'desktop', {key: line for key, line in defaults.items() if key not in present})
        if result != raw or (result is None and current is not None):
            changes.append((path, result, before['mode'] if before else 0o600))
    if dry_run:
        return [str(p) for p, _, _ in changes]
    manager_restore = {}
    if live and state.get('manager'):
        current_manager = _manager_environment()
        manager_restore = {key: value for key, value in _old_manager_values(ctx, state['manager']).items()
                           if key not in current_manager}
    try:
        for path, content, mode in changes:
            _safe(path, ctx)
            if content is None:
                if path.exists():
                    path.unlink()
            else:
                _write(path, content, mode, ctx)
        if manager_restore:
            subprocess.run(['systemctl', '--user', 'set-environment',
                            *(f'{key}={value}' for key, value in manager_restore.items())], check=True)
        if conflicts:
            state.update(records=conflicts, pending=False, manager={})
            _save(statefile, state, ctx)
        elif statefile.exists():
            _safe(statefile, ctx).unlink()
    except Exception as exc:
        raise Error(f'restore interrupted; backup retained in {statefile}: {exc}') from exc
    _services(live)
    return [str(p) for p, _, _ in changes]

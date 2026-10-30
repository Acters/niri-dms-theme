# Session environment

The default integration is **process-local**. Give the niri and DMS systemd
user services an `EnvironmentFile=` pointing at the generated profile
environment, or launch a process through `themekit.session exec`. Neither route
imports anything into the per-user systemd manager or D-Bus activation
environment. The parent project supplies the service templates and wrapper.

Deployment generates `niri-dms-theme/session.env` beneath its effective config
root. Use its absolute pathname for `EnvironmentFile=` and `--env-file`.
Process-local config roots such as `XDG_CONFIG_DIRS`,
`NIRI_DMS_THEME_CONFIG_HOME`, and `NIRI_DMS_THEME_DATA_HOME` can be carried in
that file; the legacy manager bridge deliberately does not import them.

The module uses only the Python standard library. From the repository root (or
with the repository on `PYTHONPATH`):

```sh
python -m themekit.session exec --env-file /absolute/path/profile.env -- application arg1 'arg with spaces'
python -m themekit.session status
```

`exec` requires the **current** `XDG_CURRENT_DESKTOP` to include `niri` as a
colon-separated identifier, case-insensitively. Setting that variable inside
the input file does not bypass the check. For an explicit test or one-off launch
outside niri:

```sh
python -m themekit.session exec --env-file /absolute/path/profile.env --allow-other-session -- application arg1
```

The `--` separator and a command are mandatory. The module copies the current
process environment, overlays the file's values, and calls
`os.execvpe(command[0], command, environment)`. Arguments are not shell commands;
no shell is started. A command runs with the resulting `PATH`. Only this process
and descendants inherit the overlay; unrelated desktop sessions do not. A
service's `EnvironmentFile=` similarly applies to that service, not globally.
Applications started independently through D-Bus or other services do not
necessarily inherit either environment.

`status` prints JSON describing the calling process's desktop and selected theme
variables. It does not call `systemctl`, create runtime state, or claim to report
the manager's current environment. Run it through `exec` to inspect an overlay:

```sh
python -m themekit.session exec --env-file /absolute/path/profile.env -- python -m themekit.session status
```

## Environment file format

Files must be UTF-8 regular files, at most 1 MiB, containing one assignment per
line, with optional blank lines and whole-line `#` comments:

```text
QT_QPA_PLATFORMTHEME="qt6ct"
QTENGINE_CONFIG="/absolute/path/qtengine.conf"
NIRI_DMS_THEME_PROFILE="dark"
XDG_DATA_DIRS="/absolute/path/share:/usr/local/share:/usr/share"
```

Names must match `[A-Za-z_][A-Za-z0-9_]*`. Values must be double-quoted.
Duplicate names, inline comments, `export`, unquoted values, shell expressions
outside quotes, NUL, carriage returns, and multiline values are rejected.
Assignments are parsed using `shlex`, never `source`, `eval`, or a shell.
`$HOME`, `$(command)`, and backticks **inside** a quoted value remain literal
text; no variable, command, tilde, or glob expansion takes place. Generate
absolute paths before writing the file. Escape literal backslashes as `\\` and
double quotes as `\"`; do not shell-escape dollar signs as `\$`, since `shlex`
preserves that backslash. `exec` permits all valid environment names, so use a
trusted generated file: variables such as `PATH` can affect what gets executed.

## Optional legacy user-manager bridge

**Do not put these commands in the default session hook.** They exist only for
an explicit legacy setup that cannot use process-local service environments:

```sh
python -m themekit.session manager-enter --env-file /absolute/path/profile.env --owner unique-session-token
python -m themekit.session manager-leave --owner unique-session-token
```

Both commands require a current niri desktop. There is no override for them.
`--owner` may be omitted only if `INVOCATION_ID` is present:

```sh
python -m themekit.session manager-enter --env-file /absolute/path/profile.env
python -m themekit.session manager-leave
```

The exact same owner must be used at entry and exit. Separate systemd service
invocations normally have different `INVOCATION_ID` values; pass a shared,
session-specific explicit token when entry and exit run in different units or
invocations. Tokens contain 1–256 ASCII letters, digits, `_`, `.`, `:`, or `-`.
Do not reuse a token across concurrent sessions.

Only these values are imported, and only when present in the file:

- `QT_QPA_PLATFORMTHEME`, `QT_QPA_PLATFORMTHEME_QT5`, `QT_QPA_PLATFORMTHEME_QT6`
- `QTENGINE_CONFIG`, `QT_PLUGIN_PATH`, `QT_STYLE_OVERRIDE`
- `NIRI_DMS_THEME_PROFILE`, `XDG_DATA_DIRS`

Other file assignments are ignored by the bridge. In particular it never
imports or unsets `DISPLAY` or `XDG_CURRENT_DESKTOP`. The manager ownership
marker is `NIRI_DMS_THEME_MANAGER_OWNER`.

The bridge invokes only `systemctl --user show-environment`,
`systemctl --user set-environment NAME=value ...`, and
`systemctl --user unset-environment NAME ...` through subprocess argv. Unset
arguments are bare names, never `NAME=value`. It does **not** touch the D-Bus
activation environment: D-Bus has no corresponding unset API with which to
reliably reverse an import.

### Ownership and recovery

`XDG_RUNTIME_DIR` must be an absolute, non-symlink directory owned by the current
user with mode `0700`. The bridge creates its private `niri-dms-theme`
subdirectory with mode `0700`. It serializes toolkit operations with `flock` on
`manager.lock`, and atomically writes `manager-state.json`, both mode `0600`.
Runtime state paths must resolve exactly to their expected locations; symlinks,
hard-linked files, foreign ownership, and permissive modes are refused. The
advisory lock file remains after normal exit. No runtime polling or daemon is
used.

Before import, the snapshot records each selected key's original value, including
whether it was unset, plus the installed values and owner. An owned repeated
entry with the same file is idempotent: it does not replace the original
snapshot or reapply values over intervening edits. A different file for an
already-active owner requires leaving first. Foreign snapshots, ownership
markers, and markers without a snapshot are refused rather than overwritten.

On leave, the snapshot owner and manager marker must match. A key is restored
only if its current manager value still equals the installed value. Foreign
edits and foreign unsets are preserved. An originally absent key is removed
using its bare name. The ownership marker is rechecked before removal. The
snapshot is deleted only after restoration and marker removal succeed.

An import failure attempts to roll back partial changes using the same
compare-before-restore rule. If rollback or leave fails, the recoverable
snapshot and, where possible, ownership marker are retained. Retry
`manager-leave` with the same owner in a niri context after fixing the manager
failure. An incomplete transaction must be left before entering again. A
completed restoration whose marker removal succeeded but cleanup failed can
finish snapshot cleanup on a repeated leave, without changing manager values.
If ownership was replaced or disappeared unexpectedly, the bridge refuses to
apply the old snapshot; do not delete another session's ownership marker to
force restoration.

The systemd user manager is **per user, not per desktop session**. This optional
bridge cannot isolate simultaneous niri and GNOME/KDE sessions or guarantee
that unrelated newly started user services avoid its theme values. Its advisory
lock coordinates toolkit commands only. Other tools do not honor that lock,
and `systemctl` has no atomic compare-and-set environment API; an external
writer racing between a read and a write cannot be fully excluded. Ownership
and drift checks reduce accidental clobbering, but are not a concurrency
isolation boundary. Use process-local `EnvironmentFile=`/`exec` integration for
concurrent desktops.

## Python / deployment CLI integration

A deployment CLI can lazily delegate without a dependency on its implementation:

```python
from themekit.session import main
return main(argv)
```

`main(argv=None)` returns an integer exit status and is also runnable via
`python -m themekit.session`. The subprocess boundary is the module-level
`run_manager(arguments)` function, which can be replaced by a fake in tests.
The tests in [test_session.py](../tests/test_session.py) mock that boundary and
`os.execvpe`; they never contact a real user manager or execute applications.

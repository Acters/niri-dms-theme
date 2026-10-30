# Reviewed activation / migration

Nothing here should be applied blindly to an already-running desktop. First run `plan`, `doctor`, builds and isolated tests. Keep the current session available while reviewing diffs. Do not restart the user bus or close unsaved app windows from an installer.

## 1. Stage resources

```sh
./bin/themekit build
./bin/themekit install --apply
```

This creates dedicated profile directories under the XDG config/data roots, plus a private transaction ledger under the XDG state root. Use `--mode light` if the bootstrap Qt palette should initially be light; DMS will later regenerate the current mode.

The generated profile contains:

- `session.env`: literal, quoted `KEY=value` records accepted by systemd EnvironmentFile and the session helper. Do not `source` it as a shell program.
- `niri/environment.kdl`: matching process/spawn variables.
- `integration/`: staged unit drop-ins, Matugen registration, Kate flag fragment, and optional Drawy desktop entry. They are not active merely because they exist.

## 2. Audit and retire legacy forcing

Preserve unrelated preferences and hardware flags. Review, rather than blindly deleting, each legacy location reported by `doctor`:

| Location | Review |
|---|---|
| User `environment.d` Qt files | Retire profile-forcing Qt variables after scoped activation works. |
| DMS-named global env file | Move Niri-only desktop/backend variables into session scope; decide separately whether terminal/electron/menu preferences are intentionally global. |
| Niri service override | Keep hardware/renderer settings. Replace old manager import/cleanup only after selecting the new lifecycle design. |
| DMS service overrides | Keep its Niri unit relationship; consolidate duplicate theme variables into the profile EnvironmentFile. |
| Niri main environment block | Remove/merge conflicting old Qt paths and include the generated profile fragment instead; keep input, outputs, bindings and window rules. |
| Global KDE `widgetStyle` | The profile uses a scoped `QT_STYLE_OVERRIDE=Darkly`; it does not need to force Darkly in other DEs. Restore the desired native selection explicitly if appropriate. |
| Global `DankMatugen*` color-scheme selection | DMS may apply this globally on theme changes. Choose the intended outside-session baseline deliberately; do not guess it from a backup. |
| Old unconditional Kate helper | Retire/disable that copy after validating the scoped module so another plugin search path cannot select it. Never delete an entire personal plugin directory. |

`systemctl --user unset-environment` takes **names**, for example `QT_QPA_PLATFORMTHEME`, not `QT_QPA_PLATFORMTHEME=qtengine`. Restoring previous values is safer than indiscriminate unsetting. Do not confuse the CLI with systemd's `UnsetEnvironment=` directive, which has different semantics.

Earlier D-Bus activation-environment imports can persist independently of the manager. There is no exact unset operation in that activation API. A later clean login may be required; this kit does not restart the bus or pretend manager cleanup resets it.

## 3. Activate process-local scope

After resolving the legacy overlap, install the staged Niri and DMS drop-ins into their corresponding user unit drop-in directories. They reference the generated profile EnvironmentFile. Review their paths first, then reload units at a convenient session boundary. A restart is needed for existing processes to inherit changed environment; do not restart the compositor blindly during work.

Include the generated `niri/environment.kdl` from the Niri config, using its absolute XDG config path. This covers compositor-spawned applications as well as DMS-launched applications. Service EnvironmentFile settings alone do not rewrite the environment of already-running terminals.

The default templates do not set or unset the shared manager environment. The optional legacy bridge is separate and must be explicitly chosen; read [session design](session.md).

## 4. Connect DMS generation

Point DMS's custom theme picker to the installed profile DMS theme. The intended owned settings are:

```text
currentThemeName = custom
currentThemeCategory = custom
customThemeFile = <profile config>/dms/blue-black.json
matugenTemplateQtengine = false
```

Copy/link the staged Matugen registration into DMS's user Matugen configs directory only after review. Its generated palette target is inside the owned profile data directory. Do not edit generated palettes as source.

The built-in KDE color-scheme template and `plasma-apply-colorscheme` behavior are separate from qtengine. If strict other-DE isolation is required, review/disable the stock KDE template and make sure the global KDE scheme is not still a `DankMatugen*` one that DMS will apply. Existing GTK/browser/terminal templates may also write global files; this repo does not silently migrate those unrelated integrations.

## 5. Enable apps

Enable **Balanced Glass Automatic Theme** in Kate's plugin settings for desired sessions. The supplied fragment identifies the one flag, but full session files must not be copied into Git. Keep native editor automatic selection enabled. Restart Kate once to discover a newly installed plugin. Thereafter palette changes switch views live.

Drawy remains opt-in. Use the installed `drawy-glass` wrapper within the marked Niri session, or review/install its separate desktop entry. It uses private app config/data/cache/state and the rounded-container style. Outside that session the wrapper runs native Drawy. Its canvas background also appears in PNG/SVG/clipboard output, so exported backgrounds can be translucent.

## 6. Verify before retiring the old setup

Check service/process environment, theme changes, new Kate tabs/splits, app restarts, Drawy exports, and the next non-Niri login. Do not claim cross-DE isolation from a single in-session toggle test. Keep rollback snapshots private and preserve live cursor/layout/application changes rather than restoring entire old session files.

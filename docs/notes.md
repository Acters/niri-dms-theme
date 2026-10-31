# Implementation notes

## What the commands do

`preview` builds the shared style (and Kate helper when needed), creates an isolated home, prepares the palette/settings, and opens Kate, Dolphin or Drawy. On an active Niri socket it temporarily adds an optional exact-preview-ID rule to the original Niri config, then removes only its own block on exit, preserving other edits. Missing Niri skips the backdrop effect, not the app. It preserves existing preferences when reusing a known preview home. A real home or unrelated populated directory is refused. The printed preview directory is not deleted on exit.

`install` builds both helpers before changing settings. It installs owned resources, adds marked Niri environment/material includes, writes process-local Niri/DMS service drop-ins, connects DMS's custom theme and Matugen output, enables Kate's plugin flag in existing sessions, and installs a Drawy Glass launcher. Existing bindings, GPU settings, other plugins, session data and unrelated preferences are kept. With no `--home`, it reloads user units and refreshes active DMS—not Niri or your apps.

`restore` reverses those owned settings, not whole app/session snapshots. Later user changes are retained. Modified app configuration or assets are kept with a warning and backup, rather than blocking the entire restore. Generated palette changes are expected. A manually edited marked Niri include requires review so the command cannot leave a dangling include.

For development, `--home PATH` redirects all XDG roots and suppresses service/manager operations. The alternate install home must contain a Niri config; `preview` needs no desktop configuration at all. `--dry-run` on install/restore does not build or write.

## Scope and backups

New theme variables belong to Niri/DMS process environments, not the global user manager. Known obsolete Qt forcing in the earlier environment files/import hooks is removed with backups. On a real install, only manager values that exactly match the earlier qtengine/helper setup are cleared; unrelated values are retained. No new global theme values are imported.

The user manager and D-Bus activation environment are shared by one UID. Old D-Bus activation overrides cannot be queried/unset exactly; a fresh graphical login may still be needed after legacy cleanup. This is not a concurrent multi-DE/session orchestrator. Existing terminals keep their inherited environment until reopened. Pre-existing global KDE color-scheme and GTK preferences are not guessed/reset.

Original data is stored privately at `$XDG_STATE_HOME/niri-dms-theme/backup.json`. Do not put it in Git. Reinstall retains the initial baseline. Restore never recursively deletes app-data, cache or artwork directories. Source/theme assets are separate from runtime-generated files.

Darkly uses its normal config filename. Profile defaults are supplied through the scoped config search path; existing primary user preferences take priority. The Drawy profile has its own corner-radius override and app config/data/cache/state. Its wrapper falls back to ordinary Drawy outside the marked Niri session.

## Preset and native limits

- Qt backgrounds: about 10% palette alpha; Darkly surface sliders: 15%, independently configurable. Widget shadows are off to prevent gray wash through translucent fields.
- Light surfaces: near-white with pale-blue raised colors. Dark base: black.
- Kate: 40% theme background, double-filled in normal rows to about 64%; gutter about 64%. Empty space after EOF may have a single fill. The plugin switches names using public APIs and has no polling loop.
- Drawy: native 50% canvas color combines with window layers to about 64% on the tested stack. Exported PNG/SVG/copied artwork can have translucent backgrounds. Ink colors are not faded.
- Shared `NiriGlass` wraps unmodified Darkly using public Qt6 APIs. Safe toolbar/container backgrounds receive a subtle film/rim; docks receive only an edge. Text/drawing/editor content is excluded. Custom-painted surfaces may not participate. Menus, tooltips, fields and headers use background-only style hooks.
- The same module preserves Drawy's rounded Frame containers and hides only the version-guarded unused hamburger in Drawy 1.0.2. Other apps keep native layout metrics. No application package is patched.
- Compositor rules keep blur enabled, Xray off, and noise 0.008 for Kate/Dolphin/Drawy and their popups. They do not override saturation; Niri keeps its existing behavior. They don't desaturate foreground ink/icons or alter unrelated app rules. Add other app IDs to the small material asset as needed. There is no refraction shader, global saturation override, or GTK/Electron skin.

Tested with Qt 6.12/KF6 6.31, Kate 26.08.2, Darkly 0.5.42, Drawy 1.0.2, qtengine r47 and the Niri build supporting background blur/Xray. Qt5 needs its own matching style plugin.

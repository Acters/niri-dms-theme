# Implementation notes

## What the commands do

`preview` builds the shared style (and Kate helper when needed), creates an isolated home, prepares the palette/settings, and opens Kate, Dolphin, Drawy, Gwenview or Filelight. On an active Niri socket it temporarily adds an optional exact-preview-ID rule to the original Niri config, then removes only its own block on exit, preserving other edits. Missing Niri skips the backdrop effect, not the app. It preserves existing preferences when reusing a known preview home. A real home or unrelated populated directory is refused. The printed preview directory is not deleted on exit.

`install` builds both helpers before changing settings. It installs owned resources, adds marked Niri environment/material includes, writes process-local Niri/DMS service drop-ins, connects DMS's custom theme and Matugen output, enables Kate's plugin flag in existing sessions, and installs a Drawy Glass launcher. Existing bindings, GPU settings, other plugins, session data and unrelated preferences are kept. With no `--home`, it reloads user units and refreshes active DMS—not Niri or your apps.

`restore` reverses those owned settings, not whole app/session snapshots. Later user changes are retained. Modified app configuration or assets are kept with a warning and backup, rather than blocking the entire restore. Generated palette changes are expected. A manually edited marked Niri include requires review so the command cannot leave a dangling include.

For development, `--home PATH` redirects all XDG roots and suppresses service/manager operations. The alternate install home must contain a Niri config; `preview` needs no desktop configuration at all. `--dry-run` on install/restore does not build or write.

## Scope and backups

New theme variables belong to Niri/DMS process environments, not the global user manager. Known obsolete Qt forcing in the earlier environment files/import hooks is removed with backups. On a real install, only manager values that exactly match the earlier qtengine/helper setup are cleared; unrelated values are retained. No new global theme values are imported.

The user manager and D-Bus activation environment are shared by one UID. Old D-Bus activation overrides cannot be queried/unset exactly; a fresh graphical login may still be needed after legacy cleanup. This is not a concurrent multi-DE/session orchestrator. Existing terminals keep their inherited environment until reopened. Pre-existing global KDE color-scheme and GTK preferences are not guessed/reset.

Original data is stored privately at `$XDG_STATE_HOME/niri-dms-theme/backup.json`. Do not put it in Git. Reinstall retains the initial baseline. Restore never recursively deletes app-data, cache or artwork directories. Source/theme assets are separate from runtime-generated files.

Darkly uses its normal config filename. Profile defaults are supplied through the scoped config search path; existing primary user preferences take priority. The Drawy profile has its own corner-radius override and app config/data/cache/state. Its wrapper falls back to ordinary Drawy outside the marked Niri session.

## Scoped reading surfaces and KDE apps

Kate completion and Dolphin status/details get background-only backing with an alpha floor of 220/255. Gwenview's custom filename popup gets a local background brush chosen for contrast with its existing text; Qt tooltips in Gwenview get stronger ToolTipBase backing. No global View, Window, Tooltip or Selection palette role is made opaque.

Gwenview rebuilds page palettes through KColorSchemeManager. The single active generated palette now lives under the profile's `share/color-schemes` directory, also used by qtengine and Matugen. Upgrades retain the retired generated-path file and its backup record for existing processes and eventual restore; no new runtime reference uses it, and restore removes both owned generations. A cascaded Gwenview default selects its scheme ID without editing the primary user preferences. This fixes the opaque fallback page palette; the native window already has an alpha buffer. An explicit user color-scheme choice or image-background preference takes precedence. This changes backdrop brushes, not image-pixel opacity.

Filelight menus/radial tooltips are QQC2 QML, so QStyle cannot paint them. Its normal desktop launcher is redirected to a standalone, profile-gated launcher; existing desktop-entry metadata is retained and launch keys are reversible. Outside marked Niri processes it executes ordinary Filelight. Inside the profile it uses `qmake6` to locate `org.kde.desktop`, creates a private temporary module overlay, links stock components, and copies Menu/ToolTip with an alpha floor of 0.88. A companion Filelight-only Kirigami controls overlay changes AbstractApplicationWindow's clear color to transparent; the native theme-colored QML background still paints the surface. This prevents a translucent light clear color from saturating the buffer to white. Menu, tooltip and toolbar backgrounds also receive an input-transparent QML material layer using the shared QWidget film/accent/rim coefficients. It paints beneath native foreground content, retains native popup shadows and toolbar separators, and updates on size/palette changes without polling. The radial chart and its colors are never decorated. The effective KDE style, foreground and native chrome are preserved. The overlay is regenerated on each launch and cleaned up after the app exits, with termination signals forwarded; there is no watcher or daemon. Changed upstream QML layouts fail clearly rather than silently loading Basic. Other QML apps and terminal `filelight` commands are untouched.

The initial Filelight verification missed the clear-layer problem: a light capture had saturated RGB despite nonzero transparency. Comparing the corrected clear layer restores the intended surface RGB instead of clipped white; unchanged window alpha values alone are not an acceptance test. The other four apps do not receive this QML overlay.

A partial custom QML style was rejected because it retained KDE components but lost KDE theme initialization. Hidden QML popup colors can initially be invalid until attached to a window; validation must sample a visible popup. Native Filelight checks confirmed the same low-alpha scheme RGB with 0.88 backing on visible light/dark reading panels, rather than inferring success from hidden objects.

Native Gwenview captures confirmed its page background changing from opaque fallback to layered translucency while sample thumbnail pixels stayed identical and opaque. Native Dolphin status backing measured alpha 228/255 against 38/255 in surrounding content on the tested stack. These are rendered application checks; exact effective opacity depends on nesting and the compositor backdrop.

## Preset and native limits

- Qt backgrounds: about 10% palette alpha; Darkly surface sliders: 15%, independently configurable. Widget shadows are off to prevent gray wash through translucent fields.
- Light surfaces: near-white with pale-blue raised colors. Redundant group/tab-panel frame fills are omitted only in light mode to reduce stacked backing; foreground and content settings are unchanged. Dark base and dark structural fills remain black/native.
- Kate: 40% theme background, double-filled in normal rows to about 64%; gutter about 64%. Empty space after EOF may have a single fill. The plugin switches names using public APIs and has no polling loop.
- Drawy: native 50% canvas color combines with window layers to about 64% on the tested stack. Exported PNG/SVG/copied artwork can have translucent backgrounds. Ink colors are not faded.
- Shared `NiriGlass` wraps unmodified Darkly using public Qt6 APIs. Safe toolbar/container backgrounds receive a subtle film/rim; docks receive only an edge. Text/drawing/editor content is excluded. Custom-painted surfaces may not participate. Menus, tooltips, fields and headers use background-only style hooks. Standard push buttons, combo/spin boxes and tabs receive only an outer two-pixel rim so native glyphs, arrows and selected-state fills stay intact. Standard dialog controls inherit those hooks; dialog backgrounds and generic content are not overlaid.
- The same module preserves Drawy's rounded Frame containers and hides only the version-guarded unused hamburger in Drawy 1.0.2. Other apps keep native layout metrics. No application package is patched.
- Compositor rules keep blur enabled, Xray off, and noise 0.008 for Kate/Dolphin/Drawy/Gwenview/Filelight and their popups. They do not override saturation; Niri keeps its existing behavior. They don't desaturate foreground ink/icons or alter unrelated app rules. Add other app IDs to the small material asset as needed. There is no refraction shader, global saturation override, or GTK/Electron skin.

Tested with Qt 6.12/KF6 6.31, Kate 26.08.2, Darkly 0.5.42, Drawy 1.0.2, qtengine r47 and the Niri build supporting background blur/Xray. Qt5 needs its own matching style plugin.

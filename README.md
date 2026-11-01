# Niri + DMS glass theme

A shared liquid-glass-inspired material for Qt6 controls, with balanced Kate editor backgrounds and a separate Drawy canvas profile.

## See it

```sh
./bin/themekit preview drawy
./bin/themekit preview kate
./bin/themekit preview dolphin
./bin/themekit preview gwenview
./bin/themekit preview filelight
```

That builds the needed helper if necessary and **opens the app** with an isolated profile. No environment variables or temporary-home setup to do yourself. Close the window when finished. Its directory is printed and kept, so save artwork outside it if you want to keep it permanently.

To choose the appearance or reuse an earlier temporary home:

```sh
./bin/themekit preview drawy --mode light
./bin/themekit preview kate --home /path/to/your/temp-home
```

A preview uses the selected light/dark palette without changing DMS or normal app preferences. Inside Niri, a temporary rule normalizes only the preview window's backdrop and is removed on exit. If Niri isn't available, the style still opens without that compositor effect.

## Use it normally

From a configured Niri + DMS session:

```sh
./bin/themekit install
```

This builds the helpers, selects the shared **NiriGlass** style, connects DMS palette generation, installs scoped Kate/Dolphin/Gwenview/Filelight/Drawy backdrop rules, enables Kate's plugin for existing sessions, and adds a **Drawy Glass** launcher. The normal Filelight desktop launcher uses a process-local popup style; direct `filelight` terminal launches remain stock. Gwenview gets a default selection of the same generated scheme so its page backgrounds follow the theme; explicit user scheme choices still win. DMS is refreshed if it is running; Niri and your app windows are not closed. Reopen apps/terminals once to pick up the environment. If Kate was running during installation, enable **Balanced Glass** in **Settings → Configure Kate → Plugins → Apply**; the running session can otherwise save its old disabled state back. Kate then follows light/dark changes live. Your font and session preferences are retained.

```sh
./bin/themekit restore
```

Restore removes this activation and restores the settings it changed. Unrelated preferences and app data are kept. Backups are private user state, not files in this repo. Add `--dry-run` to install or restore if you want to inspect changes first.

Run as your desktop user, **not sudo**. You need Darkly, qtengine, Niri/DMS, CMake, a C++ compiler, Qt6 development files and the KDE TextEditor/CoreAddons/Config SDK. Filelight's popup launcher also uses `qmake6` to locate the installed KDE Qt Quick style. The chosen app must be installed to preview it. Missing build dependencies stop before desktop settings are changed.

## Important details

- The shared Qt material adds restrained sheen/rims to suitable control surfaces, not text or drawing content. Backdrop saturation is left to Niri; the managed apps retain blur and noise 0.008. Reading overlays get stronger backing: Kate completion, Dolphin status/details, Gwenview filename/tooltips, and Filelight menus/tooltips. Filelight's QML menus, tooltips and toolbars receive the matching glass finish beneath their text/icons; its chart palette stays native. General surfaces and foreground pixels are not faded. This is not refractive lens distortion; GTK/Electron and other custom QML surfaces remain outside the shared style.
- The profile is scoped to Niri/DMS processes; there is no recurring global manager-environment bridge.
- Existing application windows cannot have their inherited environment rewritten. Reopen them after installation/restoration. Pre-existing D-Bus activation overrides may still require a fresh login; this tool does not restart your bus.
- Drawy's translucent canvas also affects PNG/SVG/clipboard backgrounds. Normal Drawy remains available; use **Drawy Glass** when you want this profile.
- Editor/container opacity is layered; the exact appearance can vary by widget. The original syntax themes are retained.

[Implementation and limits](docs/notes.md) · [Theme credits/licenses](NOTICE.md)

Developer checks: `python3 -m unittest discover -s tests -v` and `./tools/test-plugins`. Source: [Acters/niri-dms-theme](https://github.com/Acters/niri-dms-theme).

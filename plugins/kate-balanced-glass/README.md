# Balanced Glass Automatic Theme

A public-API KTextEditor application plugin. Each main window has a coalesced one-shot sync after initial load, editor config/palette changes, repository reloads and new views. It selects a named theme with `View::setConfigValue("theme", name)` only when the view differs. There is no polling loop and no global renderer configuration write.

This repository variant activates only when `NIRI_DMS_THEME_PROFILE=niri-dms-glass` and `XDG_CURRENT_DESKTOP` contains `niri` (case-insensitive colon list). Outside that context it creates an inert plugin view, even if the session checkbox is enabled.

Defaults are `Balanced Glass Light` / `Balanced Glass Dark`, configurable via the read-only `katebalancedglassrc` `[Themes] Light/Dark` keys. Missing themes leave views unchanged rather than forcing a fallback.

Kate finds this module in the `kf6/ktexteditor` namespace under its Qt plugin search paths. It is enabled per Kate session with `katebalancedglassplugin=true` in `[Kate Plugins]`, or the normal Plugins checkbox. Custom metadata does not make it enabled by default.

Tests exercise existing, new and split views, multiple windows, native automatic mode remaining active, and non-Niri/unmarked sessions. The renderer still paints row backgrounds twice: this is not a KTextEditor patch. Local view themes do not serialize through the tested session API.

Disable the plugin and restart Kate to restore native inheritance. Merely setting an empty theme name does not clear a view's explicit override through public APIs. A later manual per-view theme override can remain until the next ordinary sync event; the plugin deliberately does not fight every local config signal.

Build and test through the repository [CLI](../../bin/themekit) and [test runner](../../tools/test-plugins). Rebuild after ABI-breaking Qt/KF6 upgrades.

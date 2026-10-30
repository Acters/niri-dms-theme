# Drawy Glass Qt style

A tiny public Qt `QStylePlugin`/`QProxyStyle` wrapping stock Darkly. It changes `PM_ToolBarItemMargin` to 16 only for widgets inheriting Drawy's `Frame`, because Drawy uses that metric as the painted container radius. Ordinary Qt toolbar margins remain 2; the other metrics/rendering/palette are delegated.

The adapter also hides Drawy 1.0.2's unused bottom-left `application-menu` button only when its parent is `BottomLeftWidgets`, it has no menu/default action, and it is absent from the layout. The exact version guard avoids hiding a future legitimate feature. Tests cover managed/connected buttons, the real menu and a future-version case.

The profile wrapper selects this style only for Drawy within the marked Niri session. Its own Darkly config overrides the button radius to 16; other Darkly preferences cascade from shared/user defaults. No Drawy/Darkly binary is patched.

Canvas transparency uses Drawy's native setting, not this style adapter, and also affects native PNG/SVG/clipboard backgrounds. Keep that separate from UI styling decisions. Build/test with the repository tools; choosing this style does not imply that every other app should use it.

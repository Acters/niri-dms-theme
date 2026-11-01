# NiriGlass Qt 6 style

`NiriGlass` is a public `QStylePlugin` wrapping an installed, unmodified **Darkly** style. Its only build dependency is Qt 6 Widgets (CMake and a C++17 compiler are required). It uses no private Qt/Darkly APIs, package patches, polling, services, window opacity, or graphics effects.

## Build and native checks

```sh
cmake -S plugins/glass-style -B plugins/glass-style/build
cmake --build plugins/glass-style/build -j2
ctest --test-dir plugins/glass-style/build --output-on-failure
```

The module has no `lib` prefix: `build/plugins/styles/niriglassstyle.so`. The native executable is `build/style-test`. CTest supplies an offscreen platform and the build plugin search path. Darkly must be discoverable by Qt; the factory returns null if it is unavailable, rather than silently substituting a different base. No QtTest, KDE, or Darkly development headers are required. The executable creates a temporary HOME/XDG tree before QApplication startup. An integration runner supplying its own isolated home and resource paths can set `NIRI_GLASS_TEST_HOME=1` to preserve that environment (including `QTENGINE_CONFIG`).

The parent theme launcher owns installation and process-local environment setup. This directory does not install anything or change user configuration. Selection is `QT_STYLE_OVERRIDE=NiriGlass`, with a Qt plugin search root containing `styles/niriglassstyle.so`. Material activates only when both conditions hold:

* `NIRI_DMS_THEME_PROFILE=niri-dms-glass` (exact value).
* `XDG_CURRENT_DESKTOP` contains a colon-separated `niri` desktop identifier (case insensitive).

COSMIC, an unmarked process, and other desktop identifiers use stock Darkly painting and metrics. Activation is intended to be fixed at process launch, not switched by changing environment variables in a running application. Widget palette/style/size events refresh material without timers.

## Material boundary

A restrained white film (14 alpha in dark palettes, 26 in light palettes), a tiny palette-accent sheen, and a directional gradient rim follow the accepted Drawy prototype. The dark rim endpoint is a one-pixel stroke, not a filled black shadow. No foreground palette roles, opacity, input behavior, widget layout, or general margins are rewritten.

* **Light-mode group/tab panels:** redundant structural frame fills are omitted through copied paint options. Palette RGB, foreground, controls, layout and content settings are unchanged; dark mode retains native fills. Editor/canvas ancestry exclusions still apply. The accepted gallery reduced stacked structural backing from about 42% to 27%; exact alpha varies with each app's nesting.
* **Drawy `Frame` only:** child underlay, rounded radius 16; the `PM_ToolBarItemMargin=16` compatibility metric applies only to application name `drawy`, because Drawy uses that metric as its painted corner radius. Other applications/classes keep Darkly metrics.
* **`QToolBar`:** child underlay beneath real child controls; empty/hidden-action toolbars do not paint a glass box.
* **`QDockWidget`:** edge-only child layer, clipped to the outer two-pixel boundary so rounded corner arcs cannot cross parent-painted title content. No film crosses the parent-painted native title text or icons.
* **Menus, tooltips, line-edit fields:** material at `PE_PanelMenu`, `PE_PanelTipLabel`, `PE_PanelLineEdit` / `PE_FrameLineEdit`, which are background/frame passes before foreground painting. Nested primitive calls get a single material pass.
* **Headers:** `CE_HeaderSection` and `CE_HeaderEmptyArea`, never the composite header/label pass.
* **Push buttons and tabs:** a directional rim clipped strictly to the outer two pixels after native painting. Labels/icons, selected/default fills and focus indication inside that boundary remain native. Flat/command-link buttons are excluded.
* **Combo boxes and spin boxes:** the same outer-boundary rim; native arrow/text subcontrols and hit testing remain unchanged. Frameless and unusually small controls are excluded. Standard dialog buttons/fields inherit these treatments; dialog contents receive no blanket film.

Layer children are mouse-transparent, unfocusable, and lowered beneath real children, including newly polished and explicitly lowered children. Resize/show and palette/style/theme events update them. Unpolish removes them. They do not modify host geometry, layout margins, native title painting, or real child order relative to each other.

No blanket `QWidget`/`QFrame` decoration exists. Labels, menu bars, status bars, ordinary frames, text view internals, and generic content widgets receive no material child. `KTextEditor::View`, `KateViewInternal`, and `Canvas` ancestors exclude descendants from both content layers and background decoration, keeping editor/canvas surfaces unchanged. Separate popup/dialog windows stop that ancestry check, so their controls still receive the material. The Drawy 1.0.2 unmanaged `application-menu` orphan guard is retained only for application name `drawy`, exact version 1.0.2, `BottomLeftWidgets` parent, no layout membership, no action, and no menu; later versions and real controls remain untouched.

## Reading-surface exceptions

These are scoped backgrounds, not general View/Window palette changes:

- Kate `KateCompletionWidget`: a Base-color backing with an alpha floor of 220/255, beneath the child completion tree and inside the frame's contents rectangle. The native popup border, row text and icons remain above/outside it.
- Dolphin `DolphinStatusBar`: Window-color backing at `PE_Frame` (Small capsule) and `PE_PanelStatusBar` (FullWidth), with the same alpha floor. The scroll area and status text paint afterwards.
- Gwenview `Gwenview::ToolTipWidget`: its custom paint event bypasses QStyle and paints text on a Highlight gradient. A widget-local Highlight brush chooses the better contrast of Window versus Highlight RGB against the unchanged HighlightedText, then applies the alpha floor. Other roles retain inheritance and external ownership; an external Highlight change relinquishes the exception. Unpolish clears only owned resolve bits.
- Gwenview `QTipLabel`: stronger ToolTipBase backing before QLabel paints. This covers all Qt tooltips in Gwenview because Qt can reuse one tooltip label without reparenting it; the QObject parent cannot reliably identify the current owner.

Filelight uses Qt Quick, not these QWidget primitives. Its separate launcher prepares a private overlay of the installed KDE style, retaining the Menu/ToolTip alpha floor of 0.88 and transparent window clear. Background-only QML material on menus, tooltips, standard toolbars and the Kirigami header matches the film/accent/rim coefficients above. Foreground content, geometry and chart colors remain native. It does not change this module or installed packages.

## Safe coverage gaps

This is not universal application skinning. Custom widgets that bypass the supported public background primitives, opaque child panels hiding a toolbar film, non-Qt applications, and parent-painted custom content receive no additional material. Dock interiors intentionally receive no film. Menubar/custom content and editor internals remain stock, apart from the explicitly listed reading-surface exceptions. Reparenting existing decorated hosts into excluded content after polish is not a supported activation mechanism; their material paint is suppressed by the ancestor check, but the harmless input-transparent layer persists until unpolish. The native checks exercise public fake Drawy/Kate class identities, Qt widgets, and deterministic image comparisons; they do not replace visual checks against actual applications on a live compositor.

The compatibility guards originated in this repository's Drawy style; material coefficients follow the accepted Drawy liquid prototype. Source files retain the MIT SPDX identifier.

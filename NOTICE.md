# Licenses and provenance

Original deployment/session tooling, the small Kate adapter and the shared Qt glass style are provided under the repository MIT license unless a file says otherwise.

Third-party-derived theme assets retain their own provenance:

- The DMS preset derives from the stock Blue palette in [Dux Shell](https://github.com/duxlabs-dev/dux-shell), snapshot `3b63f55`. The Qt Matugen template derives from its KDE color-scheme template. These assets are marked **GPL-3.0-or-later**; a copy is in [LICENSES](LICENSES/GPL-3.0-or-later.txt).
- Breeze Light syntax colors derive from [KDE syntax-highlighting](https://invent.kde.org/frameworks/syntax-highlighting), tag `v6.31.0`, under **MIT**. Existing SPDX author/license metadata is retained in the theme.
- Tomorrow Night Bright is the existing MIT-labeled Base16 mapping, crediting the original Tomorrow theme by Chris Kempson. Its theme metadata and original color definitions are preserved; balanced copies change background alpha and names.

Filelight's private runtime popup overlay derives three components (Menu, ToolTip and ToolBar) from the installed [KDE qqc2-desktop-style](https://invent.kde.org/frameworks/qqc2-desktop-style). Their copyright notices and **LGPL-3.0-only OR GPL-2.0-or-later** SPDX identifiers are retained in the generated copies. The Filelight-only window-clear correction also copies Kirigami's AbstractApplicationWindow and AbstractApplicationHeader at runtime, retaining its **LGPL-2.0-or-later** license and copyright notice. The generated NiriGlassMaterial component is original MIT-licensed code matching this repository's shared Qt material. No KDE component source is vendored here; the other components remain links to the installed package.

Qt, KDE Frameworks, Darkly, Drawy and DMS are external dependencies, not bundled patched applications. Their licenses remain their respective upstream licenses. No downloaded upstream source archive, compiled dependency, application artwork, private config snapshot or personal document list is included.

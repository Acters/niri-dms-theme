# Licenses and provenance

Original deployment/session tooling, the small Kate adapter and the Drawy Qt style adapter are provided under the repository MIT license unless a file says otherwise.

Third-party-derived theme assets retain their own provenance:

- The DMS preset derives from the stock Blue palette in [Dux Shell](https://github.com/duxlabs-dev/dux-shell), snapshot `3b63f55`. The Qt Matugen template derives from its KDE color-scheme template. These assets are marked **GPL-3.0-or-later**; a copy is in [LICENSES](LICENSES/GPL-3.0-or-later.txt).
- Breeze Light syntax colors derive from [KDE syntax-highlighting](https://invent.kde.org/frameworks/syntax-highlighting), tag `v6.31.0`, under **MIT**. Existing SPDX author/license metadata is retained in the theme.
- Tomorrow Night Bright is the existing MIT-labeled Base16 mapping, crediting the original Tomorrow theme by Chris Kempson. Its theme metadata and original color definitions are preserved; balanced copies change background alpha and names.

Qt, KDE Frameworks, Darkly, Drawy and DMS are external dependencies, not bundled patched applications. Their licenses remain their respective upstream licenses. No downloaded upstream source archive, compiled dependency, application artwork, private config snapshot or personal document list is included.

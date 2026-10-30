# Captured stack and boundaries

Captured from the working setup on 2026-10-29. Only theme assets, reviewed style settings, helper source code and generic integration templates are in Git. Personal session contents and machine-specific startup files are not copied.

| Component | Tested version / role |
|---|---|
| Qt / KDE Frameworks | Qt 6.12.0, KF6 6.31.0 |
| Niri | 26.04.r224.g9d8f4f8; this build supports `background-effect` blur/Xray |
| Dux Shell | 2.0.0.r129.g3b63f55 |
| qtengine | r47.gc6b3f92 |
| Darkly | 0.5.42 |
| Kate | 26.08.2; public KTextEditor view-theme API |
| Drawy | 1.0.2; native per-mode canvas backgrounds |

## Appearance

- Light base `#f7f9ff`; raised surfaces use icy/pale blues rather than gray-blue.
- Dark base/surface/lowest container are black; raised dark surfaces retain shading.
- Qt background roles use alpha 26/255 (~10%). Darkly control opacity defaults are 15%, independently configurable. Layered fills mean effective opacity is widget-specific.
- Widget shadows are disabled: Darkly's filled blurred black shape otherwise shows through translucent fields as gray.
- Kate code backgrounds use alpha 102/255, painted twice in normal rows (~64% effective). The gutter uses 163/255 directly. Empty space past EOF may have only one fill. Current-line and semantic highlights are separate.
- The Drawy app profile uses 50% native canvas color; measured on the tested stack it combines with window fills to ~64% effective. Stroke colors are not made translucent.
- Drawy's outer Frame metric is overridden only for that widget class. Its orphan-button workaround runs only for version 1.0.2 and checks parent, icon, lack of menu/action and lack of layout membership.

## Important live differences

The current installation still has legacy global integration. The repo is a **migration candidate**, not a claim that the live machine is already isolated:

- User-wide Qt platform/plugin environment files and a DMS-named environment file exist. The filename does not scope `environment.d` to DMS.
- The Niri unit imports Qt variables into the shared manager. Its CLI cleanup passes `NAME=value` to `systemctl unset-environment`; that CLI requires bare names. This is different from the valid systemd `UnsetEnvironment=` directive.
- The existing personal Kate plugin predates the session gate in this repository.
- Global KDE widget/color-scheme preferences and DMS's other application templates can outlive a Niri session.
- Drawy changes were disposable previews only. Normal Drawy settings were not promoted or overwritten.

The repo intentionally does not include GPU/Vulkan bridge flags, renderer device selections, monitor layouts, keymaps, browser profiles, credentials, downloaded upstream source trees, app data, open-document URLs, or full Kate session snapshots. Host-specific settings can be managed separately; do not assume they belong in a portable theme.

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the process-local org.kde.desktop QML overlay used for Filelight.

KDE's QQuickStyle theme is only initialised when its plugin is the effective
Controls style, so a partial style that merely imports org.kde.desktop loses
the KDE theme RGB.  This overlay shadows the installed module under the same
name instead: stock components stay symlinks, the copied qmldir loses its qrc
``prefer`` directive, Menu/ToolTip gain an alpha floor on their native RGB, and
their backgrounds plus ToolBar and the Kirigami main header receive a generated
MIT NiriGlassMaterial layer. A Filelight-only Kirigami controls overlay makes
the window clear transparent, leaving its theme-colored QML background to paint
without white saturation.
Qt paths are explicit
arguments. The standalone launcher queries qmake6 for that path; neither path
changes HOME/config roots or edits an installed file.
"""
from pathlib import Path
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile

STYLE = "org.kde.desktop"
ALPHA_FLOOR = 0.88

_FLOOR = (
    "        readonly property color baseColor: Kirigami.Theme.backgroundColor\n"
    f"        readonly property color readableColor: Qt.rgba(baseColor.r, baseColor.g, baseColor.b, Math.max({ALPHA_FLOOR}, baseColor.a))\n"
    "\n"
)
MATERIAL = "NiriGlassMaterial"
MATERIAL_FILE = f"{MATERIAL}.qml"
QMLDIR_ENTRY = f"{MATERIAL} 1.0 {MATERIAL_FILE}"
_MENU_OLD = (
    "    background: Kirigami.ShadowedRectangle {\n"
    "        radius: Kirigami.Units.cornerRadius\n"
    "        implicitWidth: Kirigami.Units.gridUnit * 8\n"
    "        color: Kirigami.Theme.backgroundColor\n"
    "\n"
    "        border.color: Kirigami.ColorUtils.linearInterpolation(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, Kirigami.Theme.frameContrast)\n"
    "        border.width: 1\n"
    "\n"
    "        shadow.xOffset: 0\n"
    "        shadow.yOffset: 2\n"
    "        shadow.color: Qt.rgba(0, 0, 0, 0.3)\n"
    "        shadow.size: 8\n"
    "    }\n"
)
_MENU_NEW = (
    "    background: Kirigami.ShadowedRectangle {\n"
    + _FLOOR
    + "        radius: Kirigami.Units.cornerRadius\n"
    "        implicitWidth: Kirigami.Units.gridUnit * 8\n"
    "        color: readableColor\n"
    "\n"
    "        border.color: Kirigami.ColorUtils.linearInterpolation(readableColor, Kirigami.Theme.textColor, Kirigami.Theme.frameContrast)\n"
    "        border.width: 1\n"
    "\n"
    "        shadow.xOffset: 0\n"
    "        shadow.yOffset: 2\n"
    "        shadow.color: Qt.rgba(0, 0, 0, 0.3)\n"
    "        shadow.size: 8\n"
    "\n"
    "        NiriGlassMaterial {\n"
    "            radius: parent.radius\n"
    "            surfaceColor: parent.baseColor\n"
    "            accentColor: control.Kirigami.Theme.focusColor\n"
    "        }\n"
    "    }\n"
)
_TOOLTIP_OLD = (
    "    background: Kirigami.ShadowedRectangle {\n"
    "        radius: Kirigami.Units.cornerRadius\n"
    "        color: Kirigami.Theme.backgroundColor\n"
    "        Kirigami.Theme.colorSet: control.Kirigami.Theme.colorSet\n"
)
_TOOLTIP_NEW = (
    "    background: Kirigami.ShadowedRectangle {\n"
    + _FLOOR
    + "        radius: Kirigami.Units.cornerRadius\n"
    "        color: readableColor\n"
    "        Kirigami.Theme.colorSet: control.Kirigami.Theme.colorSet\n"
)
_TOOLTIP_BORDER_OLD = (
    "        border.color: Kirigami.ColorUtils.linearInterpolation(color, Kirigami.Theme.textColor, Kirigami.Theme.frameContrast)\n"
)
_TOOLTIP_BORDER_NEW = (
    "        border.color: Kirigami.ColorUtils.linearInterpolation(readableColor, Kirigami.Theme.textColor, Kirigami.Theme.frameContrast)\n"
    "\n"
    "        NiriGlassMaterial {\n"
    "            radius: parent.radius\n"
    "            surfaceColor: parent.baseColor\n"
    "            accentColor: control.Kirigami.Theme.focusColor\n"
    "        }\n"
)
_TOOLBAR_OLD = (
    "    background: Private.DefaultToolBarBackground {\n"
    "        control: controlRoot\n"
    "    }\n"
)
_TOOLBAR_NEW = (
    "    background: Private.DefaultToolBarBackground {\n"
    "        control: controlRoot\n"
    "\n"
    "        NiriGlassMaterial {\n"
    "            radius: 0\n"
    "            surfaceColor: parent.color\n"
    "            accentColor: controlRoot.Kirigami.Theme.focusColor\n"
    "            visible: controlRoot.contentWidth > 0 && controlRoot.contentHeight > 0\n"
    "        }\n"
    "    }\n"
)
_HEADER_OLD = (
    "    background: Rectangle {\n"
    "        color: Platform.Theme.backgroundColor\n"
    "        P.EdgeShadow {\n"
)
_HEADER_NEW = (
    "    background: Rectangle {\n"
    "        color: Platform.Theme.backgroundColor\n"
    "\n"
    "        NiriGlassMaterial {\n"
    "            radius: 0\n"
    "            surfaceColor: root.Platform.Theme.backgroundColor\n"
    "            accentColor: root.Platform.Theme.focusColor\n"
    "        }\n"
    "\n"
    "        P.EdgeShadow {\n"
)
_COPIED = frozenset(("Menu.qml", "ToolTip.qml", "ToolBar.qml", MATERIAL_FILE))
_CONTROLS_COPIED = frozenset(("qmldir", "AbstractApplicationWindow.qml",
                              "AbstractApplicationHeader.qml", MATERIAL_FILE))

# Original MIT component; it is generated here so the standalone launcher stays
# a single installed Python file and no extra QML asset is installed.
MATERIAL_QML = '''/*
    SPDX-FileCopyrightText: 2026 Niri DMS Theme contributors
    SPDX-License-Identifier: MIT

    Original NiriGlass QML material component. Its coefficients mirror
    plugins/glass-style/niriglassstyle.cpp; it is not derived from KDE QML.
*/
import QtQuick

Canvas {
    id: material

    objectName: "_niriGlassMaterial"
    enabled: false
    anchors.fill: parent

    renderTarget: Canvas.Image

    property real radius: 0
    property color surfaceColor: "transparent"
    property color accentColor: "transparent"

    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onRadiusChanged: requestPaint()
    onSurfaceColorChanged: requestPaint()
    onAccentColorChanged: requestPaint()
    onVisibleChanged: if (visible) requestPaint()

    function roundedPath(ctx, x, y, w, h, r) {
        ctx.beginPath()
        ctx.moveTo(x + r, y)
        ctx.lineTo(x + w - r, y)
        ctx.quadraticCurveTo(x + w, y, x + w, y + r)
        ctx.lineTo(x + w, y + h - r)
        ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h)
        ctx.lineTo(x + r, y + h)
        ctx.quadraticCurveTo(x, y + h, x, y + h - r)
        ctx.lineTo(x, y + r)
        ctx.quadraticCurveTo(x, y, x + r, y)
        ctx.closePath()
    }

    onPaint: {
        const ctx = getContext("2d")
        ctx.reset()
        ctx.clearRect(0, 0, width, height)
        if (width < 3 || height < 3)
            return
        const inset = 0.75
        const x = inset
        const y = inset
        const w = width - inset * 2
        const h = height - inset * 2
        if (w <= 0 || h <= 0)
            return
        const corner = Math.min(Math.max(radius, 0), Math.min(w, h) / 2)
        const lo = Math.min(surfaceColor.r, surfaceColor.g, surfaceColor.b)
        const hi = Math.max(surfaceColor.r, surfaceColor.g, surfaceColor.b)
        const light = (hi + lo) / 2 > 128 / 255

        ctx.save()
        roundedPath(ctx, x, y, w, h, corner)
        ctx.clip()
        const film = ctx.createLinearGradient(x, y, x, y + h)
        film.addColorStop(0, Qt.rgba(1, 1, 1, (light ? 26 : 14) / 255))
        film.addColorStop(0.38, Qt.rgba(1, 1, 1, (light ? 8 : 4) / 255))
        film.addColorStop(0.75, Qt.rgba(1, 1, 1, 0))
        film.addColorStop(1, Qt.rgba(1, 1, 1, 2 / 255))
        ctx.fillStyle = film
        ctx.fill()

        const sheen = ctx.createLinearGradient(x, y, x + w, y + h)
        sheen.addColorStop(0, Qt.rgba(accentColor.r, accentColor.g, accentColor.b, (light ? 8 : 5) / 255))
        sheen.addColorStop(0.6, Qt.rgba(accentColor.r, accentColor.g, accentColor.b, 0))
        ctx.fillStyle = sheen
        ctx.fill()

        const rim = ctx.createLinearGradient(x, y, x + w, y + h)
        rim.addColorStop(0, Qt.rgba(1, 1, 1, (light ? 130 : 100) / 255))
        rim.addColorStop(0.3, Qt.rgba(1, 1, 1, (light ? 60 : 48) / 255))
        rim.addColorStop(0.65, Qt.rgba(1, 1, 1, 8 / 255))
        rim.addColorStop(1, Qt.rgba(0, 0, 0, (light ? 24 : 16) / 255))
        roundedPath(ctx, x, y, w, h, corner)
        ctx.lineWidth = 1
        ctx.strokeStyle = rim
        ctx.stroke()
        ctx.restore()
    }
}
'''


class QuickStyleError(RuntimeError):
    """The installed org.kde.desktop layout cannot be overlaid safely."""


def _fail(path, reason):
    raise QuickStyleError(f"unsupported Filelight QML source: {path}: {reason}")


def _read(path):
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as error:
        _fail(path, f"cannot read as UTF-8: {error}")


def _stock_qmldir(path, text):
    """Validate the KDE module, add the material, and drop its qrc prefer line."""
    lines = text.splitlines(keepends=True)
    stripped = [line.strip() for line in lines]
    if "module org.kde.desktop" not in stripped:
        _fail(path, "expected 'module org.kde.desktop'")
    prefers = [line for line in stripped if line.startswith("prefer ")]
    if len(prefers) != 1 or not re.fullmatch(r"prefer\s+:/qt/qml/org/kde/desktop/", prefers[0]):
        _fail(path, "expected one 'prefer :/qt/qml/org/kde/desktop/' directive")
    if not any(re.fullmatch(r"(?:optional\s+)?plugin\s+org_kde_desktop", line) for line in stripped):
        _fail(path, "expected the org_kde_desktop plugin")
    for name in ("Menu", "ToolTip", "ToolBar"):
        if not any(parts and parts[0] == name and parts[-1] == f"{name}.qml"
                   for parts in (line.split() for line in stripped)):
            _fail(path, f"expected a {name} component entry")
    for line in stripped:
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] == "internal":
            parts = parts[1:]
        if any(part == MATERIAL or part.rsplit("/", 1)[-1] == MATERIAL_FILE
               for part in parts):
            _fail(path, f"{MATERIAL} component name collision")
    kept = "".join(line for line in lines if not line.lstrip().startswith("prefer "))
    if not kept.endswith("\n"):
        kept += "\n"
    return kept + QMLDIR_ENTRY + "\n"


def _patched_menu(path, text):
    if text.count(_MENU_OLD) != 1 or text.count("    id: control\n") != 1:
        _fail(path, "Menu background layout changed")
    return text.replace(_MENU_OLD, _MENU_NEW, 1)


def _patched_tooltip(path, text):
    if (text.count(_TOOLTIP_OLD) != 1 or text.count(_TOOLTIP_BORDER_OLD) != 1
            or text.count("    id: control\n") != 1):
        _fail(path, "ToolTip background layout changed")
    return text.replace(_TOOLTIP_OLD, _TOOLTIP_NEW, 1).replace(
        _TOOLTIP_BORDER_OLD, _TOOLTIP_BORDER_NEW, 1)


def _patched_toolbar(path, text):
    if text.count(_TOOLBAR_OLD) != 1 or text.count("    id: controlRoot\n") != 1:
        _fail(path, "ToolBar background layout changed")
    return text.replace(_TOOLBAR_OLD, _TOOLBAR_NEW, 1)


def _plan(source):
    """Validate the stock module and return the overlay contents in memory."""
    for name in ("qmldir", "Menu.qml", "ToolTip.qml", "ToolBar.qml"):
        path = source / name
        if not path.is_file():
            _fail(path, "missing required stock file")
    material = source / MATERIAL_FILE
    if material.exists() or material.is_symlink():
        _fail(material, f"{MATERIAL} component name collision")
    qmldir = _stock_qmldir(source / "qmldir", _read(source / "qmldir"))
    menu = _patched_menu(source / "Menu.qml", _read(source / "Menu.qml"))
    tooltip = _patched_tooltip(source / "ToolTip.qml", _read(source / "ToolTip.qml"))
    toolbar = _patched_toolbar(source / "ToolBar.qml", _read(source / "ToolBar.qml"))
    return qmldir, menu, tooltip, toolbar


def _patched_header(path, text):
    if text.count(_HEADER_OLD) != 1 or text.count("    id: root\n") != 1:
        _fail(path, "AbstractApplicationHeader background layout changed")
    return text.replace(_HEADER_OLD, _HEADER_NEW, 1)


def _controls_qmldir(path, text):
    """Validate the Kirigami controls module, add the material, drop qrc prefer."""
    lines = text.splitlines(keepends=True)
    stripped = [line.strip() for line in lines]
    expected = "prefer :/qt/qml/org/kde/kirigami/controls/"
    if ("module org.kde.kirigami.controls" not in stripped
            or sum(line == expected for line in stripped) != 1):
        _fail(path, "Kirigami controls module layout changed")
    for name, version in (("AbstractApplicationHeader", "2.0"),
                          ("AbstractApplicationWindow", "2.0")):
        entry = f"{name} {version} {name}.qml"
        if entry not in stripped:
            _fail(path, f"expected a {name} component entry")
    for line in stripped:
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] == "internal":
            parts = parts[1:]
        if any(part == MATERIAL or part.rsplit("/", 1)[-1] == MATERIAL_FILE
               for part in parts):
            _fail(path, f"{MATERIAL} component name collision")
    kept = "".join(line for line in lines if line.strip() != expected)
    if not kept.endswith("\n"):
        kept += "\n"
    return kept + QMLDIR_ENTRY + "\n"


def _controls_plan(source):
    """Keep Filelight's clear color transparent and add the main-header film.

    A translucent, non-premultiplied light clear color can saturate a compositor
    buffer to white. The theme-colored QML background already paints the panel.
    The Kirigami main header is a separate background from the QQC2 footer, so
    it receives the same generated material locally without importing the
    org.kde.desktop module (which would be circular). Only Filelight receives
    this controls overlay through its launcher.
    """
    for name in ("qmldir", "AbstractApplicationWindow.qml",
                 "AbstractApplicationHeader.qml"):
        path = source / name
        if not path.is_file():
            _fail(path, "missing required stock file")
    material = source / MATERIAL_FILE
    if material.exists() or material.is_symlink():
        _fail(material, f"{MATERIAL} component name collision")
    qmldir = _controls_qmldir(source / "qmldir", _read(source / "qmldir"))
    window = _read(source / "AbstractApplicationWindow.qml")
    old = "    color: Platform.Theme.backgroundColor\n"
    if window.count(old) != 1:
        _fail(source / "AbstractApplicationWindow.qml", "window clear-color binding changed")
    window = window.replace(old, '    color: "transparent"\n', 1)
    header = _patched_header(source / "AbstractApplicationHeader.qml",
                             _read(source / "AbstractApplicationHeader.qml"))
    return qmldir, window, header


def build_overlay(source: Path, destination: Path) -> Path:
    """Create and return a fresh overlay of ``source`` at ``destination``.

    ``source`` is the installed ``org/kde/desktop`` QML directory; its sibling
    Kirigami controls module supplies the Filelight window-clear correction.
    Both destination modules must be absent. Missing parents are created so a parent
    launcher can point QML_IMPORT_PATH at the caller-owned temporary root.
    The stock module is validated before any write, and an unsupported KDE
    layout fails with QuickStyleError instead of falling back to another
    Controls style.  Existing destinations are refused with FileExistsError.
    """
    source = Path(source)
    destination = Path(destination)
    if not source.is_dir():
        _fail(source, "not a directory")
    source = source.resolve()
    qmldir, menu, tooltip, toolbar = _plan(source)
    controls = source.parent / "kirigami/controls"
    controls_qmldir, window, header = _controls_plan(controls)
    controls_destination = destination.parent / "kirigami/controls"
    if controls_destination.exists() or controls_destination.is_symlink():
        raise FileExistsError(f"overlay destination already exists: {controls_destination}")
    if controls_destination.resolve().is_relative_to(controls.resolve()):
        raise QuickStyleError("window overlay destination must not be inside its source")

    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"overlay destination already exists: {destination}")
    if destination.resolve().is_relative_to(source):
        raise QuickStyleError(f"overlay destination must not be inside its source: {destination}")

    destination.mkdir(parents=True)
    for name, text in (("qmldir", qmldir), ("Menu.qml", menu),
                       ("ToolTip.qml", tooltip), ("ToolBar.qml", toolbar)):
        target = destination / name
        target.write_bytes(text.encode("utf-8"))
        shutil.copymode(source / name, target)
    (destination / MATERIAL_FILE).write_bytes(MATERIAL_QML.encode("utf-8"))
    for entry in sorted(source.iterdir(), key=lambda path: path.name):
        if entry.name not in _COPIED and entry.name != "qmldir":
            os.symlink(entry, destination / entry.name)
    controls_destination.mkdir(parents=True)
    copied = {"qmldir": controls_qmldir,
              "AbstractApplicationWindow.qml": window,
              "AbstractApplicationHeader.qml": header}
    for name, text in copied.items():
        target = controls_destination / name
        target.write_bytes(text.encode("utf-8"))
        shutil.copymode(controls / name, target)
    (controls_destination / MATERIAL_FILE).write_bytes(MATERIAL_QML.encode("utf-8"))
    for entry in sorted(controls.iterdir(), key=lambda path: path.name):
        if entry.name not in _CONTROLS_COPIED:
            os.symlink(entry, controls_destination / entry.name)
    return destination


def main(argv=None):
    """Run Filelight normally, adding the overlay only inside the active profile.

    This module is also installed as the standalone filelight-glass launcher.
    No config/data roots or app preferences are changed. Each launch rebuilds
    from the installed KDE style, so package updates cannot leave a stale copy.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    active = (os.environ.get("NIRI_DMS_THEME_PROFILE") == "niri-dms-glass"
              and "niri" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":"))
    try:
        if not active:
            return os.execvp("filelight", ["filelight", *args])
        query = subprocess.run(["qmake6", "-query", "QT_INSTALL_QML"],
                               check=True, capture_output=True, text=True, timeout=5)
        qml = Path(query.stdout.strip())
        if not qml.is_absolute():
            raise QuickStyleError("qmake6 did not return an absolute Qt QML directory")
        with tempfile.TemporaryDirectory(prefix="niri-filelight-") as temporary:
            imports = Path(temporary)
            build_overlay(qml / "org/kde/desktop", imports / "org/kde/desktop")
            env = os.environ.copy()
            env["QT_QUICK_CONTROLS_STYLE"] = STYLE
            env["QML_IMPORT_PATH"] = str(imports) + (os.pathsep + env["QML_IMPORT_PATH"]
                                                     if env.get("QML_IMPORT_PATH") else "")
            child = subprocess.Popen(["filelight", *args], env=env)
            previous = {}
            def forward(signum, _frame):
                if child.poll() is None:
                    child.send_signal(signum)
            try:
                for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                    previous[signum] = signal.signal(signum, forward)
                status = child.wait()
                return status if status >= 0 else 128 - status
            finally:
                for signum, handler in previous.items():
                    signal.signal(signum, handler)
    except (OSError, subprocess.SubprocessError, QuickStyleError) as error:
        print(f"filelight-glass: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

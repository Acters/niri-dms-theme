# SPDX-License-Identifier: MIT
"""Tests for the Filelight org.kde.desktop overlay builder."""
from pathlib import Path
import tempfile
import unittest
import contextlib
import io
import os
from unittest.mock import Mock, patch
from themekit import quickstyle
from themekit.quickstyle import (
    ALPHA_FLOOR, MATERIAL_FILE, MATERIAL_QML, QMLDIR_ENTRY, QuickStyleError,
    build_overlay,
)

QMLDIR = '''module org.kde.desktop
linktarget org_kde_desktop
optional plugin org_kde_desktop
classname org_kde_desktopPlugin
typeinfo org_kde_desktop.qmltypes
depends org.kde.qqc2desktopstyle.private
depends org.kde.desktop.private
prefer :/qt/qml/org/kde/desktop/
Button 1.0 Button.qml
Menu 1.0 Menu.qml
ToolBar 1.0 ToolBar.qml
ToolTip 1.0 ToolTip.qml
'''

# Layout excerpts mirroring the stock anchors; these are not vendored KDE files.
MENU = '''/*
    SPDX-FileCopyrightText: 2017 Marco Martin <mart@kde.org>
    SPDX-FileCopyrightText: 2017 The Qt Company Ltd.

    SPDX-License-Identifier: LGPL-3.0-only OR GPL-2.0-or-later
*/

import QtQuick
import QtQuick.Templates as T
import org.kde.kirigami as Kirigami

T.Menu {
    id: control

    delegate: MenuItem {}
    contentItem: ListView {}

    background: Kirigami.ShadowedRectangle {
        radius: Kirigami.Units.cornerRadius
        implicitWidth: Kirigami.Units.gridUnit * 8
        color: Kirigami.Theme.backgroundColor

        border.color: Kirigami.ColorUtils.linearInterpolation(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, Kirigami.Theme.frameContrast)
        border.width: 1

        shadow.xOffset: 0
        shadow.yOffset: 2
        shadow.color: Qt.rgba(0, 0, 0, 0.3)
        shadow.size: 8
    }
}
'''

TOOLTIP = '''/*
    SPDX-FileCopyrightText: 2017 Marco Martin <mart@kde.org>

    SPDX-License-Identifier: LGPL-3.0-only OR GPL-2.0-or-later
*/

import QtQuick
import QtQuick.Templates as T
import org.kde.kirigami as Kirigami

T.ToolTip {
    id: control

    contentItem: Item {
        Label {
            id: label
            text: control.text
            font: control.font
            color: Kirigami.Theme.textColor
            Kirigami.Theme.colorSet: control.Kirigami.Theme.colorSet
        }
    }

    background: Kirigami.ShadowedRectangle {
        radius: Kirigami.Units.cornerRadius
        color: Kirigami.Theme.backgroundColor
        Kirigami.Theme.colorSet: control.Kirigami.Theme.colorSet

        shadow.xOffset: 0
        shadow.yOffset: 4
        shadow.size: 16
        shadow.color: Qt.rgba(0, 0, 0, 0.2)

        border.width: 1
        border.color: Kirigami.ColorUtils.linearInterpolation(color, Kirigami.Theme.textColor, Kirigami.Theme.frameContrast)
    }
}
'''

TOOLBAR = '''/*
    SPDX-FileCopyrightText: 2017 Marco Martin <mart@kde.org>
    SPDX-FileCopyrightText: 2017 The Qt Company Ltd.

    SPDX-License-Identifier: LGPL-3.0-only OR GPL-2.0-or-later
*/

import QtQuick
import QtQuick.Templates as T
import org.kde.kirigami as Kirigami
import org.kde.desktop.private as Private

T.ToolBar {
    id: controlRoot

    padding: Kirigami.Units.smallSpacing

    background: Private.DefaultToolBarBackground {
        control: controlRoot
    }
}
'''


HEADER = '''/*
 *  SPDX-FileCopyrightText: 2016 Marco Martin <mart@kde.org>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */

import QtQuick
import "private" as P
import org.kde.kirigami.templates as T
import org.kde.kirigami.platform as Platform

T.AbstractApplicationHeader {
    id: root

    Platform.Theme.inherit: false
    Platform.Theme.colorSet: Platform.Theme.Header

    background: Rectangle {
        color: Platform.Theme.backgroundColor
        P.EdgeShadow {
            id: shadow
            visible: root.separatorVisible
            anchors {
                right: parent.right
                left: parent.left
                top: parent.bottom
            }
            edge: Qt.TopEdge
            opacity: (!root.page || !root.page.header || root.page.header.toString().indexOf("ToolBar") === -1)
            Behavior on opacity {
                OpacityAnimator {
                    duration: Platform.Units.longDuration
                    easing.type: Easing.InOutQuad
                }
            }
        }
        Behavior on opacity {
            OpacityAnimator {
                duration: Platform.Units.longDuration
                easing.type: Easing.InOutQuad
            }
        }
    }
}
'''

CONTROLS_QMLDIR = '''module org.kde.kirigami.controls
plugin KirigamiControlsplugin
prefer :/qt/qml/org/kde/kirigami/controls/
AbstractApplicationHeader 2.0 AbstractApplicationHeader.qml
AbstractApplicationWindow 2.0 AbstractApplicationWindow.qml
ApplicationWindow 2.0 ApplicationWindow.qml
'''
WINDOW = '''// SPDX-FileCopyrightText: 2015 Marco Martin <mart@kde.org>
// SPDX-License-Identifier: LGPL-2.0-or-later
import QtQuick.Controls as QQC2
import org.kde.kirigami.platform as Platform
QQC2.ApplicationWindow {
    color: Platform.Theme.backgroundColor
    background: Rectangle { color: Platform.Theme.backgroundColor }
}
'''


class QuickStyleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root/'qml/org/kde/desktop'
        self.destination = self.root/'overlay/org/kde/desktop'
        self._populate(self.source)

    def _populate(self, source):
        (source/'private').mkdir(parents=True)
        (source/'qmldir').write_text(QMLDIR)
        (source/'Menu.qml').write_text(MENU)
        (source/'ToolTip.qml').write_text(TOOLTIP)
        (source/'ToolBar.qml').write_text(TOOLBAR)
        (source/'Button.qml').write_text('import QtQuick.Templates as T\nT.Button {}\n')
        (source/'Frame.qml').write_text('// unchanged stock frame\nimport QtQuick\nRectangle {}\n')
        (source/'Chart.qml').write_text('// unchanged stock chart\nimport QtQuick\nItem {}\n')
        (source/'private'/'StyleItem.qml').write_text('// stock private helper\n')
        controls = source.parent / 'kirigami/controls'
        controls.mkdir(parents=True)
        (controls/'qmldir').write_text(CONTROLS_QMLDIR)
        (controls/'AbstractApplicationWindow.qml').write_text(WINDOW)
        (controls/'AbstractApplicationHeader.qml').write_text(HEADER)
        (controls/'ApplicationWindow.qml').write_text('// unchanged stock control\n')
        (controls/'AboutPage.qml').write_text('// unchanged stock page\n')

    def _case(self, name):
        root = self.root/name
        source = root/'qml/org/kde/desktop'
        self._populate(source)
        return source, root/'overlay/org/kde/desktop'

    def test_launcher_is_process_scoped_and_keeps_overlay_until_app_exits(self):
        original = {'NIRI_DMS_THEME_PROFILE': 'niri-dms-glass', 'XDG_CURRENT_DESKTOP': 'NIRI:Wayland',
                    'QML_IMPORT_PATH': '/other/qml', 'QT_QUICK_CONTROLS_STYLE': 'Other'}
        observed = {}
        child = Mock()
        def start(command, *, env):
            observed.update(command=command, env=env)
            imports = Path(env['QML_IMPORT_PATH'].split(os.pathsep)[0])
            observed['imports'] = imports
            self.assertTrue((imports / 'org/kde/desktop/Menu.qml').is_file())
            def wait():
                self.assertTrue((imports / 'org/kde/desktop/ToolTip.qml').is_file())
                self.assertTrue((imports / 'org/kde/desktop/ToolBar.qml').is_file())
                self.assertTrue((imports / 'org/kde/desktop/NiriGlassMaterial.qml').is_file())
                self.assertTrue((imports / 'org/kde/kirigami/controls/AbstractApplicationHeader.qml').is_file())
                self.assertTrue((imports / 'org/kde/kirigami/controls/NiriGlassMaterial.qml').is_file())
                return 7
            child.wait.side_effect = wait
            return child
        with patch.dict(os.environ, original, clear=True), patch.object(quickstyle.subprocess, 'run', return_value=Mock(stdout=str(self.root / 'qml'))) as query, patch.object(quickstyle.subprocess, 'Popen', side_effect=start):
            self.assertEqual(quickstyle.main(['file:///example folder', '--desktopfile', 'org.kde.filelight']), 7)
            self.assertEqual(dict(os.environ), original)
        query.assert_called_once_with(['qmake6', '-query', 'QT_INSTALL_QML'], check=True, capture_output=True, text=True, timeout=5)
        self.assertEqual(observed['command'], ['filelight', 'file:///example folder', '--desktopfile', 'org.kde.filelight'])
        self.assertEqual(observed['env']['QT_QUICK_CONTROLS_STYLE'], 'org.kde.desktop')
        self.assertTrue(observed['env']['QML_IMPORT_PATH'].endswith(os.pathsep + '/other/qml'))
        self.assertFalse(observed['imports'].exists())

    def test_launcher_forwards_termination_and_restores_signal_handlers(self):
        child = Mock()
        child.poll.return_value = None
        handlers = {}
        def install(signum, handler):
            previous = handlers.get(signum)
            handlers[signum] = handler
            return previous
        def wait():
            handlers[quickstyle.signal.SIGTERM](quickstyle.signal.SIGTERM, None)
            return -quickstyle.signal.SIGTERM
        child.wait.side_effect = wait
        with patch.dict(os.environ, {'NIRI_DMS_THEME_PROFILE': 'niri-dms-glass', 'XDG_CURRENT_DESKTOP': 'niri'}, clear=True), patch.object(quickstyle.subprocess, 'run', return_value=Mock(stdout=str(self.root / 'qml'))), patch.object(quickstyle.subprocess, 'Popen', return_value=child), patch.object(quickstyle.signal, 'signal', side_effect=install):
            self.assertEqual(quickstyle.main([]), 128 + quickstyle.signal.SIGTERM)
        child.send_signal.assert_called_once_with(quickstyle.signal.SIGTERM)
        self.assertIsNone(handlers[quickstyle.signal.SIGTERM])
        self.assertIsNone(handlers[quickstyle.signal.SIGINT])

    def test_launcher_forwards_hangup_and_cleans_the_overlay(self):
        child = Mock()
        child.poll.return_value = None
        handlers = {}
        captured = {}
        def install(signum, handler):
            previous = handlers.get(signum)
            handlers[signum] = handler
            return previous
        def start(command, *, env):
            captured['root'] = Path(env['QML_IMPORT_PATH'].split(os.pathsep)[0])
            return child
        def wait():
            self.assertTrue((captured['root'] / 'org/kde/desktop/Menu.qml').is_file())
            handlers[quickstyle.signal.SIGHUP](quickstyle.signal.SIGHUP, None)
            return -quickstyle.signal.SIGHUP
        child.wait.side_effect = wait
        with patch.dict(os.environ, {'NIRI_DMS_THEME_PROFILE': 'niri-dms-glass', 'XDG_CURRENT_DESKTOP': 'niri'}, clear=True), patch.object(quickstyle.subprocess, 'run', return_value=Mock(stdout=str(self.root / 'qml'))), patch.object(quickstyle.subprocess, 'Popen', side_effect=start), patch.object(quickstyle.signal, 'signal', side_effect=install):
            self.assertEqual(quickstyle.main([]), 128 + quickstyle.signal.SIGHUP)
        child.send_signal.assert_called_once_with(quickstyle.signal.SIGHUP)
        self.assertFalse(captured['root'].exists())
        self.assertTrue(all(handler is None for handler in handlers.values()))

    def test_launcher_without_marker_or_on_other_desktop_executes_stock_filelight(self):
        for values in ({}, {'NIRI_DMS_THEME_PROFILE': 'niri-dms-glass', 'XDG_CURRENT_DESKTOP': 'notniri'},
                       {'XDG_CURRENT_DESKTOP': 'niri'}):
            with self.subTest(values=values), patch.dict(os.environ, values, clear=True), patch.object(quickstyle.os, 'execvp', return_value=17) as execute, patch.object(quickstyle.subprocess, 'run') as query:
                self.assertEqual(quickstyle.main(['--help']), 17)
                execute.assert_called_once_with('filelight', ['filelight', '--help'])
                query.assert_not_called()

    def test_launcher_rejects_unsupported_kde_style_before_starting_filelight(self):
        (self.source / 'Menu.qml').write_text('unsupported changed layout')
        with patch.dict(os.environ, {'NIRI_DMS_THEME_PROFILE': 'niri-dms-glass', 'XDG_CURRENT_DESKTOP': 'niri'}, clear=True), patch.object(quickstyle.subprocess, 'run', return_value=Mock(stdout=str(self.root / 'qml'))), patch.object(quickstyle.subprocess, 'Popen') as launch, contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(quickstyle.main([]), 1)
            launch.assert_not_called()
            self.assertIn('Menu background layout changed', errors.getvalue())

    def test_builds_module_shadow_and_patches_only_targeted_backgrounds(self):
        before = {path.relative_to(self.source): path.read_bytes()
                  for path in self.source.rglob('*') if path.is_file()}
        controls_source = self.source.parent / 'kirigami/controls'
        controls_before = {path.relative_to(controls_source): path.read_bytes()
                           for path in controls_source.rglob('*') if path.is_file()}
        result = build_overlay(self.source, self.destination)

        self.assertEqual(result, self.destination)
        self.assertIsInstance(result, Path)
        self.assertFalse(self.destination.is_symlink())
        copied = sorted(path.name for path in self.destination.iterdir()
                        if not path.is_symlink())
        self.assertEqual(copied, ['Menu.qml', 'NiriGlassMaterial.qml', 'ToolBar.qml',
                                  'ToolTip.qml', 'qmldir'])
        patched = {'qmldir', 'Menu.qml', 'ToolTip.qml', 'ToolBar.qml'}
        for entry in self.source.iterdir():
            if entry.name in patched:
                continue
            link = self.destination/entry.name
            self.assertTrue(link.is_symlink(), entry.name)
            self.assertEqual(link.resolve(), entry.resolve())
        for name in ('Frame.qml', 'Chart.qml'):
            self.assertTrue((self.destination/name).is_symlink())
            self.assertEqual((self.destination/name).read_bytes(), (self.source/name).read_bytes())

        qmldir = (self.destination/'qmldir').read_text()
        self.assertNotIn('prefer ', qmldir)
        for line in ('module org.kde.desktop', 'optional plugin org_kde_desktop',
                     'Button 1.0 Button.qml', 'Menu 1.0 Menu.qml', 'ToolBar 1.0 ToolBar.qml',
                     'ToolTip 1.0 ToolTip.qml', QMLDIR_ENTRY):
            self.assertIn(line, qmldir)

        menu = (self.destination/'Menu.qml').read_text()
        self.assertIn('SPDX-FileCopyrightText: 2017 Marco Martin', menu)
        self.assertIn('SPDX-License-Identifier: LGPL-3.0-only OR GPL-2.0-or-later', menu)
        self.assertEqual(menu.count('Math.max(0.88, baseColor.a)'), 1)
        self.assertIn('readonly property color baseColor: Kirigami.Theme.backgroundColor', menu)
        self.assertIn('color: readableColor', menu)
        self.assertIn('linearInterpolation(readableColor, Kirigami.Theme.textColor', menu)
        self.assertNotIn('linearInterpolation(Kirigami.Theme.backgroundColor', menu)
        self.assertEqual(menu.count('NiriGlassMaterial {'), 1)
        for child in ('radius: parent.radius', 'surfaceColor: parent.baseColor',
                      'accentColor: control.Kirigami.Theme.focusColor'):
            self.assertIn(child, menu)
        for chrome in ('shadow.yOffset: 2', 'shadow.size: 8',
                       'shadow.color: Qt.rgba(0, 0, 0, 0.3)', 'border.width: 1',
                       'delegate: MenuItem {}'):
            self.assertIn(chrome, menu)

        tooltip = (self.destination/'ToolTip.qml').read_text()
        self.assertIn('SPDX-FileCopyrightText: 2017 Marco Martin', tooltip)
        self.assertIn('SPDX-License-Identifier: LGPL-3.0-only OR GPL-2.0-or-later', tooltip)
        self.assertEqual(tooltip.count('Math.max(0.88, baseColor.a)'), 1)
        self.assertIn('color: readableColor', tooltip)
        self.assertIn('color: Kirigami.Theme.textColor', tooltip)
        self.assertIn('Kirigami.Theme.colorSet: control.Kirigami.Theme.colorSet', tooltip)
        self.assertIn('linearInterpolation(readableColor, Kirigami.Theme.textColor', tooltip)
        self.assertNotIn('linearInterpolation(color, Kirigami.Theme.textColor', tooltip)
        self.assertEqual(tooltip.count('NiriGlassMaterial {'), 1)
        for child in ('radius: parent.radius', 'surfaceColor: parent.baseColor',
                      'accentColor: control.Kirigami.Theme.focusColor'):
            self.assertIn(child, tooltip)
        for chrome in ('shadow.yOffset: 4', 'shadow.size: 16',
                       'shadow.color: Qt.rgba(0, 0, 0, 0.2)', 'border.width: 1'):
            self.assertIn(chrome, tooltip)

        toolbar = (self.destination/'ToolBar.qml').read_text()
        self.assertIn('background: Private.DefaultToolBarBackground {', toolbar)
        self.assertIn('control: controlRoot', toolbar)
        self.assertIn('padding: Kirigami.Units.smallSpacing', toolbar)
        self.assertNotIn('readableColor', toolbar)
        self.assertEqual(toolbar.count('NiriGlassMaterial {'), 1)
        for child in ('radius: 0', 'surfaceColor: parent.color',
                      'accentColor: controlRoot.Kirigami.Theme.focusColor',
                      'visible: controlRoot.contentWidth > 0 && controlRoot.contentHeight > 0'):
            self.assertIn(child, toolbar)

        material = (self.destination/'NiriGlassMaterial.qml').read_text()
        self.assertEqual(material, MATERIAL_QML)
        self.assertIn('SPDX-License-Identifier: MIT', material)
        self.assertIn('objectName: "_niriGlassMaterial"', material)
        self.assertIn('enabled: false', material)
        self.assertIn('anchors.fill: parent', material)
        self.assertIn('renderTarget: Canvas.Image', material)
        self.assertIn('ctx.reset()', material)
        self.assertIn('ctx.clearRect(0, 0, width, height)', material)
        self.assertNotIn('MouseArea', material)
        self.assertNotIn('Timer', material)
        self.assertNotIn('requestAnimationFrame', material)
        self.assertNotIn('activeFocus', material)
        self.assertNotIn('focus:', material)
        self.assertNotIn('Rectangle {', material)
        for trigger in ('onWidthChanged: requestPaint()', 'onHeightChanged: requestPaint()',
                        'onRadiusChanged: requestPaint()',
                        'onSurfaceColorChanged: requestPaint()',
                        'onAccentColorChanged: requestPaint()',
                        'onVisibleChanged: if (visible) requestPaint()'):
            self.assertIn(trigger, material)
        for coefficient in ('const inset = 0.75', 'const corner = Math.min(',
                            '(light ? 26 : 14)', '(light ? 8 : 4)',
                            'film.addColorStop(0.38,', 'film.addColorStop(0.75,',
                            'Qt.rgba(1, 1, 1, 2 / 255)',
                            '(light ? 8 : 5)', 'sheen.addColorStop(0.6,',
                            '(light ? 130 : 100)', '(light ? 60 : 48)',
                            'rim.addColorStop(0.65,', 'Qt.rgba(1, 1, 1, 8 / 255)',
                            '(light ? 24 : 16)'):
            self.assertIn(coefficient, material)
        self.assertIn('function roundedPath', material)
        self.assertEqual(MATERIAL_FILE, 'NiriGlassMaterial.qml')
        self.assertEqual(QMLDIR_ENTRY, 'NiriGlassMaterial 1.0 NiriGlassMaterial.qml')
        self.assertEqual(ALPHA_FLOOR, 0.88)

        controls_source = self.source.parent / 'kirigami/controls'
        controls = self.destination.parent / 'kirigami/controls'
        self.assertEqual(sorted(path.name for path in controls.iterdir()
                                if not path.is_symlink()),
                         ['AbstractApplicationHeader.qml',
                          'AbstractApplicationWindow.qml',
                          'NiriGlassMaterial.qml', 'qmldir'])
        for entry in controls_source.iterdir():
            if entry.name in ('qmldir', 'AbstractApplicationWindow.qml',
                              'AbstractApplicationHeader.qml'):
                continue
            link = controls/entry.name
            self.assertTrue(link.is_symlink(), entry.name)
            self.assertEqual(link.resolve(), entry.resolve())
        self.assertTrue((controls/'AboutPage.qml').is_symlink())
        self.assertEqual((controls/'NiriGlassMaterial.qml').read_text(), MATERIAL_QML)

        controls_qmldir = (controls/'qmldir').read_text()
        self.assertNotIn('prefer ', controls_qmldir)
        for line in ('module org.kde.kirigami.controls',
                     'AbstractApplicationHeader 2.0 AbstractApplicationHeader.qml',
                     'AbstractApplicationWindow 2.0 AbstractApplicationWindow.qml',
                     QMLDIR_ENTRY):
            self.assertIn(line, controls_qmldir)

        header = (controls/'AbstractApplicationHeader.qml').read_text()
        self.assertIn('SPDX-License-Identifier: LGPL-2.0-or-later', header)
        self.assertIn('background: Rectangle {', header)
        self.assertIn('color: Platform.Theme.backgroundColor', header)
        self.assertEqual(header.count('P.EdgeShadow {'), 1)
        self.assertEqual(header.count('NiriGlassMaterial {'), 1)
        for child in ('radius: 0',
                      'surfaceColor: root.Platform.Theme.backgroundColor',
                      'accentColor: root.Platform.Theme.focusColor'):
            self.assertIn(child, header)
        for chrome in ('anchors {', 'top: parent.bottom', 'edge: Qt.TopEdge',
                       'Behavior on opacity', 'id: shadow'):
            self.assertIn(chrome, header)

        after = {path.relative_to(self.source): path.read_bytes()
                 for path in self.source.rglob('*') if path.is_file()}
        self.assertEqual(before, after)
        controls_after = {path.relative_to(controls_source): path.read_bytes()
                          for path in controls_source.rglob('*') if path.is_file()}
        self.assertEqual(controls_before, controls_after)

    def test_window_clear_is_transparent_without_changing_native_background(self):
        before = (self.source.parent / 'kirigami/controls/AbstractApplicationWindow.qml').read_bytes()
        build_overlay(self.source, self.destination)
        controls = self.destination.parent / 'kirigami/controls'
        window = (controls/'AbstractApplicationWindow.qml').read_text()
        self.assertIn('    color: "transparent"', window)
        self.assertIn('background: Rectangle { color: Platform.Theme.backgroundColor }', window)
        self.assertIn('SPDX-License-Identifier: LGPL-2.0-or-later', window)
        self.assertEqual((self.source.parent / 'kirigami/controls/AbstractApplicationWindow.qml').read_bytes(), before)
        self.assertNotIn('prefer ', (controls/'qmldir').read_text())
        self.assertTrue((controls/'ApplicationWindow.qml').is_symlink())
        self.assertIn('NiriGlassMaterial {',
                      (controls/'AbstractApplicationHeader.qml').read_text())
        self.assertEqual((controls/'NiriGlassMaterial.qml').read_text(), MATERIAL_QML)

    def test_window_layout_mismatch_and_existing_sibling_fail_before_writes(self):
        controls = self.source.parent / 'kirigami/controls'
        (controls/'AbstractApplicationWindow.qml').write_text(WINDOW.replace('color: Platform.Theme.backgroundColor', 'color: Qt.red'))
        with self.assertRaises(QuickStyleError):
            build_overlay(self.source, self.destination)
        self.assertFalse(self.destination.parent.exists())
        (controls/'AbstractApplicationWindow.qml').write_text(WINDOW)
        sibling = self.destination.parent / 'kirigami/controls'
        sibling.mkdir(parents=True)
        (sibling/'keep').write_text('caller data')
        with self.assertRaises(FileExistsError):
            build_overlay(self.source, self.destination)
        self.assertEqual((sibling/'keep').read_text(), 'caller data')
        self.assertFalse(self.destination.exists())

    def test_changed_toolbar_header_and_component_name_collision_fail_before_writes(self):
        mutations = (
            ('changed toolbar binding',
             lambda source: (source/'ToolBar.qml').write_text(
                 TOOLBAR.replace('        control: controlRoot\n', '')),
             'ToolBar background layout changed'),
            ('changed toolbar layout',
             lambda source: (source/'ToolBar.qml').write_text(
                 TOOLBAR.replace('        control: controlRoot\n',
                                 '        control: controlRoot\n        padding: 0\n')),
             'ToolBar background layout changed'),
            ('registered material name collision',
             lambda source: (source/'qmldir').write_text(
                 QMLDIR + 'NiriGlassMaterial 1.0 Other.qml\n'),
             'NiriGlassMaterial component name collision'),
            ('internal material name collision',
             lambda source: (source/'qmldir').write_text(
                 QMLDIR + 'internal NiriGlassMaterial Other.qml\n'),
             'NiriGlassMaterial component name collision'),
            ('stock material file collision',
             lambda source: (source/'NiriGlassMaterial.qml').write_text('// caller file\n'),
             'NiriGlassMaterial component name collision'),
            ('changed main header layout',
             lambda source: (source.parent/'kirigami/controls/AbstractApplicationHeader.qml').write_text(
                 HEADER.replace('        color: Platform.Theme.backgroundColor\n',
                                '        color: Qt.red\n')),
             'AbstractApplicationHeader background layout changed'),
            ('controls registered material name collision',
             lambda source: (source.parent/'kirigami/controls/qmldir').write_text(
                 CONTROLS_QMLDIR + 'NiriGlassMaterial 1.0 Other.qml\n'),
             'NiriGlassMaterial component name collision'),
            ('controls stock material file collision',
             lambda source: (source.parent/'kirigami/controls/NiriGlassMaterial.qml').write_text(
                 '// caller file\n'),
             'NiriGlassMaterial component name collision'),
        )
        for index, (label, mutate, reason) in enumerate(mutations):
            with self.subTest(label):
                source, destination = self._case(f'collision-{index}')
                mutate(source)
                with self.assertRaises(QuickStyleError) as raised:
                    build_overlay(source, destination)
                self.assertIn(reason, str(raised.exception))
                self.assertFalse(destination.exists())
                self.assertFalse(destination.parent.exists())

    def test_existing_destination_is_refused_untouched(self):
        self.destination.mkdir(parents=True)
        marker = self.destination/'caller-file'
        marker.write_text('keep me')
        with self.assertRaises(FileExistsError):
            build_overlay(self.source, self.destination)
        self.assertEqual(marker.read_text(), 'keep me')
        self.assertEqual(sorted(path.name for path in self.destination.iterdir()),
                         ['caller-file'])

    def test_unsupported_layouts_write_nothing(self):
        mutations = (
            ('missing qmldir', lambda source: (source/'qmldir').unlink()),
            ('missing Menu.qml', lambda source: (source/'Menu.qml').unlink()),
            ('missing ToolBar.qml', lambda source: (source/'ToolBar.qml').unlink()),
            ('qmldir without prefer', lambda source: (source/'qmldir').write_text(
                QMLDIR.replace('prefer :/qt/qml/org/kde/desktop/\n', ''))),
            ('qmldir without ToolBar', lambda source: (source/'qmldir').write_text(
                QMLDIR.replace('ToolBar 1.0 ToolBar.qml\n', ''))),
            ('generic Basic style', lambda source: (source/'qmldir').write_text(
                'module QtQuick.Controls.Basic\nButton 1.0 Button.qml\n')),
            ('missing main header', lambda source: (
                source.parent/'kirigami/controls/AbstractApplicationHeader.qml').unlink()),
            ('controls qmldir without header', lambda source: (
                source.parent/'kirigami/controls/qmldir').write_text(
                    CONTROLS_QMLDIR.replace(
                        'AbstractApplicationHeader 2.0 AbstractApplicationHeader.qml\n', ''))),
            ('changed Menu anchor', lambda source: (source/'Menu.qml').write_text(
                MENU.replace('implicitWidth: Kirigami.Units.gridUnit * 8',
                             'implicitWidth: Kirigami.Units.gridUnit * 12'))),
            ('changed ToolTip anchor', lambda source: (source/'ToolTip.qml').write_text(
                TOOLTIP.replace('linearInterpolation(color, Kirigami.Theme.textColor',
                                'linearInterpolation(color, palette.shadow'))),
        )
        for index, (label, mutate) in enumerate(mutations):
            with self.subTest(label):
                source, destination = self._case(f'unsupported-{index}')
                mutate(source)
                with self.assertRaises(QuickStyleError):
                    build_overlay(source, destination)
                self.assertFalse(destination.exists())
                self.assertFalse(destination.is_symlink())
                self.assertFalse(destination.parent.exists())

if __name__=='__main__': unittest.main()

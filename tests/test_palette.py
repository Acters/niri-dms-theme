# SPDX-License-Identifier: MIT
import configparser
import json
from pathlib import Path
import unittest
from themekit.palette import render_palette

ROOT = Path(__file__).resolve().parents[1]

class PaletteTests(unittest.TestCase):
    def setUp(self):
        self.theme = json.loads((ROOT/'assets/dms/blue-black.json').read_text())
        self.template = (ROOT/'assets/qt/translucent.colors.in').read_text()
    def test_modes_keep_every_surface_translucent_and_text_rgb(self):
        for mode in ('light','dark'):
            with self.subTest(mode=mode):
                text = render_palette(self.theme,self.template,mode)
                c = configparser.RawConfigParser(delimiters=('=',)); c.read_string(text)
                count = 0
                for section in c.sections():
                    for key,value in c[section].items():
                        if (section.startswith('Colors:') and key.startswith('background')) or (section=='WM' and key in ('activebackground','inactivebackground')):
                            self.assertEqual(value.split(',')[-1],'26'); count+=1
                        elif key.startswith('foreground'):
                            self.assertEqual(len(value.split(',')),3)
                self.assertEqual(count,18)
                self.assertEqual(c.get('Colors:Selection','ForegroundNormal'),c.get('Colors:View','ForegroundNormal'))
                self.assertNotIn('{{',text)
    def test_dark_is_black_light_rows_are_pale_blue(self):
        dark=configparser.RawConfigParser(); dark.read_string(render_palette(self.theme,self.template,'dark'))
        light=configparser.RawConfigParser(); light.read_string(render_palette(self.theme,self.template,'light'))
        self.assertEqual(dark.get('Colors:View','BackgroundNormal'),'0,0,0,26')
        self.assertEqual(light.get('Colors:View','BackgroundAlternate'),'237,246,255,26')
    def test_invalid_mode_color_or_token_is_not_silently_rendered(self):
        with self.assertRaises(ValueError): render_palette(self.theme,self.template,'auto')
        with self.assertRaises(ValueError): render_palette(self.theme,self.template+'{{colors.unknown.default.red}}','dark')
        self.theme['dark']['background']='red; execute'
        with self.assertRaises(ValueError): render_palette(self.theme,self.template,'dark')

if __name__=='__main__': unittest.main()

import unittest

import page_skin
import robotics_theme as rt

PAGE = "<html><head><title>x</title></head><body><h1>Hi</h1></body></html>"


class RoboThemeTests(unittest.TestCase):
    def test_inject_adds_css_and_js_once(self):
        out = rt.inject(PAGE)
        self.assertEqual(out.count('id="aplus-robo-css"'), 1)
        self.assertEqual(out.count('id="aplus-robo-js"'), 1)
        self.assertLess(out.index("aplus-robo-css"), out.index("</head>"))
        self.assertLess(out.index("aplus-robo-js"), out.index("</body>"))
        self.assertEqual(rt.inject(out), out)                                   # idempotent

    def test_light_pages_and_fragments_are_left_alone(self):
        light = "<html><head><style>:root{--bg:#fff}</style></head><body>x</body></html>"
        self.assertEqual(rt.inject(light), light)
        self.assertEqual(rt.inject('{"a": 1}'), '{"a": 1}')
        self.assertEqual(rt.inject(None), None)

    def test_page_skin_carries_the_theme_and_respects_toggles(self):
        out = page_skin.page_skin(PAGE)
        self.assertIn("aplus-robo-css", out)
        self.assertIn('localStorage.getItem("aplus_theme")', out)               # the on / off switch is remembered
        self.assertIn("prefers-reduced-motion", out)                            # animations stop for reduced motion
        self.assertIn("/api/mode", out)                                         # status chips come from the dashboard's own mode endpoint
        self.assertNotIn("aplus-robo-css", page_skin.page_skin("<html><head><style>:root{--bg:#ffffff}</style></head><body>x</body></html>"))


if __name__ == "__main__":
    unittest.main()

import unittest

import dashboard_skin as ds

PAGE = '<!doctype html><html><head><title>t</title></head><body><div id="aplus-main-nav"><a href="/">LIVE</a></div></body></html>'


class SkinTests(unittest.TestCase):
    def test_injects_css_before_head_end_and_script_before_body_end_once(self):
        out = ds.inject(PAGE)
        self.assertIn('id="aplus-skin-css"', out)
        self.assertLess(out.index('id="aplus-skin-css"'), out.index("</head>"))
        self.assertLess(out.index('id="aplus-skin-js"'), out.index("</body>"))
        self.assertEqual(ds.inject(out), out)                              # a second call changes nothing
        self.assertEqual(out.count('id="aplus-skin-css"'), 1)

    def test_classic_view_stays_available_and_every_rule_is_scoped_to_the_compact_class(self):
        out = ds.inject(PAGE)
        self.assertIn("aplus_view", out)                                    # the stored choice
        self.assertIn("Classic view", out)
        css = out[out.index('<style id="aplus-skin-css">'): out.index("</style>", out.index('<style id="aplus-skin-css">'))]
        rules = [r for r in css.split("}") if "{" in r and not r.strip().startswith("@media")]
        loose = [r.split("{")[0].strip() for r in rules if r.split("{")[0].strip() and "html.compact" not in r.split("{")[0]]
        self.assertEqual(loose, [])                                         # no rule can leak into the classic page

    def test_non_strings_pass_through(self):
        self.assertIsNone(ds.inject(None))


if __name__ == "__main__":
    unittest.main()

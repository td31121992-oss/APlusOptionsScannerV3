import unittest

import page_skin as ps

PAGE = '<!doctype html><html><head><title>t</title></head><body><div><a class="nav" href="/">Dashboard</a><a class="nav" href="/journal">Journal</a></div><p>x</p></body></html>'


def response(body: bytes, ctype=b"text/html; charset=utf-8") -> bytes:
    return b"HTTP/1.0 200 OK\r\nContent-Type: " + ctype + b"\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body


class PageSkinTests(unittest.TestCase):
    def test_bar_goes_right_after_body_css_in_head_script_at_the_end_once(self):
        out = ps.page_skin(PAGE)
        self.assertLess(out.index("<body>") + 6, out.index('id="aplus-topbar"'))
        self.assertLess(out.index('id="aplus-topbar"'), out.index("<p>x</p>"))
        self.assertLess(out.index('id="aplus-skin-css"'), out.index("</head>"))
        self.assertLess(out.index('id="aplus-skin-js"'), out.index("</body>"))
        self.assertEqual(ps.page_skin(out), out)
        self.assertIn('href="/chart-lab"', out)
        self.assertIn('href="http://192.168.1.5:8766"', ps.page_skin(PAGE, "192.168.1.5"))        # the technical-alerts link follows the host you opened the page on

    def test_every_rule_is_scoped_to_the_compact_class(self):
        css = ps.HEAD[ps.HEAD.index("<style"): ps.HEAD.index("</style>")]
        rules = [r.split("{")[0].strip() for r in css.split("}") if "{" in r]
        loose = [r for r in rules if r and "html.compact" not in r and "#aplus-viewfloat" not in r and "html:not(.compact)" not in r]
        self.assertEqual(loose, [])

    def test_light_pages_keep_their_own_colours_and_dark_ones_get_the_palette(self):
        light = ps.page_skin('<html><head><style>:root{--bg:#fff;--panel:#fff}</style></head><body>x</body></html>')
        self.assertNotIn("--bg:#0a0f1d", light)                                       # unreadable white-on-white otherwise
        self.assertIn("aplus-topbar", light)                                          # but it still gets the menu bar
        self.assertIn("--bg:#0a0f1d", ps.page_skin(PAGE))
        self.assertIn("--bg:#0a0f1d", ps.page_skin('<html><head><style>:root{--bg:#fff5aa}</style></head><body>x</body></html>'))     # #fff5aa is not "#fff"

    def test_response_filter_rewrites_content_length_and_leaves_other_types_alone(self):
        raw = response(PAGE.encode())
        out = ps.filter_response(raw)
        head, body = out.split(b"\r\n\r\n", 1)
        self.assertIn(b"aplus-topbar", body)
        self.assertIn(b"Content-Length: " + str(len(body)).encode(), head)
        js = response(b'{"ok": true}', b"application/json")
        self.assertEqual(ps.filter_response(js), js)
        frag = response(b"<div>no body tag</div>")
        self.assertEqual(ps.filter_response(frag), frag)
        self.assertEqual(ps.filter_response(b"garbage"), b"garbage")


if __name__ == "__main__":
    unittest.main()

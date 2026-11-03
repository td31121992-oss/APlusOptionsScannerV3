import gzip
import tempfile
import unittest
from pathlib import Path

import tick_gz as tg

HEADER = "ts,sym,ltp\n"


def member(rows):
    return gzip.compress((HEADER + "".join(f"{t},X,{p}\n" for t, p in rows)).encode())


def member_no_header(rows):
    return gzip.compress("".join(f"{t},X,{p}\n" for t, p in rows).encode())


class SalvageTests(unittest.TestCase):
    def write(self, tmp, *chunks):
        p = Path(tmp, "X.csv.gz")
        p.write_bytes(b"".join(chunks))
        return p

    def test_intact_file_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.write(tmp, member([("09:05:00", 1), ("09:05:01", 2)]))
            before = p.read_bytes()
            self.assertFalse(tg.is_damaged(p))
            self.assertEqual(tg.repair(p), (0, 0))
            self.assertEqual(p.read_bytes(), before)

    def test_a_cut_off_member_hides_later_data_until_repaired(self):
        good1 = member([(f"09:05:{i:02d}", i) for i in range(50)])
        cut = member([(f"09:28:{i:02d}", i) for i in range(50)])[:-12]                     # killed before the member was closed
        good3 = member_no_header([(f"09:29:{i:02d}", i) for i in range(20)])
        with tempfile.TemporaryDirectory() as tmp:
            p = self.write(tmp, good1, cut, member([(f"09:29:{i:02d}", i) for i in range(20)]))
            self.assertTrue(tg.is_damaged(p))
            with self.assertRaises(Exception):
                gzip.open(p, "rt").read()                                                   # the standard reader cannot get past the break
            text, members, damaged = tg.read_text(p)
            lines = text.splitlines()
            self.assertEqual(lines[0], HEADER.strip())
            self.assertEqual(sum(1 for l in lines if l.startswith("ts,sym")), 1)           # restart headers are not repeated
            self.assertEqual([l for l in lines if l.startswith("09:29")][-1], "09:29:19,X,19")      # everything after the break is recovered
            self.assertGreaterEqual(damaged, 1)
            rows, bad = tg.repair(p)
            self.assertGreater(rows, 60)
            self.assertFalse(tg.is_damaged(p))
            self.assertIn("09:29:19,X,19", gzip.open(p, "rt").read())
            self.assertFalse(Path(tmp, "X.csv.gz.repair").exists())

    def test_empty_and_garbage_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.write(tmp, b"not a gzip file at all")
            self.assertEqual(tg.read_text(p), ("", 0, 0))


if __name__ == "__main__":
    unittest.main()

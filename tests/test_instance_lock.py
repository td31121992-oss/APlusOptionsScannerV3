import tempfile
import unittest
from pathlib import Path

from core import instance_lock


class InstanceLockTests(unittest.TestCase):
    def test_second_holder_is_refused_until_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scanner.lock"
            self.assertTrue(instance_lock.acquire(path))
            second = open(path, "a+b")                      # a different handle stands in for another process
            second.seek(0)
            try:
                import os
                if os.name == "nt":
                    import msvcrt
                    with self.assertRaises(OSError):
                        msvcrt.locking(second.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    with self.assertRaises(OSError):
                        fcntl.flock(second.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                second.close()
            instance_lock.release(path)
            self.assertTrue(instance_lock.acquire(path))
            instance_lock.release(path)

    def test_same_process_reacquire_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scanner.lock"
            self.assertTrue(instance_lock.acquire(path))
            self.assertTrue(instance_lock.acquire(path))
            instance_lock.release(path)


if __name__ == "__main__":
    unittest.main()

"""Set (or change) the dashboard password. You type it here; it is never shown, logged or stored (only a salted scrypt hash is).

    python set_dashboard_password.py            asks twice (hidden), then the dashboard asks for it from the next page load: no restart needed
    python set_dashboard_password.py --remove   turns the password gate off again

Changing the password signs every browser out. See dashboard_login.py.
"""

from __future__ import annotations

import getpass
import sys

import dashboard_login as dl


def main() -> int:
    if "--remove" in sys.argv:
        try:
            dl.CONFIG.unlink()
            print("Password removed: the dashboard opens without a login again.")
        except FileNotFoundError:
            print("No password was set.")
        return 0
    first = getpass.getpass(f"New dashboard password (at least {dl.MIN_LENGTH} characters): ")
    if getpass.getpass("Type it again: ") != first:
        print("The two entries differ. Nothing changed.")
        return 1
    try:
        dl.set_password(first)
    except ValueError as exc:
        print(exc)
        return 1
    print("Password set. Open the dashboard: it now starts with the welcome screen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Client-address access control for the APlus dashboard.

APLUS_DASHBOARD_ACCESS:
  lan   (default) - this PC plus private/local-network addresses (10.x, 172.16-31.x, 192.168.x,
                    link-local, Tailscale-style 100.64/10). Phone on the same Wi-Fi keeps working.
  local           - this PC only (127.0.0.1 / ::1)
  any             - no restriction (the previous behaviour)
"""

from __future__ import annotations

import ipaddress
import os

_LAN_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",   # private IPv4
    "169.254.0.0/16", "100.64.0.0/10",                 # link-local, Tailscale-style CGNAT
    "fc00::/7", "fe80::/10",                            # IPv6 unique-local, link-local
))


def access_mode() -> str:
    value = os.getenv("APLUS_DASHBOARD_ACCESS", "lan").strip().lower()
    return value if value in {"lan", "local", "any"} else "lan"


def is_allowed(client_ip: str, mode: str | None = None) -> bool:
    mode = mode or access_mode()
    if mode == "any":
        return True
    try:
        ip = ipaddress.ip_address(str(client_ip).split("%")[0])
    except ValueError:
        return False                       # unparseable address -> deny
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return True
    if mode == "local":
        return False
    return any(ip in net for net in _LAN_NETWORKS if net.version == ip.version)

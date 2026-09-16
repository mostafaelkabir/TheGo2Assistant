# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Deciding whether a host is one only this machine can reach.

Two controls lean on this answer: the bearer token in front of ``go2 serve
--http`` is optional only on loopback, and the Basira mirror is exempt from
the egress guard only while Basira is local. Both would be bypassed by a
name that *says* local and resolves elsewhere, so the answer is taken from
the addresses, never the string.
"""

from __future__ import annotations

import ipaddress
import socket


def is_loopback(host: str) -> bool:
    """Whether every address ``host`` names is one only this machine can reach.

    A literal address is judged directly. A name is resolved, and every
    address it resolves to must be loopback: ``localhost`` is usually
    ``127.0.0.1``, but an ``/etc/hosts`` entry can point it at the LAN
    address, and trusting the string would then exempt an externally
    reachable target. A name that does not resolve is not loopback either --
    refusing is the safe side.
    """
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass  # a hostname, not an address
    try:
        resolved = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    return bool(resolved) and all(
        ipaddress.ip_address(str(info[4][0])).is_loopback for info in resolved
    )

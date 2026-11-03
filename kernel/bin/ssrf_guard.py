#!/usr/bin/env python3
"""SSRF guard for WebFetch (PreToolUse hook; exit 2 denies). CLI: --check <url>.

Only http(s) to hosts whose every address is global unicast. Refuses:
private, loopback, link-local, CGNAT, multicast, reserved, unspecified;
IPv4 hidden inside IPv6 (mapped, 6to4, Teredo, NAT64); cloud metadata names;
and hosts that answer differently on a second lookup (DNS rebinding).
Limits: WebFetch resolves again on its own and may follow redirects; this
narrows the window, it does not close it. An extra safety net, not a guarantee.
"""
from __future__ import annotations

import ipaddress
import json
import socket
import sys
import time
from urllib.parse import urlparse

METADATA_HOSTS = {"metadata", "metadata.google.internal", "instance-data", "instance-data.ec2.internal"}
LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain", ".home.arpa")
NAT64 = ipaddress.ip_network("64:ff9b::/96")
REBIND_DELAY_SEC = 0.2


def _embedded_v4(ip: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    out = [a for a in (ip.ipv4_mapped, ip.sixtofour) if a]
    if ip.teredo:
        out.extend(ip.teredo)
    if ip in NAT64:
        out.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return out


def _blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.version == 6 and any(_blocked(v4) for v4 in _embedded_v4(ip)):
        return True
    ip = getattr(ip, "ipv4_mapped", None) or ip  # ::ffff:127.0.0.1 is 127.0.0.1
    return not ip.is_global or ip.is_multicast


def _resolve(host: str) -> set:
    return {ipaddress.ip_address(i[4][0].split("%")[0])
            for i in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}


def check_url(url: str, delay: float = REBIND_DELAY_SEC) -> tuple[bool, str]:
    parsed = urlparse((url or "").strip())
    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"scheme not allowed: {parsed.scheme or '(none)'}"
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host:
        return False, "missing host"
    if host in METADATA_HOSTS or host == "localhost" or host.endswith(LOCAL_SUFFIXES):
        return False, f"local or metadata host name: {host}"
    try:
        first = _resolve(host)
        time.sleep(delay)
        second = _resolve(host)
    except (OSError, ValueError) as e:
        return False, f"cannot resolve {host}: {e}"
    for ip in first | second:
        if _blocked(ip):
            return False, f"non-public address {ip} for host {host}"
    return True, "ok"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--check"] and len(argv) == 2:
        ok, msg = check_url(argv[1])
        print("ALLOW" if ok else "DENY", msg)
        return 0 if ok else 2
    try:
        url = (json.load(sys.stdin).get("tool_input") or {}).get("url") or ""
    except (ValueError, AttributeError):
        url = ""
    ok, msg = check_url(url) if url else (False, "missing url")
    if ok:
        return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": f"SSRF guard: {msg}"}}))
    print(f"SSRF blocked: {msg}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

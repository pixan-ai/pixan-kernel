#!/usr/bin/env python3
"""SSRF guard for WebFetch (PreToolUse hook; exit 2 denies). CLI: --check <url>.

Only http(s) to hosts whose every address is global unicast.
"""
from __future__ import annotations

import ipaddress
import json
import socket
import sys
from urllib.parse import urlparse


def _blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    ip = getattr(ip, "ipv4_mapped", None) or ip  # ::ffff:127.0.0.1 is 127.0.0.1
    return not ip.is_global or ip.is_multicast


def check_url(url: str) -> tuple[bool, str]:
    parsed = urlparse((url or "").strip())
    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"scheme not allowed: {parsed.scheme or '(none)'}"
    host = parsed.hostname
    if not host:
        return False, "missing host"
    try:
        ips = {ipaddress.ip_address(i[4][0].split("%")[0])
               for i in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    except (OSError, ValueError) as e:
        return False, f"cannot resolve {host}: {e}"
    for ip in ips:
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

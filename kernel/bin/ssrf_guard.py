#!/usr/bin/env python3
"""SSRF / egress guard for WebFetch.

Blocks private, loopback, link-local (incl. 169.254.169.254), reserved, and
non-http(s) schemes. PreToolUse hook: exit 2 blocks. CLI: --check <url>.
"""
from __future__ import annotations

import ipaddress
import json
import socket
import sys
from urllib.parse import urlparse

BLOCKED_SCHEMES = frozenset(
    {"file", "ftp", "gopher", "dict", "sftp", "ssh", "jar", "data", "blob"}
)


def _host_ips(host: str) -> list[ipaddress._BaseAddress]:
    out: list[ipaddress._BaseAddress] = []
    try:
        out.append(ipaddress.ip_address(host))
        return out
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError(f"DNS resolve failed for {host!r}: {e}") from e
    for info in infos:
        addr = info[4][0]
        try:
            out.append(ipaddress.ip_address(addr))
        except ValueError:
            continue
    if not out:
        raise ValueError(f"no A/AAAA for {host!r}")
    return out


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> str | None:
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link-local"
    if ip.is_private:
        return "private"
    if ip.is_reserved:
        return "reserved"
    if ip.is_multicast:
        return "multicast"
    if ip.is_unspecified:
        return "unspecified"
    # Cloud metadata classic
    if str(ip) in ("169.254.169.254", "100.100.100.200"):
        return "cloud-metadata"
    return None


def check_url(url: str) -> tuple[bool, str]:
    raw = (url or "").strip()
    if not raw:
        return False, "empty url"
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme in BLOCKED_SCHEMES or scheme not in ("http", "https"):
        return False, f"scheme not allowed: {scheme or '(none)'}"
    host = parsed.hostname
    if not host:
        return False, "missing host"
    # Literal metadata hostnames
    hl = host.lower().rstrip(".")
    if hl in ("metadata.google.internal", "metadata", "instance-data"):
        return False, f"blocked host: {hl}"
    try:
        ips = _host_ips(host)
    except ValueError as e:
        return False, str(e)
    for ip in ips:
        why = _is_blocked_ip(ip)
        if why:
            return False, f"{why} address {ip} for host {host}"
    return True, "ok"


def _extract_url(payload: dict) -> str:
    ti = payload.get("tool_input") or payload.get("toolInput") or {}
    if isinstance(ti, dict):
        for k in ("url", "URI", "uri", "href"):
            v = ti.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    for k in ("url", "URI", "uri"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _deny(reason: str, event: str = "PreToolUse") -> int:
    out = {
        "hookSpecificOutput": {
            "hookEventName": event,
            "permissionDecision": "deny",
            "permissionDecisionReason": f"SSRF guard: {reason}",
        }
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    print(f"SSRF blocked: {reason}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--check":
        if len(argv) < 2:
            print("usage: ssrf_guard.py --check <url>", file=sys.stderr)
            return 2
        ok, msg = check_url(argv[1])
        print("ALLOW" if ok else "DENY", msg)
        return 0 if ok else 2

    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {}
    tool = str(data.get("tool_name") or data.get("toolName") or "")
    # Only gate WebFetch-like tools; ignore others quietly
    if tool and tool not in ("WebFetch", "WebSearch") and "WebFetch" not in tool:
        return 0
    url = _extract_url(data)
    if not url:
        # No URL → no opinion (don't fail open on empty for WebFetch)
        if tool in ("WebFetch",) or tool.endswith("WebFetch"):
            return _deny("missing url on WebFetch")
        return 0
    ok, msg = check_url(url)
    if not ok:
        return _deny(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

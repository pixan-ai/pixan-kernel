#!/usr/bin/env python3
"""Unit tests: SSRF guard (no network: DNS is faked)."""
import os
import socket
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "kernel", "bin"))
import ssrf_guard  # noqa: E402


def fake_dns(*answers):
    """getaddrinfo that returns answers[0] on the 1st call, answers[1] on the 2nd..."""
    calls = iter(answers)

    def gai(host, *a, **k):
        ips = next(calls)
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, 1, 6, "", (ip, 0)) for ip in ips]
    return gai


def check(url, *answers):
    with mock.patch("socket.getaddrinfo", fake_dns(*answers)):
        return ssrf_guard.check_url(url, delay=0)


class TestSsrf(unittest.TestCase):
    def test_public_ok(self):
        self.assertTrue(check("https://example.com/x", ["93.184.215.14"], ["93.184.215.14"])[0])

    def test_blocked_addresses(self):
        for ip in ["127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254",
                   "100.64.0.1", "0.0.0.0", "224.0.0.1", "::1", "fe80::1", "fc00::1",
                   "::ffff:127.0.0.1", "2002:7f00:1::", "64:ff9b::a9fe:a9fe", "fd00:ec2::254"]:
            self.assertFalse(check("http://h.example/", [ip], [ip])[0], ip)

    def test_literal_ips(self):
        for url in ["http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/latest/meta-data"]:
            self.assertFalse(check(url, [url.split("/")[2].strip("[]").split("]")[0]] * 1,
                                   [url.split("/")[2].strip("[]")])[0], url)

    def test_names(self):
        for url in ["http://localhost/", "http://metadata.google.internal/", "http://foo.local/",
                    "http://svc.internal/", "http://x.localhost/", "http://metadata/"]:
            self.assertFalse(ssrf_guard.check_url(url, delay=0)[0], url)

    def test_any_private_answer_blocks(self):
        self.assertFalse(check("http://h.example/", ["93.184.215.14", "10.0.0.1"], ["93.184.215.14"])[0])

    def test_dns_rebinding(self):
        ok, msg = check("http://h.example/", ["93.184.215.14"], ["127.0.0.1"])
        self.assertFalse(ok)
        self.assertIn("127.0.0.1", msg)

    def test_scheme(self):
        for url in ["file:///etc/passwd", "gopher://x/", "ftp://x/", ""]:
            self.assertFalse(ssrf_guard.check_url(url, delay=0)[0], url)

    def test_unresolvable(self):
        def gai(*a, **k):
            raise socket.gaierror("nope")
        with mock.patch("socket.getaddrinfo", gai):
            self.assertFalse(ssrf_guard.check_url("http://nope.example/", delay=0)[0])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Unit tests: secret filter."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "kernel", "bin"))
from secret_filter import MASK, redact  # noqa: E402

SAMPLES = [
    "sk-ant-api03-" + "A" * 40,
    "sk-proj-" + "b" * 40,
    "1234567890:" + "A" * 35,
    "ghp_" + "c" * 36,
    "github_pat_" + "d" * 50,
    "AKIA" + "E" * 16,
    "AGE-SECRET-KEY-1" + "Q" * 58,
    "xoxb-" + "1" * 20,
    "sk_live_" + "f" * 24,
    "Authorization: Bearer " + "g" * 30,
    "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----",
]


class TestSecretFilter(unittest.TestCase):
    def test_patterns(self):
        for s in SAMPLES:
            out, n = redact("before %s after" % s)
            self.assertGreaterEqual(n, 1, s)
            self.assertIn(MASK, out)
            self.assertTrue(out.startswith("before ") and out.endswith(" after"), out)

    def test_env_values(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "plain-looking-value-123"}):
            out, n = redact("token is plain-looking-value-123.")
        self.assertEqual((out, n), ("token is %s." % MASK, 1))

    def test_short_env_values_ignored(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "abc"}):
            self.assertEqual(redact("abc abc"), ("abc abc", 0))

    def test_clean_text_untouched(self):
        text = "Meeting at 10:30, ask about the sk-8 budget. Task 42 done."
        self.assertEqual(redact(text), (text, 0))


if __name__ == "__main__":
    unittest.main()

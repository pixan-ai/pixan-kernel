#!/usr/bin/env python3
"""Redact secrets from text before it leaves the agent (backups, owner alerts).

  secret_filter.py redact < text      # prints the text with secrets replaced
  secret_filter.py scan FILE...       # exit 1 and list files that contain a secret

Two sources: well-known token shapes, and the exact values of the secret
environment variables this container runs with. Best effort, not a guarantee.
"""
from __future__ import annotations

import os
import re
import sys

MASK = "[REDACTED]"
PATTERNS = [re.compile(p) for p in (
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
    r"sk-ant-[A-Za-z0-9_-]{16,}",
    r"sk-(?:proj-)?[A-Za-z0-9_-]{32,}",
    r"\b\d{6,12}:[A-Za-z0-9_-]{35}\b",              # Telegram bot token
    r"\bgh[pousr]_[A-Za-z0-9]{36,}\b",
    r"\bgithub_pat_[A-Za-z0-9_]{40,}\b",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\bAGE-SECRET-KEY-1[0-9A-Z]{58}\b",
    r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b",
    r"\b[rs]k_live_[0-9A-Za-z]{16,}\b",
    r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}",
)]
SECRET_ENV = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN",
              "TELEGRAM_BOT_TOKEN", "BACKUP_R2_ACCESS_KEY_ID", "BACKUP_R2_SECRET_ACCESS_KEY")
MIN_ENV_LEN = 8  # shorter values would redact ordinary words


def _env_values() -> list[str]:
    vals = (os.environ.get(n, "") for n in SECRET_ENV)
    return sorted({v for v in vals if len(v) >= MIN_ENV_LEN}, key=len, reverse=True)


def redact(text: str) -> tuple[str, int]:
    """Return (clean text, number of secrets replaced)."""
    count = 0
    for v in _env_values():
        count += text.count(v)
        text = text.replace(v, MASK)
    for p in PATTERNS:
        text, n = p.subn(MASK, text)
        count += n
    return text, count


def main(argv: list[str]) -> int:
    if argv[:1] == ["redact"]:
        sys.stdout.write(redact(sys.stdin.read())[0])
        return 0
    if argv[:1] == ["scan"] and len(argv) > 1:
        found = 0
        for path in argv[1:]:
            with open(path, encoding="utf-8", errors="replace") as f:
                if redact(f.read())[1]:
                    print(path)
                    found = 1
        return found
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

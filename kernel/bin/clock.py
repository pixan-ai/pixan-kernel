#!/usr/bin/env python3
"""Claude Code hook: injects the real local time (TZ, default America/Mexico_City).

SessionStart + UserPromptSubmit → additionalContext.
Do NOT use Telegram/channel UTC timestamps; this is authoritative.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


TZ_NAME = os.environ.get("TZ") or "America/Mexico_City"


def _now_local() -> str:
    try:
        now = datetime.now(ZoneInfo(TZ_NAME))
        return now.strftime("%Y-%m-%d %H:%M:%S %Z") + f" ({TZ_NAME})"
    except Exception:
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%d %H:%M:%S UTC") + f" (fallback: TZ {TZ_NAME!r} not found)"


def main() -> int:
    raw = sys.stdin.read()
    event = "UserPromptSubmit"
    try:
        data = json.loads(raw) if raw.strip() else {}
        event = str(data.get("hook_event_name") or event)
    except Exception:
        data = {}
    if event not in ("SessionStart", "UserPromptSubmit"):
        event = "UserPromptSubmit"
    stamp = _now_local()
    ctx = (
        f"Real system time: {stamp}. "
        "This is the authoritative time. Do not use UTC timestamps from the "
        "Telegram channel and do not make up the time."
    )
    out = {
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": ctx,
        }
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

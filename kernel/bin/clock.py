#!/usr/bin/env python3
"""Claude Code hook: inyecta la hora real America/Mexico_City.

SessionStart + UserPromptSubmit → additionalContext.
Do NOT use Telegram/channel UTC timestamps; this is authoritative.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def _now_cdmx() -> str:
    try:
        now = datetime.now(ZoneInfo(os.environ.get("TZ") or "America/Mexico_City"))
        return now.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%d %H:%M:%S UTC") + " (fallback; prefer America/Mexico_City)"


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
    stamp = _now_cdmx()
    ctx = (
        f"Hora real del sistema: {stamp} (America/Mexico_City). "
        "Esta es la hora autoritativa. No uses timestamps UTC del canal "
        "Telegram ni inventes la hora."
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

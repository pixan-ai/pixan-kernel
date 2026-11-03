#!/usr/bin/env python3
"""SessionStart/UserPromptSubmit hook: the real local time (TZ), or UTC if TZ is invalid."""
import json
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

name = os.environ.get("TZ") or "America/Mexico_City"
try:
    zone = ZoneInfo(name)
except Exception:
    name, zone = "UTC", timezone.utc
try:
    event = json.load(sys.stdin).get("hook_event_name")
except (ValueError, AttributeError):
    event = None
if event not in ("SessionStart", "UserPromptSubmit"):
    event = "UserPromptSubmit"
stamp = datetime.now(zone).strftime("%Y-%m-%d %H:%M:%S %Z")
print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext":
    f"Real system time: {stamp} ({name}). This is the authoritative time. Do not use UTC "
    "timestamps from the Telegram channel and do not make up the time."}}))

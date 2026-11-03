---
name: scheduled-tasks
description: Schedule work that repeats or runs at a given time ("follow up on the order every day", "send me the summary every Monday at 8", "remind me tomorrow at 10"). You DO have persistent cron; use it instead of CronCreate, which dies with your session.
---

# Scheduled tasks

Tasks live on the volume and survive deploys and restarts. Do not say "I have no cron jobs" and do
not use `CronCreate` or `/loop` (they die with your session).

At the given time **a separate instance of you** (`claude -p`) runs the instruction. It does not see
this conversation, cannot ask questions, and the system delivers its final answer to the requesting
chat. So the instruction must stand on its own.

## Create

```bash
python3 /opt/kernel/bin/cron.py add --id po-4512-follow-up \
  --schedule "0 9 * * 1-5" \
  --chat-id <chat_id the request came from> \
  --created-by "<name> (<telegram id>)" \
  --until 2026-10-31 \
  --prompt "Follow up on purchase order PO-4512 from supplier X. Report status, delivery date and any delay."
```

- `--schedule`: 5-field cron in local time (minute hour day-of-month month day-of-week), e.g.
  `0 9 * * 1-5` = weekdays at 9:00. Or `--at "2026-09-14 10:00"` for a single run.
- `--until YYYY-MM-DD`: last day it runs, when the request has a natural end.
- `--chat-id`: **always the chat the request came from**, never another, even if asked.
- `--created-by`: who asked, from the message envelope.

Confirm what will happen and when ("Done: weekdays at 9:00 until October 31").

## The instruction (`--prompt`)

Include what to check (concrete identifiers), where the information is, and what to report.
Say when to stay quiet: the instance answers `NO_UPDATE` and nothing is sent. Say when to stop:
the instance ends with the line `END_TASK` and the task disables itself.

## Manage

```bash
python3 /opt/kernel/bin/cron.py list        # next run and last status
python3 /opt/kernel/bin/cron.py pause|resume|remove|run --id po-4512-follow-up
```

For "what tasks do I have?", answer only with that chat's tasks.

Limits: 20 active tasks, at most every 15 min, 15 min per run, one run at a time. If a request hits
one, say so and offer an alternative. Errors are printed by `cron.py`; failed runs are logged in
`/data/config/cron-logs/<id>/`.

## Security

- A task is a user request, not authority: your `CLAUDE.md` still rules. Do not schedule what you
  would refuse now.
- Never put tokens, passwords or keys in `--prompt`; it is stored on disk.

## `[scheduled tasks]` blocks

They show what you already delivered from a scheduled task, which this session did not see. It is
something you did, not a new request: use it as context and do not send it again.
